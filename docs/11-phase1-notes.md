# 11 — Phase 1/2 implementation notes

Written alongside the first code drop (`phase1-walking-skeleton` branch). Records the
design calls that the Phase 0 docs left open, so they can be reviewed rather than
rediscovered. Numbers 1–4 below were raised as review findings against the Phase 0 docs;
each has either a resolution in code or a note for later phases.

## 1. Gate A for Ren'Py — the resolution

The Phase 1 criterion says "Gate A produces byte-identical files," but docs/02 says Ren'Py
injection should use the engine's `tl/` framework — under which originals are never
modified, so there is nothing to byte-compare. And `.rpyc` decompile→recompile is not
byte-stable, so identity over compiled scripts is unachievable.

**Resolution implemented:** the Ren'Py adapter extracts from `.rpy` source and injects by
**exact span rewrite** of the string literals. To keep Gate A honest (not "passes because
nothing moved"):

- extraction asserts, per literal, that `canonical_escape(unescape(raw)) == raw` — a
  literal that fails is **skipped loudly**, never guessed at;
- masking asserts losslessness (balanced markup, no sentinel glyphs in source) with the
  same skip-loudly rule;
- inject therefore re-encodes every literal through the full unmask→escape path, and Gate A
  genuinely exercises the writer.

The `tl/` framework remains the intended **production** injection path (docs/06 preference
order is unchanged); span rewrite is what proves the generic round-trip machinery that
every later text-script adapter reuses, and is itself a legitimate patch path for games
shipping `.rpy` source. Both gates run over Tier 0 in CI. "The game still boots" remains a
manual, dated result per docs/10 — it needs a Ren'Py runtime, which CI doesn't have.

## 2. Rolling context vs. parallel slots (Stage 5, noted for Phase 4)

Stage 5's rolling context makes chunk N+1 depend on chunk N's output, which conflicts with
the parallel-slots throughput multiplier in docs/04 if applied naively. Note for Phase 4:
**parallelism is across scenes/routes; translation is sequential within a scene.** The
scene segmentation from Stage 3 is what makes this well-defined.

## 3. Dedupe threshold (Stage 3, noted for Phase 2/4)

"Duplicates translate once" is unsafe for short context-dependent lines (「うん」 →
"Yeah." / "Mm-hm." / "…Okay."). Note for Stage 3: share translations only above a length
threshold (suggest ≥ 10 characters, configurable), or dedupe keyed on
`(source_hash, speaker)`. Validator 11 only warns on divergence; nothing catches forced
*convergence*, so the threshold is the defence.

## 4. Semantic linebreaks (Stage 2/7)

docs/05 strips `linebreak` codes unconditionally. Some scripts use manual breaks
semantically (poems, letters, formatted text). `TextUnit.preserve_breaks` exists as of this
drop; Stage 7 must respect it. Ren'Py needs no stripping (proportional UTF-8, engine
reflows), so the field is dormant until the KiriKiri adapter.

## Phase 1 scope: what the Ren'Py adapter does NOT yet do

Recorded so nobody mistakes the skeleton for coverage:

- **Double-quoted, single-line strings only.** No `'…'`, no `"""…"""`, no monologue mode.
- **No `.rpa` unpacking and no `.rpyc`** — loose `.rpy` source only (the SDK demo and Tier 0
  fixtures satisfy this). `.rpa` is Stage 1 work; `.rpyc` extraction may never be needed if
  `unrpyc` output is treated as source.
- **No `voice`-statement pairing** (Stage 3 concern), no `label`/scene segmentation.
- `tl/` directories are skipped on extract, so an already-translated game isn't re-extracted.

## Phase 2: project store + read-only workbench

- `tsumugi/core/store.py` — one SQLite file per game. The units-table DDL is
  **generated from the TextUnit pydantic model** (the schema-first lever); only
  store-side columns (`status`) are declared by hand. Duplicate counts come from a
  `source_hash` group join, so the workbench shows ×N badges with no extra pass.
- `tsumugi/studio/` — FastAPI host + a single-file, dependency-free workbench page
  (offline tool: no webfonts, no CDN). Bilingual table, filters (file / speaker /
  kind / free-text / duplicates-only), stats header, pagination.
- Phase 2 is read-only, so `replace_units` is a full swap; hard rule 6 (locked
  lines survive re-runs) becomes binding when writes land in Phase 4 — the
  `status` column is already there for it.
