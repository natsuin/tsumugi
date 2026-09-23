"""Engine adapters. The ONLY place engine-specific logic may live (hard rule 8)."""

from __future__ import annotations

from pathlib import Path

from tsumugi.core.adapter import EngineAdapter
from tsumugi.core.models import EngineProbe
from tsumugi.formats.kirikiri.adapter import KirikiriAdapter
from tsumugi.formats.renpy.adapter import RenpyAdapter
from tsumugi.formats.unitykag.adapter import UnityKagAdapter


def all_adapters() -> list[EngineAdapter]:
    return [RenpyAdapter(), KirikiriAdapter(), UnityKagAdapter()]


def detect(game_dir: Path) -> list[EngineProbe]:
    """Stage 0: every adapter's probe, sorted by confidence. Never silently
    picks — the caller shows evidence to the user (docs/07)."""
    probes = [p for a in all_adapters() if (p := a.probe(game_dir)) is not None]
    return sorted(probes, key=lambda p: p.confidence, reverse=True)
