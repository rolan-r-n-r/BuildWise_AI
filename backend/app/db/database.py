import os
import sqlite3
from contextlib import contextmanager
from typing import Generator, Optional
from app.config import settings


SCHEMA_SQL = """
-- Better Auth Core Tables
CREATE TABLE IF NOT EXISTS user (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    email TEXT NOT NULL UNIQUE,
    emailVerified INTEGER NOT NULL DEFAULT 0,
    image TEXT,
    createdAt TEXT NOT NULL,
    updatedAt TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS session (
    id TEXT PRIMARY KEY,
    expiresAt TEXT NOT NULL,
    token TEXT NOT NULL UNIQUE,
    createdAt TEXT NOT NULL,
    updatedAt TEXT NOT NULL,
    ipAddress TEXT,
    userAgent TEXT,
    userId TEXT NOT NULL REFERENCES user(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS account (
    id TEXT PRIMARY KEY,
    accountId TEXT NOT NULL,
    providerId TEXT NOT NULL,
    userId TEXT NOT NULL REFERENCES user(id) ON DELETE CASCADE,
    accessToken TEXT,
    refreshToken TEXT,
    idToken TEXT,
    accessTokenExpiresAt TEXT,
    refreshTokenExpiresAt TEXT,
    scope TEXT,
    password TEXT,
    createdAt TEXT NOT NULL,
    updatedAt TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS verification (
    id TEXT PRIMARY KEY,
    identifier TEXT NOT NULL,
    value TEXT NOT NULL,
    expiresAt TEXT NOT NULL,
    createdAt TEXT NOT NULL,
    updatedAt TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_user_email ON user(email);
CREATE INDEX IF NOT EXISTS idx_session_token ON session(token);
CREATE INDEX IF NOT EXISTS idx_session_userId ON session(userId);
CREATE INDEX IF NOT EXISTS idx_account_userId ON account(userId);
CREATE INDEX IF NOT EXISTS idx_verification_identifier ON verification(identifier);

-- Projects Table with Multi-User Ownership
CREATE TABLE IF NOT EXISTS projects (
    id TEXT PRIMARY KEY,
    user_id TEXT,
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
    updated_at TEXT NOT NULL,
    FOREIGN KEY(user_id) REFERENCES user(id) ON DELETE CASCADE
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


def get_db() -> Generator[sqlite3.Connection, None, None]:
    """FastAPI dependency yielding a configured SQLite connection."""
    with get_connection() as conn:
        yield conn


def init_db(db_path: Optional[str] = None) -> None:
    """Initialize database tables, run safe idempotent migrations for multi-user ownership and Better Auth."""
    with get_connection(db_path) as conn:
        conn.executescript(SCHEMA_SQL)
        cursor = conn.cursor()

        # Check if user_id column exists on projects table
        cursor.execute("PRAGMA table_info(projects)")
        columns = [row["name"] for row in cursor.fetchall()]
        if "user_id" not in columns:
            cursor.execute("ALTER TABLE projects ADD COLUMN user_id TEXT;")
            # Assign any pre-existing unowned records to legacy_unassigned so they are isolated from new users
            cursor.execute("UPDATE projects SET user_id = 'legacy_unassigned' WHERE user_id IS NULL;")
            conn.commit()

        # Ensure index on user_id exists
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_projects_user_id ON projects(user_id);")

        # Drop old global name uniqueness index if present, transitioning to per-user name uniqueness
        cursor.execute("DROP INDEX IF EXISTS idx_projects_name_unique;")
        cursor.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_projects_user_name_unique ON projects(user_id, LOWER(TRIM(name)));"
        )
        conn.commit()
