-- FIX_EMPLOYEE_ID_IT04_LIVE.sql — live 1-klik Employee ID polos 1526.08.26 (tanpa prefix ITSP.)
-- Jalankan BLOK 1 di koneksi DB web_karir, lalu BLOK 2 di koneksi DB web_perusahaan (jangan cross-DB).
-- Idempotent — aman di-rerun. Penting: jika Auto-commit OFF (DBeaver), COMMIT setelah STEP A sebelum STEP B.

-- ===================== BLOK 1: web_karir (recruitment_admins) — jalankan di DB web_karir =====================
-- Diagnosis (opsional): cek DB aktif & kolom
-- SELECT current_database(); -- harus web_karir
-- SELECT column_name FROM information_schema.columns WHERE table_schema='public' AND table_name='recruitment_admins' ORDER BY 1;

-- STEP 1A — DDL (commit dulu bila Auto-commit OFF)
ALTER TABLE public.recruitment_admins
  ADD COLUMN IF NOT EXISTS employee_id VARCHAR(50) UNIQUE NULL,
  ADD COLUMN IF NOT EXISTS is_first_login BOOLEAN DEFAULT TRUE NOT NULL;
CREATE INDEX IF NOT EXISTS ix_recruitment_admins_employee_id ON public.recruitment_admins(employee_id);
CREATE INDEX IF NOT EXISTS ix_recruitment_admins_is_first_login ON public.recruitment_admins(is_first_login);
COMMENT ON COLUMN public.recruitment_admins.employee_id IS 'Immutable FK data_karyawan.employee_id 1526.08.26 polos tanpa prefix ITSP.';
COMMENT ON COLUMN public.recruitment_admins.is_first_login IS 'true=wajib ganti password Itsp@YYYY';
-- >>> KLIK COMMIT di DBeaver di sini (atau pastikan Auto-commit ON) sebelum lanjut ke STEP 1B <<<

-- STEP 1B — promote / insert (polos 1526.08.26; legacy ITSP.1526.08.26 ikut dibetulkan sekali jalan)
CREATE EXTENSION IF NOT EXISTS pgcrypto;
UPDATE public.recruitment_admins
SET employee_id='1526.08.26', username='it-04', name='IT Admin',
    role='admin', department='IT', is_active=true, portal_access='both',
    is_first_login=true, password=crypt('Itsp@2026', gen_salt('bf',10))
WHERE lower(email)=lower('it-04@thaisummit.co.id')
   OR lower(username)=lower('it-04')
   OR employee_id='1526.08.26'
   OR employee_id='ITSP.1526.08.26'; -- legacy one-time
INSERT INTO public.recruitment_admins (employee_id, username, name, email, password, role, department, is_active, portal_access, is_first_login, is_mfa_enabled)
SELECT '1526.08.26','it-04','IT Admin','it-04@thaisummit.co.id',crypt('Itsp@2026', gen_salt('bf',10)),'admin','IT',true,'both',true,false
WHERE NOT EXISTS (SELECT 1 FROM public.recruitment_admins WHERE employee_id IN ('1526.08.26','ITSP.1526.08.26') OR lower(email)=lower('it-04@thaisummit.co.id') OR lower(username)=lower('it-04'));

-- Verifikasi web_karir (baru bisa SELECT employee_id setelah STEP 1A):
SELECT id, employee_id, username, email, role, is_active, portal_access, is_first_login FROM public.recruitment_admins WHERE employee_id IN ('1526.08.26','ITSP.1526.08.26') OR lower(email)=lower('it-04@thaisummit.co.id');

-- ===================== BLOK 2: web_perusahaan (users) — jalankan di DB web_perusahaan =====================
-- Putuskan koneksi web_karir, hubungkan ke DB web_perusahaan lalu jalankan blok ini:
-- SELECT current_database(); -- harus web_perusahaan
-- SELECT column_name, data_type, column_default FROM information_schema.columns WHERE table_schema='public' AND table_name='users' ORDER BY 1;

-- STEP 2A — DDL + DEFAULT NOW() untuk raw SQL (hindari 23502 updated_at NOT NULL)
ALTER TABLE public.users
  ADD COLUMN IF NOT EXISTS employee_id VARCHAR(50) UNIQUE NULL,
  ADD COLUMN IF NOT EXISTS is_first_login BOOLEAN DEFAULT TRUE NOT NULL;
-- Postgres default hanya di SQLAlchemy; live butuh DEFAULT NOW() agar INSERT tanpa timestamps tidak 23502
ALTER TABLE public.users ALTER COLUMN created_at SET DEFAULT NOW();
ALTER TABLE public.users ALTER COLUMN updated_at SET DEFAULT NOW();
CREATE INDEX IF NOT EXISTS ix_users_employee_id ON public.users(employee_id);
CREATE INDEX IF NOT EXISTS ix_users_is_first_login ON public.users(is_first_login);
COMMENT ON COLUMN public.users.employee_id IS 'Immutable Employee ID 1526.08.26 polos tanpa prefix ITSP.';
COMMENT ON COLUMN public.users.is_first_login IS 'true=wajib ganti password Itsp@YYYY';
-- >>> KLIK COMMIT di DBeaver di sini (atau pastikan Auto-commit ON) sebelum lanjut ke STEP 2B <<<

-- STEP 2B — promote / insert (isi NOW() eksplisit agar tetap lolos bila DEFAULT belum commit)
CREATE EXTENSION IF NOT EXISTS pgcrypto;
UPDATE public.users
SET employee_id='1526.08.26', username='it-04', name='IT Admin',
    role='admin', department='IT', is_active=true, portal_access='both',
    is_first_login=true, password=crypt('Itsp@2026', gen_salt('bf',10)), updated_at=NOW()
WHERE lower(email)=lower('it-04@thaisummit.co.id')
   OR (username IS NOT NULL AND lower(username)=lower('it-04'))
   OR employee_id='1526.08.26'
   OR employee_id='ITSP.1526.08.26'; -- legacy one-time
INSERT INTO public.users (employee_id, username, email, password, name, role, department, mfa_enabled, is_active, portal_access, is_first_login, created_at, updated_at)
SELECT '1526.08.26','it-04','it-04@thaisummit.co.id',crypt('Itsp@2026', gen_salt('bf',10)),'IT Admin','admin','IT',false,true,'both',true, NOW(), NOW()
WHERE NOT EXISTS (SELECT 1 FROM public.users WHERE employee_id IN ('1526.08.26','ITSP.1526.08.26') OR lower(email)=lower('it-04@thaisummit.co.id') OR (username IS NOT NULL AND lower(username)=lower('it-04')));

-- Verifikasi web_perusahaan:
SELECT id, employee_id, username, email, role, is_active, portal_access, is_first_login FROM public.users WHERE employee_id IN ('1526.08.26','ITSP.1526.08.26') OR lower(email)=lower('it-04@thaisummit.co.id');

-- Login test setelah kedua blok: Employee ID = 1526.08.26 (polos) | fallback email = it-04@thaisummit.co.id | password = Itsp@2026 (wajib ganti saat first login)
