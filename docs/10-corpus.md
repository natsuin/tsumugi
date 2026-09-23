# 10 — Test corpus

A generic tool's correctness claim is "round-trip holds across real games." That requires
real game files, which cannot live in this repo (hard rule 4). This document is how that is
resolved.

---

## The two round-trip gates

**Gate A — identity.** Extract → reinject *unchanged* → byte-identical file.
Proves the reader and writer are inverses.

**Gate B — expansion.** Extract → reinject text ~2× longer (ASCII filler matching the real
length ratio) → the file still parses, the archive still loads, **the game still boots and
reaches the affected line**.
Proves offset fixup, string-table rebuilding, and container repacking.

**Gate A alone is not sufficient and it is easy to be fooled by it.** Nothing moves during an
identity round-trip, so every offset in the file is still correct by accident. Gate B is the
one that catches the class of bug that silently corrupts a bytecode engine's script — which
is precisely the class you meet as adapter coverage widens. Both gates are required before an
adapter may produce a translated build.

A third, cheaper check worth running continuously: **mutation fuzzing.** Take extracted units,
apply structurally valid but length-changing mutations at random, reinject, verify parse.
Catches fixup bugs that a single fixed expansion factor happens to miss.

---

## Corpus tiers

The repo stores a **manifest and a harness, never game files.** Corpus material lands in a
gitignored local directory; CI fetches what it is allowed to fetch.

### Tier 0 — synthetic fixtures ✅ *committable*
Hand-authored minimal script files, one per engine, exercising every control code, opcode,
ruby form, and variable interpolation the adapter claims to support. These are **authored by
us**, not extracted from anything, so they live in the repo and run in CI unconditionally.

This is the tier that unblocks generic development: an adapter's reader and writer can be
built and gated against synthetic fixtures **without any real game present.** A real game is
then only needed for the integration test, not for the whole development loop.

### Tier 1 — open / redistributable samples
Engine SDKs and open projects that ship demo content under terms that permit redistribution
(Ren'Py's bundled demo projects are the clearest example; several engines publish sample
projects). CI may cache these. **Verify each one's license individually before adding it** —
"it's a demo" is not a license.

### Tier 2 — freely downloadable, not redistributable
Free doujin and indie VNs. Legal to download, generally not legal to mirror. Manifest stores
the source URL and a hash; the harness downloads on demand into the local corpus dir. Runs
locally; runs in CI only if the source permits automated fetch.

### Tier 3 — user-owned commercial games
Never in CI, never fetched, never mirrored. Manifest entries are `source: local` plus a build
hash so the harness can confirm it's testing the build it thinks it is. This is where real
coverage of the hard engines comes from.

---

## Manifest shape

```yaml
- id: renpy_demo_question
  engine: renpy
  tier: 1
  source: { kind: url, url: "…", sha256: "…" }
  gates: [identity, expansion]
  expect: { units_min: 400, encodings: [utf8] }

- id: local_kirikiri_title_a
  engine: kirikiri_z
  tier: 3
  source: { kind: local, hint: "set TSUMUGI_CORPUS_DIR" }
  build_hash: { "data.xp3": "sha256:…" }
  gates: [identity, expansion, boot]
```

`gates: [boot]` means a human (or a scripted launch + screenshot) confirmed the patched build
starts and renders the affected scene. It cannot be fully automated for most engines; record
it as a dated manual result rather than pretending CI covers it.

---

## Coverage target: families, not engine count

Supporting fifteen engines from one family proves less than supporting one from each of four.
The core is generic when it survives all four **without changes outside `tsumugi/formats/`**:

| Family | Characteristic | Representative |
|---|---|---|
| **Text script, loose files** | Strings editable in place, no container | Ren'Py, TyranoScript |
| **Archive + text script** | Container repack, encoding/font work | KiriKiri, NScripter |
| **Compiled bytecode** | String-table rebuild, offset fixup — Gate B matters most here | Majiro, BGI/Ethornell |
| **Managed runtime** | Text in assemblies/assets; injection via resource redirection | Unity |

Engine ≠ runtime: a Unity game that runs its *own* script interpreter over an encrypted
script file is **archive + text script**, not managed runtime — its text never touches
Unity assets (`unitykag`, Tier 0 fixture + a local Tier 3 title, both gates pass 2026-09-22).

Coverage inside a family is incremental work. Coverage of a *new* family is where the
abstraction gets tested — so the adapter order is deliberately one per family first, breadth
second.
