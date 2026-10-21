-- Keep every scoped dashboard account's role aligned with its staff position.
-- The position designation is the source of truth for hierarchy accounts.
UPDATE public.dashboard_users AS u
   SET role = UPPER(TRIM(s.designation_name)),
       updated_at = NOW()
  FROM public.staff_master AS s
 WHERE u.role <> 'admin'
   AND u.scope_position_code IS NOT NULL
   AND TRIM(s.position_code) = TRIM(u.scope_position_code)
   AND UPPER(TRIM(s.designation_name)) IN (
       'HOD', 'DGM', 'RSM', 'ASM', 'SPO', 'MIO', 'IO',
       'PS', 'SB', 'ASMTE', 'CM', 'SPOWS', 'TE', 'EXEC'
   );
