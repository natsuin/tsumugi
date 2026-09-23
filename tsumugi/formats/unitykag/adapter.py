"""EngineAdapter for the Unity-hosted KAG dialect.

The scenario is one encrypted file under GameMaterial/ (container.py); its
plaintext is line-structured with no inline tags (script.py). Inject is an
exact span rewrite on the decrypted text followed by re-encryption, and the
container decoder only accepts files it reproduces byte-for-byte — so Gate
A tests the writer, and Gate B tests span rewriting plus re-encryption.
"""

from __future__ import annotations

import hashlib
import sys
from collections import defaultdict
from pathlib import Path
from typing import Iterable, Iterator

from tsumugi.core.models import (
    EngineProbe,
    EngineTextCaps,
    RoundTripResult,
    SceneNode,
    ScriptGraph,
    TextUnit,
    Workspace,
)
from tsumugi.formats.unitykag.container import decode, encode
from tsumugi.formats.unitykag.script import parse
from tsumugi.qa.gates import run_gates
from tsumugi.qa.placeholders import check_placeholder_contract

_SCRIPT_GLOB = "GameMaterial/*.dsm"
_FORBIDDEN = ("[", "]", "\r", "\n")  # would parse as a tag / split the line
_LINE_START_FORBIDDEN = (";", "*", " ", "\t")  # comment / label / trimmed


class UnityKagAdapter:
    name = "unitykag"
    caps = EngineTextCaps(
        source_encoding="utf-8",
        renders_utf8=True,
        # No in-text break code exists in the dialect. Boot-tested on a Tier 3
        # title (2026-09-22): Latin renders fixed-width and the window wraps
        # per character at its edge — no word wrap — so Stage 7 must pre-wrap
        # (space padding, or a break mechanism found in the renderer).
        break_code="",
        max_lines=None,
        ruby_syntax=None,
        proportional_fonts=False,
        var_interpolation=False,
    )

    def probe(self, game_dir: Path) -> EngineProbe | None:
        scripts = sorted(game_dir.glob(_SCRIPT_GLOB))
        if not scripts:
            return None
        evidence = [f"{len(scripts)} GameMaterial/*.dsm scenario file(s)"]
        confidence = 0.4
        if decode(scripts[0].read_bytes()) is not None:
            evidence.append(f"{scripts[0].name} decrypts and re-encrypts byte-identically")
            confidence += 0.5
        else:
            evidence.append(
                f"{scripts[0].name} does not decrypt with the known key derivation"
            )
        if any(game_dir.glob("*_Data/Managed/Assembly-CSharp.dll")):
            evidence.append("Unity Mono build (*_Data/Managed/Assembly-CSharp.dll)")
            confidence += 0.09
        return EngineProbe(engine=self.name, confidence=confidence, evidence=evidence)

    def _scripts(self, game_dir: Path) -> Iterator[tuple[str, str]]:
        """(relative path, decrypted text) per scenario file."""
        for path in sorted(game_dir.glob(_SCRIPT_GLOB)):
            rel = path.relative_to(game_dir).as_posix()
            decoded = decode(path.read_bytes())
            if decoded is None:
                print(f"skip {rel}: container does not round-trip", file=sys.stderr)
                continue
            yield rel, decoded[0]

    def extract(self, ws: Workspace) -> Iterator[TextUnit]:
        ordinal = 0
        for rel, text in self._scripts(ws.game_dir):
            for line in parse(text).lines:
                ordinal += 1
                digest = hashlib.sha256(line.text.encode("utf-8")).hexdigest()
                yield TextUnit(
                    id=f"{rel}:{line.start}:{digest[:8]}",
                    source_text=line.text,
                    speaker=line.speaker,
                    voice=line.voice,
                    kind=line.kind,
                    file=rel,
                    offset=line.start,
                    length=len(line.text),
                    ordinal=ordinal,
                    source_hash=digest,
                    scene=line.scene,
                )

    def inject(self, ws: Workspace, units: Iterable[TextUnit]) -> None:
        by_file: dict[str, list[TextUnit]] = defaultdict(list)
        for u in units:
            by_file[u.file].append(u)
        for rel, file_units in by_file.items():
            decoded = decode((ws.game_dir / rel).read_bytes())
            if decoded is None:
                raise ValueError(f"{rel}: container no longer round-trips")
            src, framing = decoded
            for u in sorted(file_units, key=lambda u: u.offset, reverse=True):
                text = u.target_text if u.target_text is not None else u.source_text
                problems = check_placeholder_contract(u, text) + _line_problems(text)
                if problems:
                    raise ValueError(f"{rel} unit {u.ordinal}: contract violated: {problems}")
                src = src[: u.offset] + text + src[u.offset + u.length :]
            out_path = ws.patched_dir() / rel
            out_path.parent.mkdir(parents=True, exist_ok=True)
            out_path.write_bytes(encode(src, framing))

    def build_graph(self, ws: Workspace) -> ScriptGraph:
        nodes: list[SceneNode] = []
        for rel, text in self._scripts(ws.game_dir):
            for label in parse(text).labels:
                nodes.append(
                    SceneNode(
                        file=rel,
                        label=label.name,
                        nexts=[f"{rel}|*{n}" for n in label.nexts],
                    )
                )
        return ScriptGraph(nodes=nodes)

    def verify_round_trip(self, ws: Workspace) -> RoundTripResult:
        return run_gates(self, ws)


def _line_problems(text: str) -> list[str]:
    out = [f"contains {c!r}" for c in _FORBIDDEN if c in text]
    if not text.strip():
        out.append("empty text would drop the line")
    elif text[0] in _LINE_START_FORBIDDEN:
        out.append(f"starts with {text[0]!r}")
    return out
