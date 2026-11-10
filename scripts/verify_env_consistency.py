#!/usr/bin/env python3
"""
Skrip Verifikasi Konsistensi Environment Secrets Antar-Layanan.
PT Indonesia Thai Summit Plastech (ITSP)

Memverifikasi bahwa:
1. INTERNAL_API_SECRET pada backend-api terdefinisi dan minimal 32 karakter.
2. BACKEND_INTERNAL_SECRET pada web-karir dan web-perusahaan bernilai SAMA PERSIS dengan INTERNAL_API_SECRET backend.
3. SECRET_KEY backend (kunci tandatangan JWT) terpisah (tidak boleh identik dengan INTERNAL_API_SECRET).

Dapat dijalankan:
- Sebagai CLI pre-deploy / CI:
    python scripts/verify_env_consistency.py
- Dengan passing argumen file .env:
    python scripts/verify_env_consistency.py --backend-env ../backend-api/.env --career-env "../web-karir v1.0/.env" --company-env "../web-perusahaan v1.0/.env"
"""

import os
import sys
import argparse
from typing import Dict, List, Optional, Tuple


def parse_env_file(filepath: str) -> Dict[str, str]:
    """Parse format KEY=VALUE dari file .env sederhana."""
    env_vars = {}
    if not os.path.exists(filepath):
        return env_vars

    with open(filepath, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" in line:
                k, v = line.split("=", 1)
                k = k.strip()
                v = v.strip().strip("'\"")
                env_vars[k] = v
    return env_vars


def verify_env_secrets(
    backend_internal_secret: Optional[str],
    career_internal_secret: Optional[str],
    company_internal_secret: Optional[str],
    backend_jwt_secret: Optional[str] = None,
) -> Tuple[bool, List[str]]:
    """
    Validasi konsistensi secret antar backend dan frontend.
    Mengembalikan (is_valid: bool, errors: list[str]).
    """
    errors: List[str] = []

    # 1. Validasi Backend INTERNAL_API_SECRET
    if not backend_internal_secret:
        errors.append("[GAGAL] Backend: INTERNAL_API_SECRET belum diatur atau kosong.")
    elif len(backend_internal_secret) < 32:
        errors.append(
            f"[GAGAL] Backend: INTERNAL_API_SECRET terlalu pendek ({len(backend_internal_secret)} karakter). Wajib minimal 32 karakter."
        )

    # 2. Validasi Frontend Web Karir BACKEND_INTERNAL_SECRET
    if not career_internal_secret:
        errors.append("[GAGAL] Web Karir: BACKEND_INTERNAL_SECRET belum diatur atau kosong.")
    elif len(career_internal_secret) < 32:
        errors.append(
            f"[GAGAL] Web Karir: BACKEND_INTERNAL_SECRET terlalu pendek ({len(career_internal_secret)} karakter). Wajib minimal 32 karakter."
        )
    elif backend_internal_secret and career_internal_secret != backend_internal_secret:
        errors.append(
            "[GAGAL] MISMATCH SECRET! BACKEND_INTERNAL_SECRET di Web Karir TIDAK COCOK dengan INTERNAL_API_SECRET di Backend. Komunikasi proxy internal akan ditolak (HTTP 403)."
        )

    # 3. Validasi Frontend Web Perusahaan BACKEND_INTERNAL_SECRET
    if not company_internal_secret:
        errors.append("[GAGAL] Web Perusahaan: BACKEND_INTERNAL_SECRET belum diatur atau kosong.")
    elif len(company_internal_secret) < 32:
        errors.append(
            f"[GAGAL] Web Perusahaan: BACKEND_INTERNAL_SECRET terlalu pendek ({len(company_internal_secret)} karakter). Wajib minimal 32 karakter."
        )
    elif backend_internal_secret and company_internal_secret != backend_internal_secret:
        errors.append(
            "[GAGAL] MISMATCH SECRET! BACKEND_INTERNAL_SECRET di Web Perusahaan TIDAK COCOK dengan INTERNAL_API_SECRET di Backend. Komunikasi proxy internal akan ditolak (HTTP 403)."
        )

    # 4. Validasi Pemisahan Secret (JWT SECRET_KEY vs INTERNAL_API_SECRET)
    if backend_jwt_secret and backend_internal_secret:
        if backend_jwt_secret == backend_internal_secret:
            errors.append(
                "[GAGAL] PELANGGARAN PEMISAHAN SECRET! Backend SECRET_KEY (kunci tandatangan JWT) sama persis dengan INTERNAL_API_SECRET. Keduanya wajib menggunakan secret yang berbeda demi prinsip least-privilege."
            )

    return (len(errors) == 0, errors)


def main():
    parser = argparse.ArgumentParser(description="Verifikasi konsistensi secret backend dan frontend.")
    parser.add_argument("--backend-env", default="", help="Path ke file .env backend-api")
    parser.add_argument("--career-env", default="", help="Path ke file .env web-karir")
    parser.add_argument("--company-env", default="", help="Path ke file .env web-perusahaan")
    args = parser.parse_args()

    # Baca dari file .env jika path diberikan, fallback ke environment variables proses
    b_env = parse_env_file(args.backend_env) if args.backend_env else {}
    c_env = parse_env_file(args.career_env) if args.career_env else {}
    p_env = parse_env_file(args.company_env) if args.company_env else {}

    backend_internal_secret = b_env.get("INTERNAL_API_SECRET") or os.environ.get("INTERNAL_API_SECRET")
    career_internal_secret = c_env.get("BACKEND_INTERNAL_SECRET") or os.environ.get("CAREER_BACKEND_INTERNAL_SECRET") or os.environ.get("BACKEND_INTERNAL_SECRET")
    company_internal_secret = p_env.get("BACKEND_INTERNAL_SECRET") or os.environ.get("COMPANY_BACKEND_INTERNAL_SECRET") or os.environ.get("BACKEND_INTERNAL_SECRET")
    backend_jwt_secret = b_env.get("SECRET_KEY") or os.environ.get("SECRET_KEY")

    is_valid, errors = verify_env_secrets(
        backend_internal_secret=backend_internal_secret,
        career_internal_secret=career_internal_secret,
        company_internal_secret=company_internal_secret,
        backend_jwt_secret=backend_jwt_secret,
    )

    if not is_valid:
        print("=" * 70, file=sys.stderr)
        print("VERIFIKASI ENVIRONMENT GAGAL! DETEKSI KETIDAKKONSISTENAN SECRET:", file=sys.stderr)
        print("=" * 70, file=sys.stderr)
        for err in errors:
            print(f"- {err}", file=sys.stderr)
        print("=" * 70, file=sys.stderr)
        sys.exit(1)
    else:
        print("[SUKSES] Seluruh secret lingkungan konsisten, memenuhi batas minimal 32 karakter, dan terisolasi dengan aman.")
        sys.exit(0)


if __name__ == "__main__":
    main()
