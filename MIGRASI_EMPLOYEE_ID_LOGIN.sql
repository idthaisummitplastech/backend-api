-- ============================================================
-- MIGRASI LOGIN EMPLOYEE ID — ITSP Reusable + Auth
-- Date: 2026-10-08 | DB: web_karir + web_perusahaan
-- Goal: Login Employee ID immutable (data_karyawan.employee_id)
--        Email tetap UNIQUE audit/notifikasi
--        Password default Itsp@YYYY hash on create/reset only
-- ============================================================
-- 0) BACKUP WAJIB (shell, bukan psql):
-- pg_dump -h localhost -U postgres -d web_karir -F c -f D:\backup_web_karir_20261008.dump
-- pg_dump -h localhost -U postgres -d web_perusahaan -F c -f D:\backup_web_perusahaan_20261008.dump

-- ============ A) web_karir — recruitment_admins ============
ALTER TABLE public.recruitment_admins
  ADD COLUMN IF NOT EXISTS employee_id VARCHAR(50) UNIQUE NULL,
  ADD COLUMN IF NOT EXISTS is_first_login BOOLEAN DEFAULT TRUE NOT NULL;

CREATE INDEX IF NOT EXISTS ix_recruitment_admins_employee_id
  ON public.recruitment_admins(employee_id);
CREATE INDEX IF NOT EXISTS ix_recruitment_admins_is_first_login
  ON public.recruitment_admins(is_first_login);

COMMENT ON COLUMN public.recruitment_admins.employee_id IS 'Immutable FK data_karyawan.employee_id 1526.08.26 (polos tanpa prefix ITSP.)';
COMMENT ON COLUMN public.recruitment_admins.is_first_login IS 'true=wajib ganti password Itsp@YYYY';

-- Audit sebelum backfill
-- SELECT COUNT(*) FROM public.recruitment_admins WHERE employee_id IS NULL;
-- SELECT email, COUNT(*) FROM public.recruitment_admins GROUP BY email HAVING COUNT(*)>1;

-- Backfill via email (case-insensitive)
UPDATE public.recruitment_admins ra
SET employee_id = dk.employee_id
FROM public.data_karyawan dk
WHERE ra.employee_id IS NULL
  AND ra.email IS NOT NULL AND dk.email IS NOT NULL
  AND lower(trim(ra.email)) = lower(trim(dk.email))
  AND dk.employee_id IS NOT NULL
  AND NOT EXISTS (
    SELECT 1 FROM public.recruitment_admins ra2
    WHERE ra2.employee_id = dk.employee_id AND ra2.id <> ra.id
  );

-- Verifikasi
-- SELECT id, employee_id, username, email FROM public.recruitment_admins ORDER BY id;
-- SELECT COUNT(*) total, COUNT(employee_id) terisi FROM public.recruitment_admins;

-- ============ B) web_perusahaan — users (CMS) ============
-- \c web_perusahaan
ALTER TABLE public.users
  ADD COLUMN IF NOT EXISTS employee_id VARCHAR(50) UNIQUE NULL,
  ADD COLUMN IF NOT EXISTS is_first_login BOOLEAN DEFAULT TRUE NOT NULL;

CREATE INDEX IF NOT EXISTS ix_users_employee_id ON public.users(employee_id);
CREATE INDEX IF NOT EXISTS ix_users_is_first_login ON public.users(is_first_login);
ALTER TABLE public.users ALTER COLUMN created_at SET DEFAULT NOW();
ALTER TABLE public.users ALTER COLUMN updated_at SET DEFAULT NOW();
COMMENT ON COLUMN public.users.employee_id IS 'Immutable Employee ID sinkron data_karyawan 1526.08.26 polos tanpa prefix ITSP.';
COMMENT ON COLUMN public.users.is_first_login IS 'true=wajib ganti password Itsp@YYYY';

