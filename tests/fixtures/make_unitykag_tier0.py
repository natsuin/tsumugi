"""Regenerates tests/fixtures/unitykag_tier0/GameMaterial/data.dsm.

Tier 0 (synthetic, committable): every construct seen in the dialect —
curly/straight mixed quoting, masked "???" speaker with a voice, an
ideographic-space indent, a choice block with dead notes after [s], a
conditional jump, and dead text after [end].

    uv run python tests/fixtures/make_unitykag_tier0.py
"""

from __future__ import annotations

from pathlib import Path

from tsumugi.formats.unitykag.container import Framing, encode

SCRIPT = """
*start
;//登場人物メモ
[FO layer="A"]
[BG g="black"]
[OnMes]
朝の光がカーテンの隙間から差し込んでいた。
[cpg]

[FG g=“chr_a_01" f="71" pos="C"]
[pv s=Erika001]
[OnName num="？？？"]
「おはよう。まだ寝てるの？」
[cpg1]

[pv s=Erika002]
[OnName num="エリカ"]
「ほら、起きて。遅刻するよ」
[cpg1]

[OnName num="真琴"]
「……あと五分だけ」
[cpg1]

　窓の外では、鳥が鳴いていた。
[cpg]

;//■選択肢
[SQ]
[link target="*select00_1"]
すぐに起きる
[link target="*select00_2"]
もう少し寝る
[s]
１、すぐに起きる
２、もう少し寝る

*select00_1
[eval exp="flag = 0"]
布団を跳ねのけて起き上がった。
[cpg]
[jump target="*Scene002"]
メモ：ここは表示されない

*select00_2
[eval exp="flag = 1"]
もう一度、目を閉じた。
[cpg]

*Scene002
[if exp="flag == 1"]
[jump target="*bad"]
[endif]
[OnName num="エリカ"]
「よし、行こう！」
[cpg1]
[end]
test

*bad
結局、学校には間に合わなかった。
[cpg]
[s]
""".replace("\n", "\r\n")

OUT = Path(__file__).parent / "unitykag_tier0" / "GameMaterial" / "data.dsm"

if __name__ == "__main__":
    OUT.parent.mkdir(parents=True, exist_ok=True)
    framing = Framing(password=b"pass", prefix=b"\xef\xbb\xbf", suffix=b"\n")
    OUT.write_bytes(encode(SCRIPT, framing))
    print(f"wrote {OUT} ({OUT.stat().st_size} bytes)")
