"""The project store: one SQLite file per game (`.tsumugi`).

The units table DDL is generated from the TextUnit pydantic model — one
definition yields the Python type, the JSON Schema, and the DDL (CLAUDE.md:
generate, don't hand-write). Columns the model doesn't know about (status,
provenance) are added explicitly below.
"""

from __future__ import annotations

import json
import sqlite3
import types
import typing
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Literal

from pydantic import BaseModel

from tsumugi.core.models import TextUnit

UnitStatus = Literal["machine", "edited", "approved", "locked", "failed", "pending"]


class StoreStats(BaseModel):
    total_units: int
    by_kind: dict[str, int]
    speakers: dict[str, int]
    files: list[str]
    duplicate_groups: int
    duplicate_units: int

_SCALAR_SQL: dict[type, str] = {str: "TEXT", int: "INTEGER", bool: "INTEGER", float: "REAL"}


def _column_sql(name: str, annotation: object) -> str:
    """SQL column for one pydantic field. Unions with None become nullable;
    anything non-scalar is stored as JSON TEXT."""
    nullable = False
    ann = annotation
    if typing.get_origin(ann) in (typing.Union, types.UnionType):
        args = [a for a in typing.get_args(ann) if a is not type(None)]
        nullable = len(args) < len(typing.get_args(ann))
        ann = args[0] if len(args) == 1 else object
    sql_type = _SCALAR_SQL.get(ann, "TEXT") if isinstance(ann, type) else "TEXT"
    null_sql = "" if nullable else " NOT NULL"
    pk = " PRIMARY KEY" if name == "id" else ""
    return f"{name} {sql_type}{null_sql}{pk}"


def _units_ddl() -> str:
    cols = [
        _column_sql(name, field.annotation)
        for name, field in TextUnit.model_fields.items()
    ]
    cols.append("status TEXT NOT NULL DEFAULT 'pending'")
    return f"CREATE TABLE IF NOT EXISTS units ({', '.join(cols)})"


_JSON_FIELDS = {"placeholders"}
_UNIT_COLS = list(TextUnit.model_fields) + ["status"]


@dataclass(frozen=True)
class UnitRow:
    """One workbench row: the unit plus its store-side annotations."""

    unit: TextUnit
    status: str
    dup_count: int


@dataclass(frozen=True)
class UnitPage:
    total: int
    rows: list[UnitRow]


