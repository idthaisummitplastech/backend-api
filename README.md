# PT ITSP Enterprise Core Backend API (Python & FastAPI)

[![Python Version](https://img.shields.io/badge/python-3.13-blue.svg)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.115+-009688.svg)](https://fastapi.tiangolo.com)
[![SQLAlchemy](https://img.shields.io/badge/SQLAlchemy-2.0+-red.svg)](https://www.sqlalchemy.org/)
[![PostgreSQL](https://img.shields.io/badge/PostgreSQL-16-blue.svg)](https://www.postgresql.org/)
[![Security](https://img.shields.io/badge/OWASP-Hardened-green.svg)](https://owasp.org/)

Backend REST API Gateway terpadu berstandar enterprise untuk **PT Indonesia Thai Summit Plastech (ITSP)**. Menggabungkan sistem rekrutmen & pelacakan seleksi 7-tahap (Web Karir ATS) dan Content Management System profil perusahaan (Web Perusahaan).

---

## 🏛️ Arsitektur & Pola Desain (Clean Architecture & OOP)

Proyek ini dibangun secara ketat mengikuti kaidah **Object-Oriented Programming (OOP)** dan **Clean Architecture**:

- **Generic Repository Pattern (`CRUDBase`)**: Seluruh 20+ model PostgreSQL mewarisi kelas generic type `CRUDBase[ModelType, CreateSchemaType, UpdateSchemaType]` sehingga operasi data access (Create, Read, Update, Delete, Pagination, Counting) sangat reusable tanpa redundansi kode.
- **Dynamic CMS Registry (`CMSModelRegistry`)**: Mengelola 15 entitas CMS secara dinamis dengan satu handler kueri yang aman.
- **Service Layer Pattern**: Logika bisnis (evaluasi ujian, anti-cheat, NIK generator, SMTP mailer, RBAC) terisolasi sepenuhnya dari HTTP Controller.
- **Role-Based Access Control (RBAC)**: Dependency injection `RoleChecker(["admin", "hr", "user_dept"])` dengan isolasi hak akses level departemen.

---

## 🛡️ Fitur Keamanan (Security Awareness)

1. **Pencegahan SQL Injection**: Kueri menggunakan SQLAlchemy 2.0 ORM dengan *parameterized binding*.
2. **Password Cryptography**: Hashing Bcrypt (salt factor 12) dengan verifikasi *constant-time* untuk mencegah serangan timing.
3. **Autentikasi Dua Faktor (2FA / MFA)**: Mendukung TOTP RFC 6238 (Google Authenticator / Microsoft Authenticator) menggunakan pyotp.
4. **OWASP Security Headers**: Injeksi otomatis header `X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY`, `X-XSS-Protection`, dan `HSTS`.
5. **SlowAPI Rate Limiting**: Pembatasan frekuensi request pada endpoint sensitif (`/auth/login`, `/applicants/apply`) untuk memitigasi serangan Brute Force & DoS.
6. **Sentry PII Sanitizer**: Pemfilteran otomatis data kredensial (password, auth token, NIK, CV) sebelum log dikirim ke Sentry.
7. **Safe Uploads**: Verifikasi MIME type, batasan berkas CV <= 100 KB, dan penamaan UUID unik untuk mencegah *Path Traversal*.

---

## 🚀 Panduan Memulai Cepat (Local Development)

### 1. Prasyarat
- Python 3.12+ atau 3.13
- PostgreSQL 15+

### 2. Setup Virtual Environment
```powershell
cd backend-api
python -m venv venv
.\venv\Scripts\activate
pip install -r requirements.txt
```

### 3. Konfigurasi Environment
Salin file `.env.example` menjadi `.env` dan sesuaikan koneksi database PostgreSQL Anda:
```powershell
copy .env.example .env
```

### 4. Menjalankan Server
```powershell
uvicorn main:app --reload --port 8000
```
- **Interactive Swagger UI**: [http://localhost:8000/docs](http://localhost:8000/docs)
- **Health Check Probe**: [http://localhost:8000/health](http://localhost:8000/health)

### 5. Menjalankan Automated Testing
```powershell
pytest
```

---

## 🐳 Docker Production Deployment

```powershell
# Build dan jalankan dengan Docker
docker build -t itsp-backend-api .
docker run -d -p 8000:8000 --env-file .env itsp-backend-api
```

---

## 📁 Struktur Direktori
```text
backend-api/
├── app/
│   ├── api/             # API Router & Dependency Injection (RBAC)
│   ├── core/            # Security, Settings, Sentry, Headers Middleware
│   ├── crud/            # Generic Repository (CRUDBase) & Specialized CRUD
│   ├── db/              # SQLAlchemy Base, Session, and Database Seeder
│   ├── models/          # SQLAlchemy ORM Models (Auth, Recruitment, CMS)
│   ├── schemas/         # Pydantic v2 DTOs (Request/Response validation)
│   └── services/        # Business Logic: Auth, Email, Test Engine, NIK
├── tests/               # Pytest Automated Test Suite
├── Dockerfile           # Production container (Non-root user)
├── pytest.ini           # Testing configuration
├── requirements.txt     # Locked production dependencies
└── main.py              # Application entrypoint & lifespan
```

---

## 📄 Lisensi & Hak Cipta
Hak Cipta © 2026 PT Indonesia Thai Summit Plastech. Seluruh hak cipta dilindungi undang-undang.
