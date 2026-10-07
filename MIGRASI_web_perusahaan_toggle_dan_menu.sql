-- MIGRASI web_perusahaan (DATABASE_COMPANY_URL) + admin_menus
-- Jalankan: psql "$DATABASE_COMPANY_URL" -f MIGRASI_web_perusahaan_toggle_dan_menu.sql
-- 1) users: toggle active + portal access
ALTER TABLE public.users ADD COLUMN IF NOT EXISTS username TEXT;
ALTER TABLE public.users ADD COLUMN IF NOT EXISTS department TEXT;
ALTER TABLE public.users ADD COLUMN IF NOT EXISTS is_active BOOLEAN DEFAULT true NOT NULL;
ALTER TABLE public.users ADD COLUMN IF NOT EXISTS portal_access TEXT DEFAULT 'both' NOT NULL;
-- 1b) admin_menus (dinamis)
CREATE TABLE IF NOT EXISTS public.admin_menus (
  id integer GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  title TEXT NOT NULL,
  url TEXT NOT NULL,
  portal TEXT NOT NULL DEFAULT 'perusahaan' CHECK (portal IN ('perusahaan','karir','both')),
  location TEXT NOT NULL CHECK (location IN ('admin_sidebar','admin_top')),
  icon TEXT,
  section TEXT,
  sort_order integer DEFAULT 0 NOT NULL,
  is_active boolean DEFAULT true NOT NULL,
  allowed_roles TEXT,
  parent_id integer REFERENCES public.admin_menus(id) ON DELETE CASCADE,
  created_at timestamp(3) without time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
  updated_at timestamp(3) without time zone DEFAULT CURRENT_TIMESTAMP NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_admin_menus_portal ON public.admin_menus(portal);
CREATE INDEX IF NOT EXISTS ix_admin_menus_location ON public.admin_menus(location);
CREATE INDEX IF NOT EXISTS ix_admin_menus_is_active ON public.admin_menus(is_active);
INSERT INTO public.admin_menus (title,url,portal,location,icon,sort_order,is_active,allowed_roles) VALUES
 ('Dashboard','/admin','both','admin_sidebar','DashboardIcon',0,true,NULL),
 ('Manufactured Products','/admin/products','perusahaan','admin_sidebar','Inventory2Icon',10,true,'admin,marketing'),
 ('ISO Certifications','/admin/certifications','perusahaan','admin_sidebar','WorkspacePremiumIcon',20,true,'admin,marketing'),
 ('Plant Facilities','/admin/facilities','perusahaan','admin_sidebar','PrecisionManufacturingIcon',30,true,'admin,marketing'),
 ('Services','/admin/services','perusahaan','admin_sidebar','MiscellaneousServicesIcon',40,true,'admin,marketing'),
 ('Blog Articles','/admin/blog-posts','perusahaan','admin_sidebar','ArticleIcon',50,true,'admin,marketing,editor'),
 ('Sustainability Reports','/admin/sustainability-reports','perusahaan','admin_sidebar','AssessmentIcon',60,true,'admin,marketing'),
 ('Hero Banners','/admin/hero-sections','perusahaan','admin_sidebar','ViewCarouselIcon',70,true,'admin'),
 ('Announcements','/admin/announcements','perusahaan','admin_sidebar','CampaignIcon',80,true,'admin'),
 ('Key Features','/admin/features','perusahaan','admin_sidebar','StarIcon',90,true,'admin'),
 ('Partners & Clients','/admin/partners','perusahaan','admin_sidebar','HandshakeIcon',100,true,'admin'),
 ('Testimonials','/admin/testimonials','perusahaan','admin_sidebar','FormatQuoteIcon',110,true,'admin'),
 ('FAQs','/admin/faqs','perusahaan','admin_sidebar','QuizIcon',120,true,'admin,editor'),
 ('Statistics','/admin/statistics','perusahaan','admin_sidebar','BarChartIcon',130,true,'admin'),
 ('Inbox Messages','/admin/contacts','perusahaan','admin_sidebar','MailIcon',140,true,'admin,marketing'),
 ('User Management','/admin/users','perusahaan','admin_sidebar','AdminPanelSettingsIcon',150,true,'admin'),
 ('Navigation Menus','/admin/nav-menus','perusahaan','admin_sidebar','NavigationIcon',160,true,'admin'),
 ('Manage Pages','/admin/pages','perusahaan','admin_sidebar','WebAssetIcon',170,true,'admin'),
 ('Security & MFA','/admin/mfa-setup','perusahaan','admin_sidebar','ShieldIcon',180,true,NULL),
 ('Site Settings','/admin/settings','perusahaan','admin_sidebar','SettingsIcon',190,true,'admin'),
 ('Data Pelamar (7 Tahap)','/admin/applicants','karir','admin_top','PeopleIcon',0,true,'admin,hr,user_dept'),
 ('Data Karyawan','/admin/employees','karir','admin_top','EmployeeIcon',10,true,'admin,hr'),
 ('Kelola Lowongan','/admin/jobs','karir','admin_top','WorkIcon',20,true,'admin,hr'),
 ('Departemen & Section','/admin/departments','karir','admin_top','DeptIcon',30,true,'admin,hr'),
 ('Bank Soal Ujian Online','/admin/questions','karir','admin_top','QuizIcon',40,true,'admin,hr,user_dept'),
 ('Cetak ID Card Karyawan','/admin/id-cards','karir','admin_top','BadgeIcon',50,true,'admin,hr'),
 ('Pengaturan MCU & Default','/admin/settings','karir','admin_top','SettingsIcon',60,true,'admin,hr'),
 ('Kelola Akun & Reset Password','/admin/users','karir','admin_top','AdminPanelSettingsIcon',70,true,'admin')
ON CONFLICT DO NOTHING;
DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname='users_portal_access_check') THEN
    ALTER TABLE public.users ADD CONSTRAINT users_portal_access_check CHECK (portal_access IN ('perusahaan','karir','both'));
  END IF;
