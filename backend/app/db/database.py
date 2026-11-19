import os
import re
import sqlite3
from contextlib import contextmanager
from typing import Any, Generator, Optional
from app.config import settings


SQLITE_SCHEMA_SQL = """
-- Better Auth Core Tables
CREATE TABLE IF NOT EXISTS "user" (
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
    userId TEXT NOT NULL REFERENCES "user"(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS account (
    id TEXT PRIMARY KEY,
    accountId TEXT NOT NULL,
    providerId TEXT NOT NULL,
    userId TEXT NOT NULL REFERENCES "user"(id) ON DELETE CASCADE,
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

CREATE INDEX IF NOT EXISTS idx_user_email ON "user"(email);
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
    FOREIGN KEY(user_id) REFERENCES "user"(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_projects_created_at ON projects(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_projects_bookmarked ON projects(is_bookmarked);

-- Bring Your Own Key (BYOK) Hybrid AI Architecture Tables
CREATE TABLE IF NOT EXISTS user_ai_credentials (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    provider TEXT NOT NULL,
    encrypted_api_key TEXT NOT NULL,
    key_hint TEXT NOT NULL,
    base_url TEXT,
    selected_model TEXT,
    status TEXT NOT NULL DEFAULT 'connected',
    last_validated_at TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY(user_id) REFERENCES "user"(id) ON DELETE CASCADE,
    UNIQUE(user_id, provider)
);

CREATE TABLE IF NOT EXISTS user_ai_preferences (
    user_id TEXT PRIMARY KEY,
    preferred_provider TEXT NOT NULL DEFAULT 'deterministic',
    preferred_model TEXT,
    fallback_to_deterministic INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY(user_id) REFERENCES "user"(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_user_ai_credentials_user_id ON user_ai_credentials(user_id);
"""

POSTGRES_SCHEMA_SQL = """
-- Better Auth Core Tables
CREATE TABLE IF NOT EXISTS public."user" (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    email TEXT NOT NULL UNIQUE,
    emailVerified INTEGER NOT NULL DEFAULT 0,
    image TEXT,
    createdAt TEXT NOT NULL,
    updatedAt TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_user_email ON public."user"(email);

CREATE TABLE IF NOT EXISTS public.session (
    id TEXT PRIMARY KEY,
    expiresAt TEXT NOT NULL,
    token TEXT NOT NULL UNIQUE,
    createdAt TEXT NOT NULL,
    updatedAt TEXT NOT NULL,
    ipAddress TEXT,
    userAgent TEXT,
    userId TEXT NOT NULL REFERENCES public."user"(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_session_token ON public.session(token);
CREATE INDEX IF NOT EXISTS idx_session_userId ON public.session(userId);

CREATE TABLE IF NOT EXISTS public.account (
    id TEXT PRIMARY KEY,
    accountId TEXT NOT NULL,
    providerId TEXT NOT NULL,
    userId TEXT NOT NULL REFERENCES public."user"(id) ON DELETE CASCADE,
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

CREATE INDEX IF NOT EXISTS idx_account_userId ON public.account(userId);

CREATE TABLE IF NOT EXISTS public.verification (
    id TEXT PRIMARY KEY,
    identifier TEXT NOT NULL,
    value TEXT NOT NULL,
    expiresAt TEXT NOT NULL,
    createdAt TEXT NOT NULL,
    updatedAt TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_verification_identifier ON public.verification(identifier);

-- Projects Table with Multi-User Ownership
CREATE TABLE IF NOT EXISTS public.projects (
    id TEXT PRIMARY KEY,
    user_id TEXT,
    name TEXT NOT NULL,
    description TEXT,
    latitude DOUBLE PRECISION NOT NULL,
    longitude DOUBLE PRECISION NOT NULL,
    formatted_address TEXT,
    building_typology TEXT,
    floors INTEGER,
    built_up_area_sqft DOUBLE PRECISION,
    composite_score DOUBLE PRECISION,
    total_cost_inr DOUBLE PRECISION,
    is_bookmarked INTEGER DEFAULT 0,
    boundary_json TEXT,
    parameters_json TEXT NOT NULL,
    analysis_summary_json TEXT,
    analysis_result_json TEXT,
    floor_plan_json TEXT,
    site_vision_json TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY(user_id) REFERENCES public."user"(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_projects_created_at ON public.projects(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_projects_bookmarked ON public.projects(is_bookmarked);
CREATE INDEX IF NOT EXISTS idx_projects_user_id ON public.projects(user_id);
CREATE UNIQUE INDEX IF NOT EXISTS idx_projects_user_name_unique ON public.projects(user_id, LOWER(TRIM(name)));

-- Bring Your Own Key (BYOK) Hybrid AI Architecture Tables
CREATE TABLE IF NOT EXISTS public.user_ai_credentials (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    provider TEXT NOT NULL,
    encrypted_api_key TEXT NOT NULL,
    key_hint TEXT NOT NULL,
    base_url TEXT,
    selected_model TEXT,
    status TEXT NOT NULL DEFAULT 'connected' CHECK (status IN ('connected', 'invalid_key', 'rate_limited', 'error')),
    last_validated_at TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY(user_id) REFERENCES public."user"(id) ON DELETE CASCADE,
    UNIQUE(user_id, provider)
);

CREATE INDEX IF NOT EXISTS idx_user_ai_credentials_user_id ON public.user_ai_credentials(user_id);
CREATE INDEX IF NOT EXISTS idx_user_ai_credentials_provider ON public.user_ai_credentials(user_id, provider);

CREATE TABLE IF NOT EXISTS public.user_ai_preferences (
    user_id TEXT PRIMARY KEY,
    preferred_provider TEXT NOT NULL DEFAULT 'deterministic',
    preferred_model TEXT,
    fallback_to_deterministic INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY(user_id) REFERENCES public."user"(id) ON DELETE CASCADE
);
"""

