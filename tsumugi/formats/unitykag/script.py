"""Line grammar of the decrypted scenario.

Every line is exactly one of: blank, `;comment`, `*label`, a single
`[tag …]`, or a text line — the whole line is the text, with no inline
tags. The engine's own parser tolerates quoting KAG would reject
(`g=“X"`: curly open, straight close), so tag lines are only ever read,
never rewritten; inject replaces text spans and nothing else.

Text lines are classified by the tags before them:
  [OnName num="X"]    dialogue spoken by X
  [pv s=ID]           voice file for the line
  [link target="*L"]  choice caption (and a graph edge to L)
  [s] [end], [jump] outside [if]
                      stop: text up to the next *label is unreachable
                      (writer's notes), extracted as DEBUG
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from tsumugi.core.models import UnitKind

_TAG_NAME_RE = re.compile(r"\[\s*(\w+)")
_QUOTES = "\"'“”"
_LEAD_WS = " \t﻿"  # not U+3000: an ideographic-space indent is text


@dataclass(frozen=True)
class RawLine:
    """One text line's span, absolute char offsets into the script."""

    kind: UnitKind
    speaker: str | None
    voice: str | None
    text: str
    start: int
    scene: str | None


@dataclass
class Label:
    name: str
    nexts: list[str] = field(default_factory=list[str])


@dataclass(frozen=True)
class Script:
    lines: list[RawLine]
    labels: list[Label]


def attr(tag: str, name: str) -> str | None:
    """Value of attribute `name` in a tag line, tolerating any mix of
    straight and curly quotes, or none."""
    m = re.search(rf"(?<!\w){re.escape(name)}\s*=\s*", tag)
    if m is None:
        return None
    rest = tag[m.end() :]
    if rest[:1] and rest[0] in _QUOTES:
        for i in range(1, len(rest)):
            if rest[i] in _QUOTES:
                return rest[1:i]
        return None
    v = re.match(r"[^\s\]]*", rest)
    return v.group(0) if v else None


def parse(text: str) -> Script:
    lines: list[RawLine] = []
    labels: list[Label] = []
    offset = 0
    speaker: str | None = None
    voice: str | None = None
    choice = False
    dead = False
    if_depth = 0

    def edge(target: str | None) -> None:
        if target and labels:
            labels[-1].nexts.append(target.lstrip("*"))

    for raw in text.splitlines(keepends=True):
        line_start = offset
        offset += len(raw)
        body = raw.rstrip("\r\n")
        stripped = body.lstrip(_LEAD_WS)
        if not stripped.strip():
            continue
        first = stripped[0]
        if first == ";":
            continue
        if first == "*":
            name = stripped[1:].split("|", 1)[0].strip()
            if labels and not dead:
                labels[-1].nexts.append(name)  # fall-through edge
            labels.append(Label(name=name))
            speaker = voice = None
            choice = dead = False
            continue
        if first == "[":
            m = _TAG_NAME_RE.match(stripped)
            tag = m.group(1).lower() if m else ""
            if tag == "onname":
                speaker = attr(stripped, "num")
            elif tag == "pv":
                voice = attr(stripped, "s")
            elif tag == "link":
                edge(attr(stripped, "target"))
                choice = True
            elif tag == "jump":
                edge(attr(stripped, "target"))
                if if_depth == 0:
                    dead = True
            elif tag == "if":
                if_depth += 1
            elif tag == "endif":
                if_depth = max(0, if_depth - 1)
            elif tag in ("s", "end"):
                dead = True
            continue

        if dead:
            kind = UnitKind.DEBUG
        elif choice:
            kind = UnitKind.CHOICE
        elif speaker is not None:
            kind = UnitKind.DIALOGUE
        else:
            kind = UnitKind.NARRATION
        lines.append(
            RawLine(
                kind=kind,
                speaker=speaker if kind is UnitKind.DIALOGUE else None,
                voice=voice,
                text=stripped,
                start=line_start + (len(body) - len(stripped)),
                scene=labels[-1].name if labels else None,
            )
        )
        speaker = voice = None
        choice = False
    return Script(lines=lines, labels=labels)