END $$;
CREATE INDEX IF NOT EXISTS ix_users_is_active ON public.users(is_active);
CREATE INDEX IF NOT EXISTS ix_users_portal_access ON public.users(portal_access);
CREATE INDEX IF NOT EXISTS ix_users_role ON public.users(role);
DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_indexes WHERE indexname='users_username_key') THEN
    CREATE UNIQUE INDEX users_username_key ON public.users(username) WHERE username IS NOT NULL;
  END IF;
END $$;
UPDATE public.users SET is_active = true WHERE is_active IS NULL;
UPDATE public.users SET portal_access = 'both' WHERE portal_access IS NULL OR portal_access = '';
COMMENT ON COLUMN public.users.is_active IS 'false = akun dinonaktifkan, tidak bisa login ke portal manapun';
COMMENT ON COLUMN public.users.portal_access IS 'perusahaan | karir | both';

-- 2) nav_menus: perluas untuk menu dinamis
ALTER TABLE public.nav_menus ADD COLUMN IF NOT EXISTS is_maintenance BOOLEAN DEFAULT false NOT NULL;
ALTER TABLE public.nav_menus ADD COLUMN IF NOT EXISTS portal TEXT DEFAULT 'perusahaan' NOT NULL;
ALTER TABLE public.nav_menus ADD COLUMN IF NOT EXISTS allowed_roles TEXT DEFAULT NULL;
ALTER TABLE public.nav_menus ADD COLUMN IF NOT EXISTS icon TEXT DEFAULT NULL;
DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname='nav_menus_portal_check') THEN
    ALTER TABLE public.nav_menus ADD CONSTRAINT nav_menus_portal_check CHECK (portal IN ('perusahaan','karir','both'));
  END IF;
END $$;
CREATE INDEX IF NOT EXISTS ix_nav_menus_portal ON public.nav_menus(portal);
CREATE INDEX IF NOT EXISTS ix_nav_menus_location ON public.nav_menus(location);
CREATE INDEX IF NOT EXISTS ix_nav_menus_is_active ON public.nav_menus(is_active);
UPDATE public.nav_menus SET portal='perusahaan' WHERE portal IS NULL;
COMMENT ON COLUMN public.nav_menus.portal IS 'perusahaan/web-perusahaan, karir/web-karir, both=keduanya';
COMMENT ON COLUMN public.nav_menus.allowed_roles IS 'CSV role (NULL=semua). cth: admin,hr,user_dept,marketing,editor';
COMMENT ON COLUMN public.nav_menus.icon IS 'nama MUI icon';
