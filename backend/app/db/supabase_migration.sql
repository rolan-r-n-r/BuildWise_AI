-- =============================================================================
-- BuildWise AI — Production Supabase (PostgreSQL) Initial Schema & Migration
-- Complete Schema: Better Auth, Projects, BYOK AI Credentials & Preferences
-- Run this script in your Supabase Dashboard: SQL Editor -> New Query -> Run
-- =============================================================================

-- Enable required extensions
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS "pgcrypto";

-- -----------------------------------------------------------------------------
-- 1. Better Auth Core Tables
-- -----------------------------------------------------------------------------

-- Core User Table (quoted "user" because user is a PostgreSQL reserved keyword)
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

-- Active User Sessions Table
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

-- User Authentication Accounts Table (Credential / OAuth)
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

-- Verification Tokens Table (Email Verification & Password Reset OTPs)
CREATE TABLE IF NOT EXISTS public.verification (
    id TEXT PRIMARY KEY,
    identifier TEXT NOT NULL,
    value TEXT NOT NULL,
    expiresAt TEXT NOT NULL,
    createdAt TEXT NOT NULL,
    updatedAt TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_verification_identifier ON public.verification(identifier);

-- -----------------------------------------------------------------------------
-- 2. Projects Table with Multi-User Ownership & Isolation
-- -----------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS public.projects (
    id TEXT PRIMARY KEY,
    user_id TEXT REFERENCES public."user"(id) ON DELETE CASCADE,
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
    updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_projects_created_at ON public.projects(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_projects_bookmarked ON public.projects(is_bookmarked);
CREATE INDEX IF NOT EXISTS idx_projects_user_id ON public.projects(user_id);
CREATE UNIQUE INDEX IF NOT EXISTS idx_projects_user_name_unique ON public.projects(user_id, LOWER(TRIM(name)));

-- -----------------------------------------------------------------------------
-- 3. Bring Your Own Key (BYOK) Hybrid AI Architecture Tables
-- -----------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS public.user_ai_credentials (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL REFERENCES public."user"(id) ON DELETE CASCADE,
    provider TEXT NOT NULL,
    encrypted_api_key TEXT NOT NULL,
    key_hint TEXT NOT NULL,
    base_url TEXT,
    selected_model TEXT,
    status TEXT NOT NULL DEFAULT 'connected' CHECK (status IN ('connected', 'invalid_key', 'rate_limited', 'error')),
    last_validated_at TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    CONSTRAINT uq_user_ai_credentials_user_provider UNIQUE (user_id, provider)
);

CREATE INDEX IF NOT EXISTS idx_user_ai_credentials_user_id ON public.user_ai_credentials(user_id);
CREATE INDEX IF NOT EXISTS idx_user_ai_credentials_provider ON public.user_ai_credentials(user_id, provider);

CREATE TABLE IF NOT EXISTS public.user_ai_preferences (
    user_id TEXT PRIMARY KEY REFERENCES public."user"(id) ON DELETE CASCADE,
    preferred_provider TEXT NOT NULL DEFAULT 'deterministic',
    preferred_model TEXT,
    fallback_to_deterministic INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

-- -----------------------------------------------------------------------------
-- 4. Automatic Timestamp Trigger Function (Optional Utility)
-- -----------------------------------------------------------------------------

CREATE OR REPLACE FUNCTION public.handle_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = timezone('utc'::text, now())::text;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;
