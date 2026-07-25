"""Run artifacts: a per-run directory plus a SQLite index.

Layout follows mirofish-cli's convention, which is the best pattern going for this shape
of tool — one self-contained directory per run, machine-readable and human-browsable:

    runs/<run_id>/
      manifest.json          what was run, against what, with which population
      input/                 provenance copies: episodes, beats, config
      reactions.jsonl        one line per persona-episode, written as they land
      report/                verdict.json, report.md, report.html
      logs/run.log

Reactions are appended to JSONL *during* the run so a crash at episode 17 of 20 leaves
17 episodes of usable data rather than nothing. SQLite is the query surface.
"""

from __future__ import annotations

import json
import sqlite3
from contextlib import closing
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Iterator

RUNS_DIR = Path("runs")
DB_PATH = RUNS_DIR / "pocketsim.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
    run_id                  TEXT PRIMARY KEY,
    series                  TEXT NOT NULL,
    market                  TEXT NOT NULL,
    population_path         TEXT NOT NULL,
    population_fingerprint  TEXT NOT NULL,
    population_size         INTEGER NOT NULL,
    provider                TEXT NOT NULL,
    model                   TEXT NOT NULL,
    episodes_planned        INTEGER NOT NULL,
    episodes_simulated      INTEGER NOT NULL DEFAULT 0,
    status                  TEXT NOT NULL DEFAULT 'running',
    created_at              TEXT NOT NULL,
    finished_at             TEXT,
    usage_json              TEXT
);

CREATE TABLE IF NOT EXISTS reactions (
    run_id          TEXT NOT NULL,
    persona_id      TEXT NOT NULL,
    cohort_id       TEXT NOT NULL,
    region_id       TEXT NOT NULL DEFAULT '',
    episode_no      INTEGER NOT NULL,
    will_continue   INTEGER NOT NULL,
    would_pay       INTEGER NOT NULL,
    drop_beat       TEXT,
    switch_to       TEXT,
    craving_mid     INTEGER NOT NULL,
    craving_end     INTEGER NOT NULL,
    next_prediction TEXT,
    emotional_state TEXT,
    continue_reason TEXT,
    pay_reason      TEXT,
    memory_update   TEXT,
    tenure_months   INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (run_id, persona_id, episode_no)
);