# Backwards compatibility alias
SCHEMA_SQL = SQLITE_SCHEMA_SQL


def is_postgres() -> bool:
    """Check if the backend is configured to use a PostgreSQL database URL."""
    url = (settings.DATABASE_URL or "").strip()
    return url.startswith("postgres://") or url.startswith("postgresql://")


def _translate_query_to_pg(query: str) -> str:
    """Translates '?' parameter placeholders to '%s' outside string literals for PostgreSQL."""
    parts = re.split(r"('[^']*')", query)
    for i in range(0, len(parts), 2):
        parts[i] = parts[i].replace("?", "%s")
    return "".join(parts)


class PgRow(dict):
    """Row wrapper supporting both dict-key access ('emailVerified') and tuple-index access (0)."""

    def __init__(self, mapping: dict, tuple_vals: tuple):
        super().__init__(mapping)
        self._tuple = tuple_vals

    def __getitem__(self, key: Any) -> Any:
        if isinstance(key, int):
            return self._tuple[key]
        return super().__getitem__(key)

    def keys(self):
        return super().keys()


class PgCursorWrapper:
    """Wraps a psycopg Cursor to accept '?' placeholders and return PgRow instances."""

    def __init__(self, raw_cursor):
        self._raw = raw_cursor

    def execute(self, sql: str, params=None):
        translated = _translate_query_to_pg(sql)
        if params is None:
            self._raw.execute(translated)
        else:
            self._raw.execute(translated, params)
        return self

    def executemany(self, sql: str, seq_of_params):
        translated = _translate_query_to_pg(sql)
        self._raw.executemany(translated, seq_of_params)
        return self

    def _wrap_row(self, row):
        if row is None:
            return None
        if isinstance(row, dict):
            return PgRow(row, tuple(row.values()))
        return row

    def fetchone(self):
        return self._wrap_row(self._raw.fetchone())

    def fetchall(self):
        rows = self._raw.fetchall()
        return [self._wrap_row(r) for r in rows]

    def fetchmany(self, size=None):
        rows = self._raw.fetchmany(size) if size else self._raw.fetchmany()
        return [self._wrap_row(r) for r in rows]

    @property
    def rowcount(self):
        return self._raw.rowcount

    def close(self):
        self._raw.close()

    def __iter__(self):
        for row in self._raw:
            yield self._wrap_row(row)


class PgConnectionWrapper:
    """Wraps a psycopg Connection to provide sqlite3-compatible execute and cursor behavior."""

    def __init__(self, raw_conn):
        self._raw = raw_conn

    def cursor(self):
        return PgCursorWrapper(self._raw.cursor())

    def execute(self, sql: str, params=None):
        cur = self.cursor()
        cur.execute(sql, params)
        return cur

    def executescript(self, script: str):
        cur = self._raw.cursor()
        try:
            cur.execute(script)
        finally:
            cur.close()

    def commit(self):
        self._raw.commit()

    def rollback(self):
        self._raw.rollback()

    def close(self):
        self._raw.close()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if exc_type is not None:
            self.rollback()
        else:
            self.commit()


@contextmanager
def get_connection(db_path: Optional[str] = None) -> Generator[Any, None, None]:
    """Yield a configured database connection (SQLite by default, or PostgreSQL if DATABASE_URL is set)."""
    # If an explicit db_path is passed (such as during isolated test runs), use SQLite
    if db_path or not is_postgres():
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
    else:
        # PostgreSQL / Supabase mode
        try:
            import psycopg
            from psycopg.rows import dict_row
        except ImportError as e:
            raise RuntimeError(
                "psycopg is required when DATABASE_URL is set. "
                "Install it with: pip install psycopg[binary]"
            ) from e

        db_url = settings.DATABASE_URL.strip()
        conninfo = psycopg.conninfo.conninfo_to_dict(db_url)
        host = conninfo.get("host", "")
        # Enforce SSL for remote PostgreSQL hosts (e.g., Supabase) if not explicitly set
        if "sslmode" not in conninfo and host not in ("localhost", "127.0.0.1", ""):
            conninfo["sslmode"] = "require"

        raw_conn = psycopg.connect(**conninfo, row_factory=dict_row, autocommit=False)
        wrapper = PgConnectionWrapper(raw_conn)
        try:
            yield wrapper
        finally:
            wrapper.close()


def get_db() -> Generator[Any, None, None]:
    """FastAPI dependency yielding a configured database connection."""
    with get_connection() as conn:
        yield conn


def init_db(db_path: Optional[str] = None) -> None:
    """Initialize database tables idempotently for SQLite or Supabase PostgreSQL."""
    if db_path or not is_postgres():
        with get_connection(db_path) as conn:
            conn.executescript(SQLITE_SCHEMA_SQL)
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

            # Idempotent grandfathering migration: existing accounts created prior to mandatory
            # registration verification are grandfathered with emailVerified = 1 so they never lose access
            cursor.execute("PRAGMA user_version;")
            ver_row = cursor.fetchone()
            user_version = ver_row[0] if ver_row else 0
            if user_version < 2:
                cursor.execute("UPDATE \"user\" SET emailVerified = 1 WHERE emailVerified = 0;")
                cursor.execute("PRAGMA user_version = 2;")

            conn.commit()
    else:
        # PostgreSQL / Supabase initialization
        with get_connection() as conn:
            conn.executescript(POSTGRES_SCHEMA_SQL)
            conn.commit()