class ProjectStore:
    def __init__(self, path: Path) -> None:
        self.path = path
        self._db = sqlite3.connect(path)
        self._db.row_factory = sqlite3.Row
        self._db.executescript(
            f"""
            {_units_ddl()};
            CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS scenes (
                file TEXT NOT NULL, label TEXT NOT NULL, title TEXT,
                order_index INTEGER, nexts TEXT NOT NULL,
                PRIMARY KEY (file, label)
            );
            CREATE TABLE IF NOT EXISTS terms (
                term TEXT PRIMARY KEY, count INTEGER NOT NULL,
                kind TEXT NOT NULL, sample TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS observations (
                key TEXT PRIMARY KEY, scene TEXT NOT NULL, model TEXT NOT NULL,
                prompt_hash TEXT NOT NULL, payload TEXT NOT NULL,
                created TEXT NOT NULL DEFAULT (datetime('now'))
            );
            CREATE INDEX IF NOT EXISTS idx_units_hash ON units (source_hash);
            CREATE INDEX IF NOT EXISTS idx_units_file ON units (file);
            CREATE INDEX IF NOT EXISTS idx_units_speaker ON units (speaker);
            """
        )
        self._migrate_unit_columns()

    def _migrate_unit_columns(self) -> None:
        """Add unit columns introduced after a store was created (additive
        only — pydantic supplies defaults on read)."""
        existing = {
            str(r["name"])
            for r in self._db.execute("PRAGMA table_info(units)").fetchall()
        }
        for name, field in TextUnit.model_fields.items():
            if name not in existing:
                col = _column_sql(name, field.annotation).replace(" NOT NULL", "")
                with self._db:
                    self._db.execute(f"ALTER TABLE units ADD COLUMN {col}")

    def close(self) -> None:
        self._db.close()

    # -- meta ------------------------------------------------------------

    def set_meta(self, **values: str) -> None:
        with self._db:
            self._db.executemany(
                "INSERT OR REPLACE INTO meta (key, value) VALUES (?, ?)",
                list(values.items()),
            )

    def meta(self) -> dict[str, str]:
        rows = self._db.execute("SELECT key, value FROM meta").fetchall()
        return {str(r["key"]): str(r["value"]) for r in rows}

    # -- units -----------------------------------------------------------

    def replace_units(self, units: Iterable[TextUnit]) -> int:
        """Full re-extract. Phase 2 is read-only over machine output, so
        replace is safe; hard rule 6 (locked lines) becomes relevant when
        writes exist in Phase 4."""
        rows: list[dict[str, object]] = []
        for u in units:
            row = u.model_dump(mode="json")
            for f in _JSON_FIELDS:
                row[f] = json.dumps(row[f], ensure_ascii=False)
            row["status"] = "pending"
            rows.append(row)
        placeholders_sql = ", ".join(f":{c}" for c in _UNIT_COLS)
        with self._db:
            self._db.execute("DELETE FROM units")
            self._db.executemany(
                f"INSERT INTO units ({', '.join(_UNIT_COLS)}) VALUES ({placeholders_sql})",
                rows,
            )
        return len(rows)

    def units(
        self,
        *,
        file: str | None = None,
        speaker: str | None = None,
        kind: str | None = None,
        status: str | None = None,
        q: str | None = None,
        dupes_only: bool = False,
        limit: int = 100,
        offset: int = 0,
    ) -> UnitPage:
        where: list[str] = []
        params: dict[str, object] = {}
        for col, val in (("file", file), ("speaker", speaker), ("kind", kind), ("status", status)):
            if val is not None:
                where.append(f"u.{col} = :{col}")
                params[col] = val
        if q:
            where.append("(u.source_text LIKE :q OR IFNULL(u.target_text,'') LIKE :q)")
            params["q"] = f"%{q}%"
        if dupes_only:
            where.append("d.n > 1")
        where_sql = ("WHERE " + " AND ".join(where)) if where else ""
        base = (
            "FROM units u JOIN (SELECT source_hash, COUNT(*) AS n FROM units "
            "GROUP BY source_hash) d ON d.source_hash = u.source_hash "
        ) + where_sql

        total_row = self._db.execute(f"SELECT COUNT(*) AS c {base}", params).fetchone()
        total = int(total_row["c"])
        params.update({"limit": limit, "offset": offset})
        rows = self._db.execute(
            f"SELECT u.*, d.n AS dup_count {base} "
            "ORDER BY u.file, u.ordinal LIMIT :limit OFFSET :offset",
            params,
        ).fetchall()
        return UnitPage(total=total, rows=[_to_row(r) for r in rows])

    # -- analysis artifacts ------------------------------------------------

    def replace_scenes(self, rows: list[tuple[str, str, str | None, int | None, str]]) -> None:
        """(file, label, title, order_index, nexts_json) rows."""
        with self._db:
            self._db.execute("DELETE FROM scenes")
            self._db.executemany(
                "INSERT INTO scenes (file, label, title, order_index, nexts) "
                "VALUES (?, ?, ?, ?, ?)",
                rows,
            )

    def file_order(self) -> dict[str, int]:
        """file -> reading-order index from the Stage 3 scene graph. Empty
        until `analyze` has run, or for an engine with no graph yet."""
        rows = self._db.execute(
            "SELECT file, MIN(order_index) AS oi FROM scenes "
            "WHERE order_index IS NOT NULL GROUP BY file"
        ).fetchall()
        return {str(r["file"]): int(r["oi"]) for r in rows}

    def replace_terms(self, rows: list[tuple[str, int, str, str]]) -> None:
        """(term, count, kind, sample) rows."""
        with self._db:
            self._db.execute("DELETE FROM terms")
            self._db.executemany(
                "INSERT INTO terms (term, count, kind, sample) VALUES (?, ?, ?, ?)",
                rows,
            )

    def terms(self, limit: int = 200) -> list[tuple[str, int, str, str]]:
        rows = self._db.execute(
            "SELECT term, count, kind, sample FROM terms ORDER BY count DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return [(str(r["term"]), int(r["count"]), str(r["kind"]), str(r["sample"])) for r in rows]

    def put_observation(
        self, key: str, scene: str, model: str, prompt_hash: str, payload: str
    ) -> None:
        with self._db:
            self._db.execute(
                "INSERT OR REPLACE INTO observations "
                "(key, scene, model, prompt_hash, payload) VALUES (?, ?, ?, ?, ?)",
                (key, scene, model, prompt_hash, payload),
            )

    def observation(self, key: str) -> str | None:
        row = self._db.execute(
            "SELECT payload FROM observations WHERE key = ?", (key,)
        ).fetchone()
        return str(row["payload"]) if row else None

    def observations(self) -> list[tuple[str, str]]:
        rows = self._db.execute(
            "SELECT scene, payload FROM observations ORDER BY key"
        ).fetchall()
        return [(str(r["scene"]), str(r["payload"])) for r in rows]

    def stats(self) -> StoreStats:
        db = self._db
        total = int(db.execute("SELECT COUNT(*) AS c FROM units").fetchone()["c"])
        by_kind = {
            str(r["kind"]): int(r["c"])
            for r in db.execute("SELECT kind, COUNT(*) c FROM units GROUP BY kind")
        }
        speakers = {
            str(r["speaker"]): int(r["c"])
            for r in db.execute(
                "SELECT speaker, COUNT(*) c FROM units WHERE speaker IS NOT NULL "
                "GROUP BY speaker ORDER BY c DESC"
            )
        }
        files = [
            str(r["file"])
            for r in db.execute("SELECT DISTINCT file FROM units ORDER BY file")
        ]
        dup = db.execute(
            "SELECT COUNT(*) AS groups, IFNULL(SUM(n), 0) AS units FROM "
            "(SELECT COUNT(*) AS n FROM units GROUP BY source_hash HAVING n > 1)"
        ).fetchone()
        return StoreStats(
            total_units=total,
            by_kind=by_kind,
            speakers=speakers,
            files=files,
            duplicate_groups=int(dup["groups"]),
            duplicate_units=int(dup["units"]),
        )


def _to_row(r: sqlite3.Row) -> UnitRow:
    data = {k: r[k] for k in r.keys() if k not in ("dup_count", "status")}
    for f in _JSON_FIELDS:
        data[f] = json.loads(str(data[f]))
    return UnitRow(
        unit=TextUnit.model_validate(data),
        status=str(r["status"]),
        dup_count=int(r["dup_count"]),
    )
