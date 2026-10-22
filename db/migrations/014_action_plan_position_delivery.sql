-- Queue action-plan messages by staff position, including positions without an account.
CREATE TABLE IF NOT EXISTS public.dashboard_action_plan_positions (
    action_plan_id BIGINT NOT NULL REFERENCES public.dashboard_action_plans(id) ON DELETE CASCADE,
    position_code TEXT NOT NULL,
    PRIMARY KEY (action_plan_id, position_code)
);

CREATE INDEX IF NOT EXISTS idx_dashboard_action_plan_positions_code
    ON public.dashboard_action_plan_positions (position_code, action_plan_id);

-- Include actions saved before position-based delivery was introduced.
INSERT INTO public.dashboard_action_plan_positions (action_plan_id, position_code)
SELECT id, TRIM(action_owner_position_code)
  FROM public.dashboard_action_plans
 WHERE NULLIF(TRIM(action_owner_position_code), '') IS NOT NULL
ON CONFLICT DO NOTHING;

-- A newly created or reassigned account receives all messages for its position.
CREATE OR REPLACE FUNCTION public.deliver_dashboard_action_plan_positions()
RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF NEW.is_active AND NEW.role <> 'admin'
       AND NULLIF(TRIM(NEW.scope_position_code), '') IS NOT NULL THEN
        INSERT INTO public.dashboard_action_plan_recipients (action_plan_id, recipient_user_id)
        SELECT p.action_plan_id, NEW.id
          FROM public.dashboard_action_plan_positions p
         WHERE p.position_code = TRIM(NEW.scope_position_code)
        ON CONFLICT (action_plan_id, recipient_user_id) DO NOTHING;
    END IF;
    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS dashboard_user_deliver_action_plans ON public.dashboard_users;
CREATE TRIGGER dashboard_user_deliver_action_plans
AFTER INSERT OR UPDATE OF scope_position_code, is_active, role ON public.dashboard_users
FOR EACH ROW EXECUTE FUNCTION public.deliver_dashboard_action_plan_positions();

INSERT INTO public.dashboard_action_plan_recipients (action_plan_id, recipient_user_id)
SELECT p.action_plan_id, u.id
  FROM public.dashboard_action_plan_positions p
  JOIN public.dashboard_users u ON TRIM(u.scope_position_code) = p.position_code
 WHERE u.is_active AND u.role <> 'admin'
ON CONFLICT (action_plan_id, recipient_user_id) DO NOTHING;