-- Backfill opsi dblink (jika 1 cluster) atau CSV manual:
-- CREATE EXTENSION IF NOT EXISTS dblink;
-- UPDATE public.users u SET employee_id = dk.employee_id
-- FROM dblink('dbname=web_karir','SELECT lower(email) AS lc, employee_id FROM data_karyawan WHERE employee_id IS NOT NULL')
--   AS dk(lc TEXT, employee_id VARCHAR(50))
-- WHERE u.employee_id IS NULL AND lower(trim(u.email)) = dk.lc;

-- ============ C) PROMOTE PRIMARY SUPERADMIN 1526.08.26 / it-04@thaisummit.co.id ============
-- Super Admin utama — Employee ID immutable, role admin, portal both, password default Itsp@2026 (is_first_login=true)
-- Jalankan di KEDUA DB (web_karir + web_perusahaan). Idempotent — aman di-rerun.
-- Prasyarat: kolom employee_id sudah ada (bagian A/B di atas) + pgcrypto untuk crypt.
CREATE EXTENSION IF NOT EXISTS pgcrypto;

-- web_karir: recruitment_admins
-- C1) Jika sudah ada by email/username/legacy ITSP. -> promote + reset password ke polos 1526.08.26
UPDATE public.recruitment_admins
SET employee_id='1526.08.26', username='it-04', name='IT Admin',
    role='admin', department='IT', is_active=true, portal_access='both',
    is_first_login=true, password=crypt('Itsp@2026', gen_salt('bf',10))
WHERE lower(email)=lower('it-04@thaisummit.co.id')
   OR lower(username)=lower('it-04')
   OR employee_id IN ('1526.08.26','ITSP.1526.08.26');
-- C2) Jika belum ada sama sekali -> insert polos
INSERT INTO public.recruitment_admins (employee_id, username, name, email, password, role, department, is_active, portal_access, is_first_login, is_mfa_enabled)
SELECT '1526.08.26','it-04','IT Admin','it-04@thaisummit.co.id',crypt('Itsp@2026', gen_salt('bf',10)),'admin','IT',true,'both',true,false
WHERE NOT EXISTS (
  SELECT 1 FROM public.recruitment_admins
  WHERE employee_id IN ('1526.08.26','ITSP.1526.08.26')
     OR lower(email)=lower('it-04@thaisummit.co.id')
     OR lower(username)=lower('it-04')
);

-- web_perusahaan: users (CMS) — jalankan setelah \c web_perusahaan
-- C1) promote legacy ITSP. -> polos + set updated_at agar tidak 23502
UPDATE public.users
SET employee_id='1526.08.26', username='it-04', name='IT Admin',
    role='admin', department='IT', is_active=true, portal_access='both',
    is_first_login=true, password=crypt('Itsp@2026', gen_salt('bf',10)), updated_at=NOW()
WHERE lower(email)=lower('it-04@thaisummit.co.id')
   OR (username IS NOT NULL AND lower(username)=lower('it-04'))
   OR employee_id IN ('1526.08.26','ITSP.1526.08.26');
-- C2) insert polos dengan NOW() eksplisit (anti 23502 bila DEFAULT belum commit)
INSERT INTO public.users (employee_id, username, email, password, name, role, department, mfa_enabled, is_active, portal_access, is_first_login, created_at, updated_at)
SELECT '1526.08.26','it-04','it-04@thaisummit.co.id',crypt('Itsp@2026', gen_salt('bf',10)),'IT Admin','admin','IT',false,true,'both',true, NOW(), NOW()
WHERE NOT EXISTS (
  SELECT 1 FROM public.users
  WHERE employee_id IN ('1526.08.26','ITSP.1526.08.26')
     OR lower(email)=lower('it-04@thaisummit.co.id')
     OR (username IS NOT NULL AND lower(username)=lower('it-04'))
);
-- Verifikasi: SELECT employee_id, username, email, role, is_active, portal_access, is_first_login FROM public.recruitment_admins WHERE employee_id='1526.08.26';
-- Verifikasi: SELECT employee_id, username, email, role, is_active, portal_access, is_first_login FROM public.users WHERE employee_id='1526.08.26';
-- Login test: Employee ID = 1526.08.26  |  fallback email = it-04@thaisummit.co.id  |  password = Itsp@2026 (wajib ganti saat first login)

