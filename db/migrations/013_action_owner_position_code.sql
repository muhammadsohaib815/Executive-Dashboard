-- Retain the staff identity used for an action owner, even without a dashboard login.
ALTER TABLE public.dashboard_action_plans
    ADD COLUMN IF NOT EXISTS action_owner_position_code TEXT;

CREATE INDEX IF NOT EXISTS idx_dashboard_action_plans_owner_position
    ON public.dashboard_action_plans (action_owner_position_code)
    WHERE action_owner_position_code IS NOT NULL;
