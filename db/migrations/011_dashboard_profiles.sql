-- Store a small user profile photo as a validated data URL.
ALTER TABLE public.dashboard_users
    ADD COLUMN IF NOT EXISTS profile_photo_data TEXT;
