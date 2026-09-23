"""Core pydantic models: TextUnit, placeholders, probe/caps, round-trip results.

One definition serves the Python type, the JSON Schema, and validated parsing
(the schema-first lever from CLAUDE.md).
"""

from __future__ import annotations

from enum import StrEnum
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field


class PlaceholderKind(StrEnum):
    """Kinds from the docs/05 contract table."""

    LINEBREAK = "linebreak"
    PAGEBREAK = "pagebreak"
    WAIT = "wait"
    VAR = "var"
    RUBY_OPEN = "ruby_open"
    RUBY_CLOSE = "ruby_close"
    STYLE_OPEN = "style_open"
    STYLE_CLOSE = "style_close"
    VOICE = "voice"
    SE = "se"
    OPAQUE = "opaque"


class Placeholder(BaseModel):
    """One masked control code: sentinel index -> raw engine markup."""

    index: int
    raw: str
    kind: PlaceholderKind


class UnitKind(StrEnum):
    DIALOGUE = "dialogue"
    NARRATION = "narration"
    CHOICE = "choice"
    UI = "ui"
    SYSTEM = "system"
    NAME = "name"
    DEBUG = "debug"


class TextUnit(BaseModel):
    """One translatable unit. SourceText is masked; codes live in placeholders."""

    id: str
    source_text: str
    placeholders: list[Placeholder] = Field(default_factory=list[Placeholder])
    speaker: str | None = None
    # Voice file id when the engine ties one to the line: ground truth for
    # Stage 3 voice->speaker mapping (masked "???" speakers included).
    voice: str | None = None
    kind: UnitKind
    file: str
    offset: int
    length: int
    ordinal: int
    source_hash: str
    # Scene this unit belongs to (label or title), when the engine exposes it.
    scene: str | None = None
    # Escape-hatch for units whose manual breaks are semantic (poems, letters,
    # ASCII art). Stage 7 must not re-derive breaks for these.
    preserve_breaks: bool = False
    # Filled by later stages / the gates. None means "identity" on inject.
    target_text: str | None = None


class EngineProbe(BaseModel):
    """Stage 0 output: never a silent guess (docs/07)."""

    engine: str
    confidence: float = Field(ge=0.0, le=1.0)
    evidence: list[str]


class EngineTextCaps(BaseModel):
    """What Stages 5-7 need to know without caring which engine it is."""

    source_encoding: str
    renders_utf8: bool
    break_code: str
    max_lines: int | None = None
    ruby_syntax: str | None = None
    proportional_fonts: bool
    var_interpolation: bool


class SceneNode(BaseModel):
    """One scene: where it lives and which storages it flows into."""

    file: str
    label: str
    title: str | None = None
    nexts: list[str] = Field(default_factory=list[str])


class ScriptGraph(BaseModel):
    """Stage 3 reading-order input. File order is not reading order."""

    nodes: list[SceneNode] = Field(default_factory=list[SceneNode])


class GateFailure(BaseModel):
    """One failure, with values in the message (token-efficient by design)."""

    file: str
    message: str


class GateResult(BaseModel):
    gate: Literal["identity", "expansion"]
    files_checked: int
    units_checked: int
    failures: list[GateFailure] = Field(default_factory=list[GateFailure])

    @property
    def passed(self) -> bool:
        return not self.failures


class RoundTripResult(BaseModel):
    """Hard rule 2: both gates, both required."""

    identity: GateResult
    expansion: GateResult

    @property
    def passed(self) -> bool:
        return self.identity.passed and self.expansion.passed


class Workspace(BaseModel):
    """Paths for one run. game_dir is read-only to Tsumugi (hard rule 7)."""

    game_dir: Path
    work_dir: Path

    def patched_dir(self) -> Path:
        return self.work_dir / "patched"
