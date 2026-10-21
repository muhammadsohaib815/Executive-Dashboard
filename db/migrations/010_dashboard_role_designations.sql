-- Allow dashboard accounts to use the staff hierarchy designation as their
-- role label.  Scope_position_code remains the authoritative data boundary.
ALTER TABLE public.dashboard_users
    DROP CONSTRAINT IF EXISTS dashboard_users_role_check;

ALTER TABLE public.dashboard_users
    ADD CONSTRAINT dashboard_users_role_check CHECK (
        role IN (
            'admin', 'executive', 'manager', 'viewer',
            'HOD', 'DGM', 'RSM', 'ASM', 'SPO', 'MIO', 'IO',
            'PS', 'SB', 'ASMTE', 'CM', 'SPOWS', 'TE', 'EXEC'
        )
    );
