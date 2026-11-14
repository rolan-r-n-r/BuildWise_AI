import os
import sqlite3
from contextlib import contextmanager
from typing import Generator, Optional
from app.config import settings


SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS projects (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    description TEXT,
    latitude REAL NOT NULL,
    longitude REAL NOT NULL,
    formatted_address TEXT,
    building_typology TEXT,
    floors INTEGER,
    built_up_area_sqft REAL,
    composite_score REAL,
    total_cost_inr REAL,
    is_bookmarked INTEGER DEFAULT 0,
    boundary_json TEXT,
    parameters_json TEXT NOT NULL,
    analysis_summary_json TEXT,
    analysis_result_json TEXT,
    floor_plan_json TEXT,
    site_vision_json TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_projects_created_at ON projects(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_projects_bookmarked ON projects(is_bookmarked);
"""


@contextmanager
def get_connection(db_path: Optional[str] = None) -> Generator[sqlite3.Connection, None, None]:
    """Yield a configured SQLite connection with WAL mode and foreign keys enabled."""
    target_path = db_path or settings.DATABASE_PATH
    os.makedirs(os.path.dirname(os.path.abspath(target_path)), exist_ok=True)
    conn = sqlite3.connect(target_path, timeout=10.0, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("PRAGMA journal_mode = WAL;")
        conn.execute("PRAGMA foreign_keys = ON;")
        conn.execute("PRAGMA busy_timeout = 5000;")
        yield conn
    finally:
        conn.close()


def init_db(db_path: Optional[str] = None) -> None:
    """Initialize database tables, disambiguate historical duplicate names, and enforce uniqueness idempotently."""
    with get_connection(db_path) as conn:
        conn.executescript(SCHEMA_SQL)

        # Migration: Disambiguate legacy duplicates from pre-uniqueness versions without data loss
        cursor = conn.cursor()
        duplicates = cursor.execute("""
            SELECT LOWER(TRIM(name)) as norm_name, COUNT(*) as cnt
            FROM projects
            GROUP BY LOWER(TRIM(name))
            HAVING cnt > 1
        """).fetchall()

        for dup in duplicates:
            norm_name = dup[0]
            rows = cursor.execute("""
                SELECT id, name FROM projects
                WHERE LOWER(TRIM(name)) = ?
                ORDER BY updated_at ASC, created_at ASC
            """, (norm_name,)).fetchall()

            # Keep the newest record with original name; archive older duplicates safely
            for i, r in enumerate(rows[:-1], 1):
                new_name = f"{r['name']} (Archive {i})"
                cursor.execute("UPDATE projects SET name = ? WHERE id = ?", (new_name, r["id"]))

        conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_projects_name_unique ON projects(LOWER(TRIM(name)));")
        conn.commit()
