-- =============================================================================
-- BuildWise AI — Supabase (PostgreSQL) Production Migration
-- Hybrid AI Architecture with BYOK (Bring Your Own API Key)
-- =============================================================================

-- 1. User AI Credentials Table (Encrypted API Keys at Rest)
CREATE TABLE IF NOT EXISTS public.user_ai_credentials (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id TEXT NOT NULL REFERENCES public."user"(id) ON DELETE CASCADE,
    provider TEXT NOT NULL,
    encrypted_api_key TEXT NOT NULL,
    key_hint TEXT NOT NULL,
    base_url TEXT,
    selected_model TEXT,
    status TEXT NOT NULL DEFAULT 'connected' CHECK (status IN ('connected', 'invalid_key', 'rate_limited', 'error')),
    last_validated_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT timezone('utc'::text, now()),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT timezone('utc'::text, now()),
    CONSTRAINT uq_user_ai_credentials_user_provider UNIQUE (user_id, provider)
);

-- Index for high-performance lookup by user_id
CREATE INDEX IF NOT EXISTS idx_user_ai_credentials_user_id ON public.user_ai_credentials(user_id);
CREATE INDEX IF NOT EXISTS idx_user_ai_credentials_provider ON public.user_ai_credentials(user_id, provider);

-- 2. User AI Preferences Table (Deterministic vs AI Strategy)
CREATE TABLE IF NOT EXISTS public.user_ai_preferences (
    user_id TEXT PRIMARY KEY REFERENCES public."user"(id) ON DELETE CASCADE,
    preferred_provider TEXT NOT NULL DEFAULT 'deterministic',
    preferred_model TEXT,
    fallback_to_deterministic BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT timezone('utc'::text, now()),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT timezone('utc'::text, now())
);

-- 3. Row Level Security (RLS) Policies
-- Strict Multi-Tenant Isolation: Users can NEVER read, create, update, or delete
-- another user's encrypted credentials or AI preferences.

ALTER TABLE public.user_ai_credentials ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.user_ai_preferences ENABLE ROW LEVEL SECURITY;

-- Credential policies (tied to Supabase auth.uid() or current session user_id)
CREATE POLICY "Users can only read their own AI credentials"
    ON public.user_ai_credentials
    FOR SELECT
    USING (auth.uid()::text = user_id);

CREATE POLICY "Users can only insert their own AI credentials"
    ON public.user_ai_credentials
    FOR INSERT
    WITH CHECK (auth.uid()::text = user_id);

CREATE POLICY "Users can only update their own AI credentials"
    ON public.user_ai_credentials
    FOR UPDATE
    USING (auth.uid()::text = user_id)
    WITH CHECK (auth.uid()::text = user_id);

CREATE POLICY "Users can only delete their own AI credentials"
    ON public.user_ai_credentials
    FOR DELETE
    USING (auth.uid()::text = user_id);

-- Preference policies
CREATE POLICY "Users can only view their own AI preferences"
    ON public.user_ai_preferences
    FOR SELECT
    USING (auth.uid()::text = user_id);

CREATE POLICY "Users can only upsert their own AI preferences"
    ON public.user_ai_preferences
    FOR ALL
    USING (auth.uid()::text = user_id)
    WITH CHECK (auth.uid()::text = user_id);

-- Updated_at trigger function
CREATE OR REPLACE FUNCTION public.handle_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = timezone('utc'::text, now());
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS tr_user_ai_credentials_updated_at ON public.user_ai_credentials;
CREATE TRIGGER tr_user_ai_credentials_updated_at
    BEFORE UPDATE ON public.user_ai_credentials
    FOR EACH ROW
    EXECUTE FUNCTION public.handle_updated_at();

DROP TRIGGER IF EXISTS tr_user_ai_preferences_updated_at ON public.user_ai_preferences;
CREATE TRIGGER tr_user_ai_preferences_updated_at
    BEFORE UPDATE ON public.user_ai_preferences
    FOR EACH ROW
    EXECUTE FUNCTION public.handle_updated_at();
