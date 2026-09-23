"""Stage 3 units: reading order and term mining. No LLM anywhere here."""

from pathlib import Path

from tsumugi.analysis.scenegraph import reading_order, units_in_reading_order
from tsumugi.analysis.terms import mine_terms
from tsumugi.core.models import SceneNode, ScriptGraph, TextUnit, UnitKind
from tsumugi.core.store import ProjectStore


def _unit(text: str, speaker: str | None = None, n: int = 0) -> TextUnit:
    return TextUnit(
        id=f"u{n}", source_text=text, speaker=speaker,
        kind=UnitKind.DIALOGUE if speaker else UnitKind.NARRATION,
        file="f.scn", offset=n, length=len(text), ordinal=n, source_hash=f"h{n}",
    )


def test_reading_order_follows_nexts_not_file_names() -> None:
    # z_intro chains to a_middle chains to m_end: alphabetical order would
    # be wrong; the graph must win.
    graph = ScriptGraph(
        nodes=[
            SceneNode(file="a_middle.txt.scn", label="*mid", nexts=["m_end.txt"]),
            SceneNode(file="m_end.txt.scn", label="*end", nexts=[]),
            SceneNode(file="z_intro.txt.scn", label="*start", nexts=["a_middle.txt"]),
        ]
    )
    ordered = reading_order(graph)
    files = [n.file for n, _ in ordered]
    assert files == ["z_intro.txt.scn", "a_middle.txt.scn", "m_end.txt.scn"], files
    assert [i for _, i in ordered] == [0, 1, 2]


def test_reading_order_keeps_unreachable_files() -> None:
    graph = ScriptGraph(
        nodes=[
            SceneNode(file="a.scn", label="*a", nexts=[]),
            SceneNode(file="orphan.scn", label="*o", nexts=[]),
        ]
    )
    ordered = reading_order(graph)
    assert {n.file for n, _ in ordered} == {"a.scn", "orphan.scn"}


def test_units_follow_graph_order_not_file_order(tmp_path: Path) -> None:
    # Store order is file/ordinal (a_middle before z_intro); the graph says
    # z_intro is read first. Uncovered files (system.ks) go last, kept.
    def u(file: str, n: int) -> TextUnit:
        return _unit(f"{file}{n}", n=n).model_copy(update={"id": f"{file}:{n}", "file": file})

    store = ProjectStore(tmp_path / "p.tsumugi")
    store.replace_units(
        [u("a_middle.scn", 1), u("system.ks", 1), u("z_intro.scn", 2), u("z_intro.scn", 1)]
    )
    store.replace_scenes(
        [("z_intro.scn", "*s", None, 0, "[]"), ("a_middle.scn", "*m", None, 1, "[]")]
    )
    stored = [r.unit for r in store.units(limit=10).rows]
    ordered = units_in_reading_order(stored, store.file_order())
    got = [x.id for x in ordered]
    assert got == ["z_intro.scn:1", "z_intro.scn:2", "a_middle.scn:1", "system.ks:1"], got
    store.close()


def test_mine_terms_ranks_and_tags() -> None:
    units = [
        _unit("ルミナの魔導書は白鷺学園にある。", n=1),
        _unit("エリカ、それは魔導書だ。", "エリカ", 2),
        _unit("ルミナと魔導書と白鷺学園。", n=3),
        _unit("エリカは笑った。", n=4),
    ]
    terms = {t: (c, k) for t, c, k, _ in mine_terms(units, min_count=2)}
    assert terms["ルミナ"][0] == 2
    assert terms["魔導書"] == (3, "kanji")
    assert terms["白鷺学園"] == (2, "kanji")
    # Speakers are tagged so the glossary can exclude them.
    assert terms["エリカ"][1] == "speaker"


def test_mine_terms_ignores_sentinels_and_stopwords() -> None:
    units = [
        _unit("⟦0⟧先輩⟦1⟧と自分と時間。", n=1),
        _unit("先輩と自分と時間。", n=2),
        _unit("先輩と自分と時間。", n=3),
    ]
    mined = {t for t, _, _, _ in mine_terms(units, min_count=2)}
    assert "自分" not in mined and "時間" not in mined  # stopworded