- The roadmap's Phase 2 criterion says "reading order"; true reading order is the
  Stage 3 graph (Phase 3). Until then the table is file/ordinal order.

## KiriKiri adapter (family 2: archive + text script)

Second adapter, driven by a real Tier 3 target (encrypted KiriKiriZ title, XP3 v2).

- **`tsumugi/archives/xp3.py`** — clean-room XP3 reader: index parse for any
  archive, extraction for unencrypted ones. Commercial titles set the protect
  flag (per-title cxdec cipher); those are *reported with a workflow*, never
  guessed at. Writing (patch2.xp3) is Phase 6; revisit `construct` then.
- **Encrypted-title workflow** (hard rule 7 keeps Tsumugi from writing into the
  game dir, so the one-time dump is a user step): KirikiriTools' version.dll
  (arcusmaximus — already our docs/02 vendor) dumps decrypted files as the
  engine loads them; for `.scn`-based (KAGEnvPlayer) titles,
  `tsumugi krkr-dump-script` prints the appconfig.tjs that force-loads every
  scene so one run dumps everything. `tsumugi unpack` prints all of this when
  it meets a protected archive.
- **`.ks` (KAG) parsing** — line-start grammar (`;` comment, `*` label, `@`
  command, else text), 【名前】/【名前/表示名】 speaker prefixes,
  `[iscript]…[endscript]` skipped, quoted attribute values honored in tag
  scanning, `[[` literal brackets. Per-file encoding (cp932 / UTF-16LE / UTF-8)
  is detected and verified to re-encode byte-identically before extraction;
  Tier 0 commits one cp932 and one UTF-16LE fixture so both stay proven in CI.
- **Linebreak reconciliation (docs/05 vs Gate A):** `[r]` is masked with kind
  `linebreak` and *kept* in the unit — if Stage 2 stripped it, identity could
  never round-trip. The docs/05 "model never sees linebreaks" rule moves to
  Stage 5 prompt assembly, which drops linebreak-kind sentinels on the way to
  the model and Stage 7 re-derives them. Extraction stays lossless.
- **`.scn` caveat:** KAGEnvPlayer-era titles compile scenarios to PSB `.scn`
  binaries instead of (or alongside) `.ks`. The adapter currently handles `.ks`
  only; if a dump yields `.scn`, that is a separate parser (FreeMote/PSB prior
  art) — scoped when a real dump shows it's needed.

## KiriKiri scrambled text codec (`kstext.py`) — found via the real target

A KirikiriTools dump of the Tier 3 target title showed that storage-decrypted
`.ks`/`.tjs`/`.csv`/`.txt` are still wrapped in KiriKiri's own text-file
container: `0xFE 0xFE`, a mode byte, a `0xFF 0xFE` BOM, then transformed
UTF-16LE. Reimplemented from KirikiriTools' `Descrambler.cs` (MIT), verified
against real files:

- **mode 0** conditional XOR (self-inverse); **mode 1** 16-bit bit-swap
  `((c&0xAAAA)>>1)|((c&0x5555)<<1)` (self-inverse; what the target uses);
  **mode 2** zlib/deflate.
- Modes 0/1 are involutions, so re-encoding an unchanged file is byte-identical
  — Gate A holds. `decode()` proves this per file with an `encode(decode(x))==x`
  guard and skips loudly on failure. Mode 2 is decode-only (zlib output isn't
  byte-reproducible); no mode-2 file has appeared in the target.
- Plain cp932 / UTF-16 / UTF-8 files still go through `detect_encoding`.
- Tier 0 gains a committed mode-1 scrambled fixture so CI exercises the codec.

**State of the real target:** the title is `.scn`-based after all — playing
into the story dumped 16 `*.txt.scn` scenario files (raw PSB v3, uncompressed,
unencrypted after the KirikiriTools dump). `.ks` on this title is
engine/system script only. Per hard rule 4 and Q7, the specific title, its
file prefixes, and its cast are deliberately not named in this public repo.

## PSB v3 reader + .scn extraction (the real scenario path)

- **`psb.py`** — read-only PSB v2/v3 parser reimplemented from FreeMote
  (Psb.cs/PsbValues.cs): width-prefixed little-endian numbers, the
  `<count-width><count><entry-width><entries>` array packing, the
  charset/namesData/nameIndexes trie for object keys, UTF-8 string table.