CREATE INDEX IF NOT EXISTS idx_reactions_run_ep ON reactions(run_id, episode_no);
CREATE INDEX IF NOT EXISTS idx_reactions_cohort ON reactions(run_id, cohort_id);
CREATE INDEX IF NOT EXISTS idx_reactions_region ON reactions(run_id, region_id);
"""

# Columns added after the first runs were already on disk. `CREATE TABLE IF NOT EXISTS`
# silently does nothing to an existing table, so without this an older database keeps
# working right up until the insert fails on an unknown column.
MIGRATIONS: dict[str, str] = {
    "region_id": "ALTER TABLE reactions ADD COLUMN region_id TEXT NOT NULL DEFAULT ''",
}


def _migrate(conn: sqlite3.Connection) -> None:
    existing = {row["name"] for row in conn.execute("PRAGMA table_info(reactions)")}
    for column, ddl in MIGRATIONS.items():
        if column not in existing:
            conn.execute(ddl)
    conn.commit()


@dataclass
class RunMeta:
    run_id: str
    series: str
    market: str
    population_path: str
    population_fingerprint: str
    population_size: int
    provider: str
    model: str
    episodes_planned: int
    episodes_simulated: int = 0
    status: str = "running"
    created_at: str = ""
    finished_at: str | None = None
    usage_json: str | None = None


def run_dir(run_id: str) -> Path:
    return RUNS_DIR / run_id


def connect() -> sqlite3.Connection:
    RUNS_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    _migrate(conn)
    return conn


class RunStore:
    """Write side of a single run. Use as a context manager."""

    def __init__(self, meta: RunMeta) -> None:
        self.meta = meta
        self.dir = run_dir(meta.run_id)
        self._jsonl: Any = None

    def __enter__(self) -> RunStore:
        for sub in ("input", "report", "logs"):
            (self.dir / sub).mkdir(parents=True, exist_ok=True)
        self.meta.created_at = self.meta.created_at or datetime.now(UTC).isoformat()
        self._jsonl = (self.dir / "reactions.jsonl").open("a", encoding="utf-8")
        with closing(connect()) as conn:
            conn.execute(
                "INSERT OR REPLACE INTO runs "
                "(run_id, series, market, population_path, population_fingerprint, population_size,"
                " provider, model, episodes_planned, episodes_simulated, status, created_at) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    self.meta.run_id,
                    self.meta.series,
                    self.meta.market,
                    self.meta.population_path,
                    self.meta.population_fingerprint,
                    self.meta.population_size,
                    self.meta.provider,
                    self.meta.model,
                    self.meta.episodes_planned,
                    0,
                    "running",
                    self.meta.created_at,
                ),
            )
            conn.commit()
        self.write_manifest()
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        if self._jsonl:
            self._jsonl.close()
        if exc_type is not None:
            self.finish(status="failed")

    def write_manifest(self) -> None:
        (self.dir / "manifest.json").write_text(
            json.dumps(asdict(self.meta), indent=2), encoding="utf-8"
        )

    def save_input(self, name: str, payload: Any) -> None:
        text = payload if isinstance(payload, str) else json.dumps(payload, indent=2, default=str)
        (self.dir / "input" / name).write_text(text, encoding="utf-8")

    def log(self, line: str) -> None:
        with (self.dir / "logs" / "run.log").open("a", encoding="utf-8") as f:
            f.write(f"{datetime.now(UTC).isoformat()} {line}\n")

    def record(self, rows: list[dict[str, Any]]) -> None:
        if not rows:
            return
        for r in rows:
            self._jsonl.write(json.dumps(r, ensure_ascii=False) + "\n")
        self._jsonl.flush()

        cols = (
            "run_id persona_id cohort_id region_id episode_no will_continue would_pay drop_beat "
            "switch_to craving_mid craving_end next_prediction emotional_state continue_reason "
            "pay_reason memory_update tenure_months"
        ).split()
        with closing(connect()) as conn:
            conn.executemany(
                f"INSERT OR REPLACE INTO reactions ({','.join(cols)}) "
                f"VALUES ({','.join('?' * len(cols))})",
                [tuple(r.get(c) for c in cols) for r in rows],
            )
            conn.commit()

    def finish(self, status: str = "completed", usage: dict | None = None, episodes: int = 0) -> None:
        self.meta.status = status
        self.meta.finished_at = datetime.now(UTC).isoformat()
        self.meta.episodes_simulated = episodes or self.meta.episodes_simulated
        self.meta.usage_json = json.dumps(usage) if usage else self.meta.usage_json
        with closing(connect()) as conn:
            conn.execute(
                "UPDATE runs SET status=?, finished_at=?, episodes_simulated=?, usage_json=? "
                "WHERE run_id=?",
                (
                    self.meta.status,
                    self.meta.finished_at,
                    self.meta.episodes_simulated,
                    self.meta.usage_json,
                    self.meta.run_id,
                ),
            )
            conn.commit()
        self.write_manifest()


# ─────────────────────────────────────────────────────────────────────────────
# Read side
# ─────────────────────────────────────────────────────────────────────────────


def get_run(run_id: str) -> dict[str, Any]:
    with closing(connect()) as conn:
        row = conn.execute("SELECT * FROM runs WHERE run_id=?", (run_id,)).fetchone()
    if row is None:
        known = [r["run_id"] for r in list_runs()]
        raise KeyError(f"no run '{run_id}'. Known runs: {known or '(none)'}")
    return dict(row)


def list_runs(limit: int = 50) -> list[dict[str, Any]]:
    with closing(connect()) as conn:
        rows = conn.execute(
            "SELECT * FROM runs ORDER BY created_at DESC LIMIT ?", (limit,)
        ).fetchall()
    return [dict(r) for r in rows]


def iter_reactions(run_id: str) -> Iterator[dict[str, Any]]:
    with closing(connect()) as conn:
        for row in conn.execute(
            "SELECT * FROM reactions WHERE run_id=? ORDER BY episode_no, persona_id", (run_id,)
        ):
            yield dict(row)


def load_reactions(run_id: str) -> list[dict[str, Any]]:
    rows = list(iter_reactions(run_id))
    if not rows:
        raise ValueError(f"run '{run_id}' has no reactions recorded")
    return rows


def delete_run(run_id: str) -> None:
    with closing(connect()) as conn:
        conn.execute("DELETE FROM reactions WHERE run_id=?", (run_id,))
        conn.execute("DELETE FROM runs WHERE run_id=?", (run_id,))
        conn.commit()
