"""bible.map: per-window observation extraction on the local model.

Each call sees one window of consecutive units in reading order and returns
schema-constrained observations. Calls are cached in the project store
keyed by content+model+prompt, so re-runs and crashes are cheap
(checkpointing is not optional on this machine — docs/04)."""

from __future__ import annotations

import hashlib
import re
import time
from dataclasses import dataclass

import httpx

from pydantic import BaseModel, Field

from tsumugi.analysis.scenegraph import units_in_reading_order
from tsumugi.core.models import TextUnit
from tsumugi.core.store import ProjectStore
from tsumugi.llm.client import LlmBinding, OllamaClient

_SENTINEL = re.compile(r"⟦\d+⟧")

WINDOW_UNITS = 60

_SYSTEM = (
    "あなたは日本語ビジュアルノベルの校閲アシスタントです。"
    "与えられたシーン抜粋を読み、登場人物ごとの話し方の特徴を観察して、"
    "指定されたJSONスキーマだけで出力してください。\n"
    "- first_person: その人物の一人称(俺/僕/私/わたし/あたし等)。不明ならnull\n"
    "- gender_evidence: 性別が分かる根拠があれば短く。不明ならnull\n"
    "- speech_style: 話し方(敬語/タメ口/尊大/方言など)を短く\n"
    "- notes: 口癖・特徴があれば短く\n"
    "- terms: 作品固有の用語・地名・組織名など(一般語は除く)\n"
    "観察のみ。翻訳はしない。推測より不明を選ぶ。"
)


class CharacterObs(BaseModel):
    name_ja: str
    first_person: str | None = None
    gender_evidence: str | None = None
    speech_style: str | None = None
    notes: str | None = None


class WindowObservation(BaseModel):
    characters: list[CharacterObs] = Field(default_factory=list[CharacterObs])
    terms: list[str] = Field(default_factory=list[str])


@dataclass(frozen=True)
class Window:
    scene: str
    index: int
    units: list[TextUnit]


def windows_in_order(units: list[TextUnit], size: int = WINDOW_UNITS) -> list[Window]:
    out: list[Window] = []
    for start in range(0, len(units), size):
        chunk = units[start : start + size]
        scene = next((u.scene for u in chunk if u.scene), None) or chunk[0].file
        out.append(Window(scene=scene, index=start // size, units=chunk))
    return out


def _window_prompt(w: Window) -> str:
    lines: list[str] = [f"シーン: {w.scene}"]
    for u in w.units:
        text = _SENTINEL.sub("", u.source_text)
        who = u.speaker or "地の文"
        lines.append(f"{who}: {text}")
    return "\n".join(lines)


def run_map(
    store: ProjectStore,
    binding: LlmBinding,
    *,
    limit: int | None = None,
    log: bool = True,
) -> tuple[int, int, int]:
    """Run bible.map over all units. Returns (done, cached, failed)."""
    units = [r.unit for r in store.units(limit=1_000_000).rows]
    file_order = store.file_order()
    if log and not file_order:
        print("note: no scene graph in the store (run `tsumugi analyze`); using file order")
    wins = windows_in_order(units_in_reading_order(units, file_order))
    if limit is not None:
        wins = wins[:limit]

    schema = WindowObservation.model_json_schema()
    client = OllamaClient(binding)
    done = cached = failed = 0
    try:
        schema_json = str(sorted(schema.items()))
        for w in wins:
            user = _window_prompt(w)
            prompt_hash = hashlib.sha256(
                (_SYSTEM + user + schema_json).encode()
            ).hexdigest()[:16]
            key = f"map:{w.units[0].file}:{w.index}:{binding.model}:{prompt_hash}"
            if store.observation(key) is not None:
                cached += 1
                continue
            try:
                try:
                    raw = client.chat_json(_SYSTEM, user, schema)
                except httpx.HTTPError:
                    # One retry on transport/server errors: the first call
                    # after a model load 500s occasionally.
                    time.sleep(3)
                    raw = client.chat_json(_SYSTEM, user, schema)
                obs = WindowObservation.model_validate(raw)
            except Exception as e:  # noqa: BLE001 — terse, one line per failure
                failed += 1
                if log:
                    print(f"map fail {w.units[0].file}#{w.index}: {type(e).__name__}: {e}")
                continue
            store.put_observation(
                key, w.scene, binding.model, prompt_hash,
                obs.model_dump_json(),
            )
            done += 1
            if log:
                names = ", ".join(c.name_ja for c in obs.characters[:5])
                print(f"map ok {w.units[0].file}#{w.index}: {names}")
    finally:
        client.close()
    return done, cached, failed