- **`scn.py`** — scenario extraction. Observed shape:
  `root.scenes[].texts[i] = [display|null, [[label|null, text, len]…],
  voice, flags, stage]`; each take of a line is its own unit; speaker =
  display or take label; kind = dialogue/narration by speaker presence.
- **Extract-only, deliberately.** Writing PSB (offset/string-table rebuild)
  is exactly the Phase 6 / family-3 job the roadmap warns about; until it
  exists the identity gate reports `.scn` files as "no write path for this
  format yet" instead of pretending (hard rule 2 — no translated build for
  this title until that lands). Phase 2 browsing needs only extraction.
- **Inline `%`-codes and backslash-codes in .scn text.** A corpus scan of the
  full title found `%p…;` / `%f…;` / `%NN;` style switches (font names may
  contain spaces — the arg runs to the `;`) and `\n` / `\k` / `\x` controls
  inside scenario text. `mask(scn_codes=True)` masks both families; a bare
  `%` in prose (１００%) stays text. Grammar comes from the scan, not guesses.
- **Verified on the full target dump:** 47,571 units from 226 scenario files
  (22,648 dialogue / 24,923 narration), 17 speakers, 4,259 units in 955
  duplicate groups, 7,238 masked control codes, zero raw codes remaining in
  stored source text. The KirikiriTools force-load appconfig (printed by
  `tsumugi krkr-dump-script`) dumps every scenario in one boot — confirmed
  working on the target.

## Phase 3: analysis + bible (first increment)

- **`tsumugi/analysis/`** — Stage 3, deterministic, zero LLM (docs/01).
  `scenegraph.py`: reading order by BFS over `SceneNode.nexts` from the entry
  scenes; unreachable files are appended, never dropped. The graph comes
  through the new `EngineAdapter.build_graph()` protocol method (hard rule 8:
  analysis never knows the engine). `terms.py`: regex morphology — katakana
  runs + kanji compounds, frequency-ranked, speaker names auto-tagged so the
  glossary can exclude them. SudachiPy/fugashi remains the planned upgrade
  once dictionary licensing is verified; same interface.
- **`tsumugi/llm/client.py`** — Ollama client with docs/04 rules baked in:
  explicit `num_ctx` on every call, schema-constrained decode via `format`,
  [stable system][volatile user] prompt split for KV prefix reuse. Bindings
  are per-task (`LlmBinding`), never hardcoded in a stage.
- **`tsumugi/bible/`** — `mapper.py`: bible.map over ~60-unit windows in
  reading order; observations (first person, speech style, gender evidence,
  terms) cached in the store keyed by content+model+prompt+schema hash, so
  crashes and re-runs are cheap. `draft.py`: deterministic aggregation into
  cast/*.yaml + glossary.yaml + style.yaml — disagreements are surfaced as
  `conflicts:` on the card, never silently resolved (docs/03 pass C rule).
  The LLM reduce pass for conflict resolution is still to come.
- **Approval gate plumbed:** `bible-draft` writes `bible_approved=false` to
  meta; `tsumugi bible-approve` flips it; Stage 5 must refuse to start
  otherwise (hard rule 5).
- **On the target:** `analyze` resolves 254 scenes across 226 files to a
  single entry scene and mines 3,293 term candidates. bible.map piloted on
  the locally installed 31B (the docs/04 "fits barely" row).
- **Map windows run in graph reading order.** `run_map` sorts units by
  their file's `scenes.order_index` (`units_in_reading_order`), then
  ordinal; files the graph doesn't cover go last in file-name order. With
  no scene graph (analyze not run, or Ren'Py today) it falls back to file
  order and says so. Where the two orders coincide (the Tier 3 title's
  linear chapter naming), the windows and their cache keys are unchanged.

## Running it

```
uv sync --group dev
uv run pytest                             # gates + parser + store + API tests
uv run pyright                            # strict, hard rule 9
uv run tsumugi probe   tests/fixtures/renpy_tier0
uv run tsumugi gates   tests/fixtures/renpy_tier0
uv run tsumugi extract <renpy-game-dir> --project game.tsumugi
uv run tsumugi serve   game.tsumugi       # workbench on http://127.0.0.1:8788
```
