"""Reading order from the scene graph. File order is not reading order —
the order here comes from following each scene's `nexts` edges from the
entry points (scenes nothing links to)."""

from __future__ import annotations

from collections import deque

from tsumugi.core.models import SceneNode, ScriptGraph, TextUnit


def units_in_reading_order(
    units: list[TextUnit], file_order: dict[str, int]
) -> list[TextUnit]:
    """Units sorted by their file's reading-order index, then ordinal.
    Files the graph doesn't cover go last in file-name order — kept, never
    dropped (same rule as unreachable scenes below)."""
    last = len(file_order)
    return sorted(units, key=lambda u: (file_order.get(u.file, last), u.file, u.ordinal))


def _storage_to_file(storage: str, files: set[str]) -> str | None:
    """Match a `nexts` storage ref ('name.txt' / 'name.txt|*label') to a
    node file ('name.txt.scn')."""
    base = storage.split("|")[0]
    for cand in (base, base + ".scn"):
        if cand in files:
            return cand
    return None


def reading_order(graph: ScriptGraph) -> list[tuple[SceneNode, int]]:
    """(node, order_index) in reading order: BFS from entry scenes (no
    incoming edges), unresolved/unreached nodes appended in file order at
    the end so nothing is lost."""
    files = {n.file for n in graph.nodes}
    by_file: dict[str, list[SceneNode]] = {}
    for n in graph.nodes:
        by_file.setdefault(n.file, []).append(n)

    incoming: set[str] = set()
    for n in graph.nodes:
        for nx in n.nexts:
            f = _storage_to_file(nx, files)
            if f is not None and f != n.file:
                incoming.add(f)

    entries = sorted(f for f in files if f not in incoming)
    order: list[str] = []
    seen: set[str] = set()
    queue = deque(entries)
    while queue:
        f = queue.popleft()
        if f in seen:
            continue
        seen.add(f)
        order.append(f)
        for node in by_file[f]:
            for nx in node.nexts:
                t = _storage_to_file(nx, files)
                if t is not None and t not in seen:
                    queue.append(t)
    for f in sorted(files - seen):  # unreachable: keep, flagged by position
        order.append(f)

    index_of = {f: i for i, f in enumerate(order)}
    out: list[tuple[SceneNode, int]] = []
    for n in graph.nodes:
        out.append((n, index_of[n.file]))
    out.sort(key=lambda t: (t[1], t[0].label))
    return out
