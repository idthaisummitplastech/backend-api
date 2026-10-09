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

COMMENT ON COLUMN public.recruitment_admins.employee_id IS 'Immutable FK data_karyawan.employee_id 004.02.16';
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
COMMENT ON COLUMN public.users.employee_id IS 'Immutable Employee ID sinkron data_karyawan';
COMMENT ON COLUMN public.users.is_first_login IS 'true=wajib ganti password Itsp@YYYY';

-- Backfill opsi dblink (jika 1 cluster) atau CSV manual:
-- CREATE EXTENSION IF NOT EXISTS dblink;
-- UPDATE public.users u SET employee_id = dk.employee_id
-- FROM dblink('dbname=web_karir','SELECT lower(email) AS lc, employee_id FROM data_karyawan WHERE employee_id IS NOT NULL')
--   AS dk(lc TEXT, employee_id VARCHAR(50))
-- WHERE u.employee_id IS NULL AND lower(trim(u.email)) = dk.lc;

