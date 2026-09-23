# 02 — Engines, adapters, and prior art

## The adapter contract

One interface, one folder per engine. Everything engine-specific lives behind it; no other
project may branch on engine type.

```python
class EngineAdapter(Protocol):
    caps: EngineTextCaps                                   # encoding, break code, ruby, font

    def probe(self, game_dir: Path) -> EngineProbe: ...    # confidence + evidence
    def extract(self, ws: Workspace) -> Iterator[TextUnit]: ...   # units + placeholders
    def build_graph(self, ws: Workspace) -> ScriptGraph: ...      # labels, jumps, choices
    def inject(self, ws: Workspace, units: Iterable[TextUnit]) -> None: ...
    def verify_round_trip(self, ws: Workspace) -> RoundTripResult: ...   # hard rule 2
```

A `Protocol`, not an ABC: structural typing keeps adapters decoupled from the core, and
`pyright --strict` still verifies conformance at check time. Every model in the signatures
above is a `pydantic` model, so the same definitions produce the JSON Schema used for
constrained decoding downstream.

`EngineTextCaps` is what Stages 5–7 need to know without caring which engine it is:
source encoding, whether the engine can render UTF-8 or needs an SJIS workaround, the
line-break control code, max lines per page, ruby syntax, whether proportional fonts are
supported, whether variable interpolation appears in text.

## Engine landscape

Ordered by "what you'll actually encounter," with the honest difficulty rating.

| Engine | Archives | Scripts | Difficulty | Notes |
|---|---|---|---|---|
| **Ren'Py** | `.rpa` | `.rpy` / `.rpyc` | ★☆☆☆☆ | Has a **built-in translation framework** (`tl/` trees). Injection is *supported by the engine*, not a hack. UTF-8 native, proportional fonts, no repack needed. |
| **KiriKiri / KiriKiriZ** | `.xp3` | `.ks` (TJS2) | ★★☆☆☆ | The workhorse of doujin/commercial JP VNs. Text-ish scripts, well-documented, loose-file override support (`data/` beside the xp3) makes patching easy. |
| **Unity-hosted KAG dialect** (`unitykag`) | none | `GameMaterial/*.dsm` | ★★☆☆☆ | A Unity shell running its own KAG-like interpreter. One scenario file: Base64 of AES-256-CBC (PBKDF2-SHA1 key from the widely-copied .NET sample code). Plaintext is one tag per line, text lines bare — no inline codes. Tag quoting is looser than KAG (`g=“x"`), so tag lines are never rewritten. Speaker/voice come from `[OnName]`/`[pv]` lines. No Unity asset tooling needed. |
| **NScripter / ONScripter** | none | `nscript.dat` | ★★☆☆☆ | Trivial obfuscation (XOR 0x84). Old but huge back catalogue. SJIS-locked; needs font work. |
| **TyranoScript** | loose | `.ks` + JS | ★★☆☆☆ | HTML5. Basically editable in a text editor. |
| **RPG Maker MV/MZ** | loose | JSON | ★★☆☆☆ | Not a VN engine but a lot of VN-adjacent games. JSON is easy; the hard part is classification (tons of non-dialogue strings). |
| **Artemis** | `.pfs` | `.ast` | ★★★☆☆ | Structured but proprietary. |
| **CatSystem2** | `.int` | `.cst` | ★★★☆☆ | Compressed scripts. |
| **Majiro** | `.arc` | `.mjo` | ★★★★☆ | **Compiled bytecode.** Reinjection means rewriting string tables and fixing offsets. |
| **BGI / Ethornell** | `.arc` | `._bp` | ★★★★☆ | Compiled bytecode, same problem. Very common commercially. |
| **Siglus (Key/VisualArts)** | `Scene.pck` | compiled | ★★★★★ | Encrypted, per-title key variation. Big prize, big pain. |
| **Unity VNs** | `.assets` / bundles | C# or ScriptableObjects | ★★★☆☆–★★★★★ | Wildly variable. Sometimes external JSON; sometimes hardcoded in `Assembly-CSharp.dll`. Injection is best done via a **runtime resource redirector fed a pre-translated dictionary** — that is still offline translation, just delivered at load time. |

**Bytecode engines are the real dividing line.** Text-script engines let you edit strings in
place. Bytecode engines require rebuilding string tables and patching every offset that
pointed past the edit — and English strings are *longer*, so every offset moves. Budget for
this; do not assume an adapter is a weekend.

## Prior art — interoperate, don't re-implement

**Verify every license before vendoring any of this. Treat the notes below as leads to
confirm, not as established fact.**

- **GARbro** (morkt) — C#/.NET, WPF. Reads several hundred VN archive formats. Invoked as a
  CLI subprocess (we are Python; see D19). Extraction is
  its strength; creation is spotty. *Use as:* the Stage 1 fallback for containers we haven't
  written. Shell out to its CLI rather than vendoring, at least initially.
- **VNTranslationTools / VNTextPatch** (arcusmaximus) — C#, invoked as a CLI. The closest existing thing to
  Stage 2/8: extracts script text to xlsx/json and reinserts it, across a good spread of the
  engines above. Also ships **VNTextProxy**, a DLL shim that forces proportional fonts and
  non-Shift-JIS characters into engines that can't do either. *Use as:* the reference
  implementation for adapters, and possibly a direct dependency for engines it already
  covers. This is the single biggest available head start.
- **XUnity.AutoTranslator** (bbepis) — for Unity titles, its resource redirector can consume
  a pre-built translation file. *Use as:* the Unity injection backend. Its live-translation
  mode is out of scope; the redirector is not.
- **Ren'Py SDK** — `translate` framework, `unrpa`, `unrpyc`. **All Python**, so these import
  directly rather than being shelled out — a concrete benefit of D19 for the Phase 1 walking
  skeleton. Ren'Py injection should use the engine's own translation system, not text surgery.
- **HDiffPatch / xdelta3** — binary diff for patch distribution.

### Interop rule

An external tool is allowed at Stage 1 (unpacking) and as an adapter's internal
implementation detail. It is **not** allowed to become the project's data model. Everything
lands in the same `TextUnit` table regardless of who parsed it.

## Choosing the first adapter

Two different jobs, don't conflate them:

- **Walking skeleton (Phase 1):** pick the easiest engine so the *pipeline* gets proven, not
  the parser. **Ren'Py** — a day's work, engine-supported injection, immediate end-to-end.
- **First real target (Phase 3–6):** pick the engine of a game actually worth translating.
  **KiriKiri** is the highest coverage-per-effort for Japanese VNs and supports loose-file
  overrides, which makes patch distribution clean.

Building both proves the abstraction early, which is the whole reason for Phase 7 existing.
