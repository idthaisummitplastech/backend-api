-- FIX_EMPLOYEE_ID_IT04_LIVE.sql — 1-klik untuk DB live yang ERROR column "employee_id" does not exist
-- Jalankan BLOK 1 di koneksi DB web_karir, lalu BLOK 2 di koneksi DB web_perusahaan (jangan cross-DB).
-- Idempotent — aman di-rerun. Urutan penting: ALTER dulu baru UPDATE/INSERT.

-- ===================== BLOK 1: web_karir (recruitment_admins) — jalankan di DB web_karir =====================
-- Diagnosis (opsional): cek kolom sudah ada?
-- SELECT column_name, data_type, is_nullable FROM information_schema.columns WHERE table_schema='public' AND table_name='recruitment_admins' ORDER BY column_name;

ALTER TABLE public.recruitment_admins
  ADD COLUMN IF NOT EXISTS employee_id VARCHAR(50) UNIQUE NULL,
  ADD COLUMN IF NOT EXISTS is_first_login BOOLEAN DEFAULT TRUE NOT NULL;
CREATE INDEX IF NOT EXISTS ix_recruitment_admins_employee_id ON public.recruitment_admins(employee_id);
CREATE INDEX IF NOT EXISTS ix_recruitment_admins_is_first_login ON public.recruitment_admins(is_first_login);
COMMENT ON COLUMN public.recruitment_admins.employee_id IS 'Immutable FK data_karyawan.employee_id ITSP.1526.08.26';
COMMENT ON COLUMN public.recruitment_admins.is_first_login IS 'true=wajib ganti password Itsp@YYYY';

-- Backfill email -> employee_id bila ada data_karyawan (lewati jika tidak ada tabel)
-- UPDATE public.recruitment_admins ra SET employee_id = dk.employee_id FROM public.data_karyawan dk
-- WHERE ra.employee_id IS NULL AND lower(trim(ra.email))=lower(trim(dk.email)) AND dk.employee_id IS NOT NULL
--   AND NOT EXISTS (SELECT 1 FROM public.recruitment_admins ra2 WHERE ra2.employee_id=dk.employee_id AND ra2.id<>ra.id);

CREATE EXTENSION IF NOT EXISTS pgcrypto;
UPDATE public.recruitment_admins
SET employee_id='ITSP.1526.08.26', username='it-04', name='IT Admin',
    role='admin', department='IT', is_active=true, portal_access='both',
    is_first_login=true, password=crypt('Itsp@2026', gen_salt('bf',10))
WHERE lower(email)=lower('it-04@thaisummit.co.id')
   OR lower(username)=lower('it-04')
   OR employee_id='ITSP.1526.08.26';
INSERT INTO public.recruitment_admins (employee_id, username, name, email, password, role, department, is_active, portal_access, is_first_login, is_mfa_enabled)
SELECT 'ITSP.1526.08.26','it-04','IT Admin','it-04@thaisummit.co.id',crypt('Itsp@2026', gen_salt('bf',10)),'admin','IT',true,'both',true,false
WHERE NOT EXISTS (SELECT 1 FROM public.recruitment_admins WHERE employee_id='ITSP.1526.08.26' OR lower(email)=lower('it-04@thaisummit.co.id') OR lower(username)=lower('it-04'));

-- Verifikasi web_karir (baru bisa SELECT employee_id setelah ALTER di atas):
SELECT id, employee_id, username, email, role, is_active, portal_access, is_first_login FROM public.recruitment_admins WHERE employee_id='ITSP.1526.08.26' OR lower(email)=lower('it-04@thaisummit.co.id');

-- ===================== BLOK 2: web_perusahaan (users) — jalankan di DB web_perusahaan =====================
-- Putuskan koneksi web_karir, hubungkan ke DB web_perusahaan lalu jalankan blok ini:
-- SELECT column_name, data_type FROM information_schema.columns WHERE table_schema='public' AND table_name='users' ORDER BY column_name;

ALTER TABLE public.users
  ADD COLUMN IF NOT EXISTS employee_id VARCHAR(50) UNIQUE NULL,
  ADD COLUMN IF NOT EXISTS is_first_login BOOLEAN DEFAULT TRUE NOT NULL;
CREATE INDEX IF NOT EXISTS ix_users_employee_id ON public.users(employee_id);
CREATE INDEX IF NOT EXISTS ix_users_is_first_login ON public.users(is_first_login);
COMMENT ON COLUMN public.users.employee_id IS 'Immutable Employee ID ITSP.1526.08.26';
COMMENT ON COLUMN public.users.is_first_login IS 'true=wajib ganti password Itsp@YYYY';

CREATE EXTENSION IF NOT EXISTS pgcrypto;
UPDATE public.users
SET employee_id='ITSP.1526.08.26', username='it-04', name='IT Admin',
    role='admin', department='IT', is_active=true, portal_access='both',
    is_first_login=true, password=crypt('Itsp@2026', gen_salt('bf',10))
WHERE lower(email)=lower('it-04@thaisummit.co.id')
   OR (username IS NOT NULL AND lower(username)=lower('it-04'))
   OR employee_id='ITSP.1526.08.26';
INSERT INTO public.users (employee_id, username, email, password, name, role, department, mfa_enabled, is_active, portal_access, is_first_login)
SELECT 'ITSP.1526.08.26','it-04','it-04@thaisummit.co.id',crypt('Itsp@2026', gen_salt('bf',10)),'IT Admin','admin','IT',false,true,'both',true
WHERE NOT EXISTS (SELECT 1 FROM public.users WHERE employee_id='ITSP.1526.08.26' OR lower(email)=lower('it-04@thaisummit.co.id') OR (username IS NOT NULL AND lower(username)=lower('it-04')));

-- Verifikasi web_perusahaan:
SELECT id, employee_id, username, email, role, is_active, portal_access, is_first_login FROM public.users WHERE employee_id='ITSP.1526.08.26' OR lower(email)=lower('it-04@thaisummit.co.id');

-- Login test setelah kedua blok: Employee ID = ITSP.1526.08.26 | fallback email = it-04@thaisummit.co.id | password = Itsp@2026 (wajib ganti)
