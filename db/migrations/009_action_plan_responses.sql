-- Responses from assigned SPO/MIO staff back to the action-plan owner.
CREATE TABLE IF NOT EXISTS public.dashboard_action_plan_responses (
    id BIGSERIAL PRIMARY KEY,
    action_plan_id BIGINT NOT NULL REFERENCES public.dashboard_action_plans(id) ON DELETE CASCADE,
    sender_user_id BIGINT NOT NULL REFERENCES public.dashboard_users(id) ON DELETE CASCADE,
    response_text TEXT NOT NULL CHECK (length(trim(response_text)) > 0),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_dashboard_action_plan_responses_plan
    ON public.dashboard_action_plan_responses (action_plan_id, created_at DESC, id DESC);

DO $$
BEGIN
    IF to_regprocedure('public.bump_dashboard_cache_generation()') IS NOT NULL THEN
        DROP TRIGGER IF EXISTS dashboard_cache_invalidate_action_plan_responses
            ON public.dashboard_action_plan_responses;
        CREATE TRIGGER dashboard_cache_invalidate_action_plan_responses
        AFTER INSERT OR UPDATE OR DELETE OR TRUNCATE
        ON public.dashboard_action_plan_responses
        FOR EACH STATEMENT EXECUTE FUNCTION public.bump_dashboard_cache_generation();
    END IF;
END;
$$;
