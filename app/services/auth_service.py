from typing import Any, Dict, Optional
from sqlalchemy.orm import Session
from fastapi import HTTPException, status
from app.crud.crud_auth import crud_admin, crud_user
from app.crud.crud_recruitment import crud_applicant
from app.core.security import (
    create_access_token,
    verify_totp,
    generate_totp_secret,
    generate_totp_uri,
    get_password_hash,
)
from app.schemas.auth import Token, AdminCreate


class AuthService:
    """Enterprise authentication and session orchestration service."""

    def authenticate_admin(
        self,
        db: Session,
        username_or_email: str,
        password: str,
        totp_code: Optional[str] = None,
    ) -> Token:
        """Authenticate HR/Admin via Employee ID primary (004.02.16) → username → email fallback + resign/is_active guard."""
        raw = (username_or_email or "").strip()
        admin = crud_admin.authenticate(
            db, username_or_email=raw, password=password
        )
        if not admin:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Employee ID / Username / Email atau password salah.",
            )

        # is_active guard
        if hasattr(admin, "is_active") and getattr(admin, "is_active") is False:
            raise HTTPException(status_code=403, detail="Akun Anda telah dinonaktifkan oleh Administrator.")

        # employee_status resign guard (if linked to data_karyawan)
        try:
            emp_id = getattr(admin, "employee_id", None)
            if emp_id:
                from app.models.recruitment import DataKaryawan
                dk = db.query(DataKaryawan).filter(DataKaryawan.employee_id == emp_id).first()
                if dk and getattr(dk, "employee_status", None) == "resign":
                    raise HTTPException(status_code=403, detail="Akun karyawan sudah resign — akses ditolak. Hubungi HR.")
        except HTTPException:
            raise
        except Exception:
            pass

        # Check MFA if enabled
        if admin.is_mfa_enabled:
            if not totp_code:
                return Token(
                    access_token="",
                    expires_in=0,
                    role=admin.role,
                    name=admin.name,
                    email=admin.email,
                    department=admin.department,
                    requires_mfa=True,
                    employee_id=getattr(admin, "employee_id", None),
                    is_first_login=getattr(admin, "is_first_login", False),
                )
            if not verify_totp(admin.mfa_secret or "", totp_code):
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Kode Autentikasi 2FA (TOTP) tidak valid atau kedaluwarsa.",
                )

        token = create_access_token(
            subject=admin.id,
            role=admin.role,
            department=admin.department,
            extra_claims={"name": admin.name, "email": admin.email, "type": "admin", "employee_id": getattr(admin, "employee_id", None)},
        )
        return Token(
            access_token=token,
            expires_in=480 * 60,
            role=admin.role,
            name=admin.name,
            email=admin.email,
            department=admin.department,
            requires_mfa=False,
            employee_id=getattr(admin, "employee_id", None),
            is_first_login=getattr(admin, "is_first_login", False),
        )

    def authenticate_applicant(
        self,
        db: Session,
        email: str,
        password: str,
    ) -> Token:
        """Authenticate career portal applicant."""
        applicant = crud_applicant.authenticate(db, email=email, password=password)
        if not applicant:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Email atau password pelamar salah.",
            )

        token = create_access_token(
            subject=applicant.id,
            role="applicant",
            extra_claims={
                "name": applicant.full_name,
                "email": applicant.email,
                "stage": applicant.current_stage,
                "type": "applicant",
            },
        )
        return Token(
            access_token=token,
            expires_in=180 * 60,
            role="applicant",
            name=applicant.full_name,
            full_name=applicant.full_name,
            fullName=applicant.full_name,
            email=applicant.email,
            requires_mfa=False,
            id=applicant.id,
            applicant_id=applicant.id,
        )

    def setup_admin_mfa(self, db: Session, admin_id: int) -> Dict[str, str]:
        """Generate a new TOTP secret and QR URI for admin."""
        admin = crud_admin.get(db, admin_id)
        if not admin:
            raise HTTPException(status_code=404, detail="Admin tidak ditemukan.")

        secret = generate_totp_secret()
        uri = generate_totp_uri(secret, username=admin.email)
        admin.mfa_secret = secret
        db.commit()

        return {"secret": secret, "qr_uri": uri}

    def verify_and_enable_mfa(self, db: Session, admin_id: int, code: str) -> bool:
        """Verify code and formally activate MFA for admin account."""
        admin = crud_admin.get(db, admin_id)
        if not admin or not admin.mfa_secret:
            raise HTTPException(status_code=400, detail="MFA belum diinisialisasi.")

        if not verify_totp(admin.mfa_secret, code):
            raise HTTPException(status_code=400, detail="Kode verifikasi salah.")

        admin.is_mfa_enabled = True
        db.commit()
        return True


auth_service = AuthService()
