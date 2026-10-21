-- User hierarchy assignments, action plans, and in-app notifications.
ALTER TABLE public.dashboard_users
    ADD COLUMN IF NOT EXISTS scope_position_code TEXT;

CREATE INDEX IF NOT EXISTS idx_dashboard_users_scope_position
    ON public.dashboard_users (scope_position_code)
    WHERE is_active = TRUE AND scope_position_code IS NOT NULL;

CREATE TABLE IF NOT EXISTS public.dashboard_action_plans (
    id BIGSERIAL PRIMARY KEY,
    created_by_user_id BIGINT NOT NULL REFERENCES public.dashboard_users(id),
    action_text TEXT NOT NULL CHECK (length(trim(action_text)) > 0),
    action_owner TEXT NOT NULL DEFAULT '',
    due_date DATE,
    priority TEXT NOT NULL DEFAULT 'Medium' CHECK (priority IN ('High', 'Medium', 'Low')),
    status TEXT NOT NULL DEFAULT 'Open' CHECK (status IN ('Open', 'In Progress', 'Complete')),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS public.dashboard_action_plan_recipients (
    action_plan_id BIGINT NOT NULL REFERENCES public.dashboard_action_plans(id) ON DELETE CASCADE,
    recipient_user_id BIGINT NOT NULL REFERENCES public.dashboard_users(id),
    PRIMARY KEY (action_plan_id, recipient_user_id)
);

CREATE TABLE IF NOT EXISTS public.dashboard_notifications (
    id BIGSERIAL PRIMARY KEY,
    recipient_user_id BIGINT NOT NULL REFERENCES public.dashboard_users(id) ON DELETE CASCADE,
    action_plan_id BIGINT NOT NULL REFERENCES public.dashboard_action_plans(id) ON DELETE CASCADE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    read_at TIMESTAMPTZ,
    UNIQUE (recipient_user_id, action_plan_id)
);

CREATE INDEX IF NOT EXISTS idx_dashboard_notifications_inbox
    ON public.dashboard_notifications (recipient_user_id, created_at DESC, id DESC);

CREATE OR REPLACE FUNCTION public.notify_dashboard_action_plan_recipients()
RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    INSERT INTO public.dashboard_notifications (recipient_user_id, action_plan_id)
    VALUES (NEW.recipient_user_id, NEW.action_plan_id)
    ON CONFLICT (recipient_user_id, action_plan_id) DO NOTHING;
    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS dashboard_action_plan_notify_recipient
    ON public.dashboard_action_plan_recipients;
CREATE TRIGGER dashboard_action_plan_notify_recipient
AFTER INSERT ON public.dashboard_action_plan_recipients
FOR EACH ROW EXECUTE FUNCTION public.notify_dashboard_action_plan_recipients();

-- Make imports and administrator edits invalidate cached dashboard responses.
DO $$
DECLARE source_table text; trigger_name text;
BEGIN
    FOREACH source_table IN ARRAY ARRAY[
        'dashboard_users', 'dashboard_action_plans',
        'dashboard_action_plan_recipients', 'dashboard_notifications'
    ] LOOP
        IF to_regclass('public.' || source_table) IS NOT NULL THEN
            trigger_name := 'dashboard_cache_invalidate_' || source_table;
            EXECUTE format('DROP TRIGGER IF EXISTS %I ON public.%I', trigger_name, source_table);
            EXECUTE format(
                'CREATE TRIGGER %I AFTER INSERT OR UPDATE OR DELETE OR TRUNCATE ON public.%I '
                'FOR EACH STATEMENT EXECUTE FUNCTION public.bump_dashboard_cache_generation()',
                trigger_name, source_table
            );
        END IF;
    END LOOP;
END;
$$;
