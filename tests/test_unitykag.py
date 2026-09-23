"""Hard rule 2 + extraction shape for the Unity-hosted KAG dialect (Tier 0)."""

import base64
from pathlib import Path

import pytest

from tsumugi.core.models import TextUnit, UnitKind, Workspace
from tsumugi.formats import detect
from tsumugi.formats.unitykag.adapter import UnityKagAdapter
from tsumugi.formats.unitykag.container import decode

FIXTURE = Path(__file__).parent / "fixtures" / "unitykag_tier0"
DSM = FIXTURE / "GameMaterial" / "data.dsm"


def _units(tmp_path: Path) -> list[TextUnit]:
    return list(UnityKagAdapter().extract(Workspace(game_dir=FIXTURE, work_dir=tmp_path)))


def test_container_decodes_and_refuses_foreign_input() -> None:
    decoded = decode(DSM.read_bytes())
    assert decoded is not None, "fixture container must round-trip"
    text, framing = decoded
    assert text.startswith("\r\n*start\r\n"), repr(text[:20])
    assert framing.prefix == b"\xef\xbb\xbf" and framing.suffix == b"\n", framing
    assert decode(b"\xef\xbb\xbfnot base64!\n") is None
    # Valid Base64, 16 bytes, but not our ciphertext: padding check refuses.
    assert decode(base64.b64encode(bytes(range(16))) + b"\n") is None


def test_probe(tmp_path: Path) -> None:
    probes = detect(FIXTURE)
    assert probes and probes[0].engine == "unitykag", probes
    assert probes[0].confidence >= 0.9, probes[0]


def test_gate_a_identity(tmp_path: Path) -> None:
    result = UnityKagAdapter().verify_round_trip(Workspace(game_dir=FIXTURE, work_dir=tmp_path))
    assert result.identity.passed, [f.message for f in result.identity.failures]
    assert result.identity.files_checked == 1
    assert result.identity.units_checked == 15, result.identity.units_checked


def test_gate_b_expansion(tmp_path: Path) -> None:
    result = UnityKagAdapter().verify_round_trip(Workspace(game_dir=FIXTURE, work_dir=tmp_path))
    assert result.expansion.passed, [f.message for f in result.expansion.failures]


def test_extraction_shape(tmp_path: Path) -> None:
    units = _units(tmp_path)
    kinds = [u.kind for u in units]
    assert kinds.count(UnitKind.DIALOGUE) == 4, kinds
    assert kinds.count(UnitKind.CHOICE) == 2, kinds
    # Notes after [s], text after an unconditional [jump], text after [end].
    dead = [u.source_text for u in units if u.kind is UnitKind.DEBUG]
    assert dead == ["１、すぐに起きる", "２、もう少し寝る", "メモ：ここは表示されない", "test"], dead

    masked = units[1]
    assert (masked.speaker, masked.voice) == ("？？？", "Erika001"), masked
    assert units[3].speaker == "真琴" and units[3].voice is None, units[3]
    # Ideographic-space indent is part of the text, not trimmed.
    assert any(u.source_text.startswith("　窓の外") for u in units)
    # Tag lines (incl. the curly/straight quoted one) are never units.
    assert not any("[" in u.source_text or "“" in u.source_text for u in units)
    assert units[-1].scene == "bad", units[-1].scene


def test_graph_edges(tmp_path: Path) -> None:
    graph = UnityKagAdapter().build_graph(Workspace(game_dir=FIXTURE, work_dir=tmp_path))
    nexts = {n.label: [x.split("|*")[1] for x in n.nexts] for n in graph.nodes}
    assert nexts == {
        "start": ["select00_1", "select00_2"],  # links; [s] stops fall-through
        "select00_1": ["Scene002"],  # unconditional jump
        "select00_2": ["Scene002"],  # fall-through
        "Scene002": ["bad"],  # conditional jump; [end] stops fall-through
        "bad": [],
    }, nexts


@pytest.mark.parametrize(
    "bad", ["[r]broken", "two\r\nlines", ";comment", "*label", " lead", "   "]
)
def test_inject_rejects_line_breaking_text(tmp_path: Path, bad: str) -> None:
    units = _units(tmp_path)
    units[0].target_text = bad
    with pytest.raises(ValueError, match="contract violated"):
        UnityKagAdapter().inject(Workspace(game_dir=FIXTURE, work_dir=tmp_path), units)
