import os
import sys
import argparse
import secrets
import string
import logging
from datetime import datetime, timezone
from typing import Optional, Tuple, Any

# Ensure backend-api root in sys.path
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
BACKEND_DIR = os.path.abspath(os.path.join(SCRIPT_DIR, ".."))
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

from app.db.session import SessionLocal, SessionCompanyLocal
from app.models.auth import RecruitmentAdmin, User
from app.core.security import get_password_hash

logger = logging.getLogger("audit_recovery")
logger.setLevel(logging.INFO)
if not logger.handlers:
    ch = logging.StreamHandler(sys.stdout)
    ch.setFormatter(logging.Formatter("[%(asctime)s UTC] [%(levelname)s] [AUDIT] %(message)s"))
    logger.addHandler(ch)


def generate_secure_temporary_password(length: int = 16) -> str:
    """Generate cryptographically secure temporary password satisfying complexity rules."""
    upper = string.ascii_uppercase
    lower = string.ascii_lowercase
    digits = string.digits
    special = "!@#$%^&*"
    all_chars = upper + lower + digits + special

    # Ensure at least one character from each set
    pwd = [
        secrets.choice(upper),
        secrets.choice(lower),
        secrets.choice(digits),
        secrets.choice(special),
    ]
    for _ in range(length - 4):
        pwd.append(secrets.choice(all_chars))
    secrets.SystemRandom().shuffle(pwd)
    return "".join(pwd)


def find_account(db, realm: str, identifier: str) -> Optional[Any]:
    """Find account in respective realm by ID, email, or username."""
    identifier_clean = identifier.strip()
    is_numeric = identifier_clean.isdigit()

    if realm == "ats":
        q = db.query(RecruitmentAdmin)
        if is_numeric:
            account = q.filter(RecruitmentAdmin.id == int(identifier_clean)).first()
            if account:
                return account
        return q.filter(
            (RecruitmentAdmin.email.ilike(identifier_clean))
            | (RecruitmentAdmin.username.ilike(identifier_clean))
        ).first()

    elif realm == "cms":
        q = db.query(User)
        if is_numeric:
            account = q.filter(User.id == int(identifier_clean)).first()
            if account:
                return account
        return q.filter(
            (User.email.ilike(identifier_clean))
            | (User.username.ilike(identifier_clean))
        ).first()

    return None


def execute_recovery(
    realm: str,
    identifier: str,
    action: str,
    custom_password: Optional[str] = None,
    sync: bool = False,
    db_ats=None,
    db_cms=None,
) -> Tuple[bool, str, Optional[str]]:
    """
    Execute disaster recovery on the targeted account.
    Returns: (success: bool, message: str, generated_temp_password: Optional[str])
    """
    realm_normalized = realm.lower().strip()
    if realm_normalized not in ("ats", "cms"):
        return False, "Parameter --realm wajib bernilai 'ats' atau 'cms'.", None

    action_normalized = action.lower().strip()
    if action_normalized not in ("reset-mfa", "reset-password", "break-glass"):
        return False, "Parameter --action wajib bernilai 'reset-mfa', 'reset-password', atau 'break-glass'.", None

    close_ats = False
    close_cms = False
    if db_ats is None:
        db_ats = SessionLocal()
        close_ats = True
    if db_cms is None:
        db_cms = SessionCompanyLocal()
        close_cms = True

    try:
        active_db = db_ats if realm_normalized == "ats" else db_cms
        account = find_account(active_db, realm_normalized, identifier)

        if not account:
            logger.warning(
                f"RECOVERY_FAILED realm={realm_normalized} identifier={identifier} "
                f"action={action_normalized} reason=ACCOUNT_NOT_FOUND"
            )
            return False, f"Akun pada realm '{realm_normalized}' dengan pengenal '{identifier}' tidak ditemukan.", None

        now_utc = datetime.now(timezone.utc)
        temp_pwd_generated = None
        target_email = getattr(account, "email", None)

        # 1. Reset MFA
        if action_normalized in ("reset-mfa", "break-glass"):
            if realm_normalized == "ats":
                account.is_mfa_enabled = False
            else:
                account.mfa_enabled = False
            account.mfa_secret = None
            if hasattr(account, "backup_codes"):
                account.backup_codes = None
            account.mfa_verified_at = None
            account.totp_failed_attempts = 0
            account.totp_locked_until = None

        # 2. Reset Password
        if action_normalized in ("reset-password", "break-glass"):
            new_pwd = custom_password.strip() if custom_password and custom_password.strip() else generate_secure_temporary_password(16)
            temp_pwd_generated = new_pwd
            account.password = get_password_hash(new_pwd)
            account.is_first_login = True
            account.password_changed_at = now_utc
            account.mfa_verified_at = None

        # 3. Always bump session version to invalidate all stale tokens/sessions
        account.session_version = (getattr(account, "session_version", 1) or 1) + 1
        active_db.commit()

        # 4. Optional Realm Synchronization
        if sync and target_email:
            peer_db = db_cms if realm_normalized == "ats" else db_ats
            peer_realm = "cms" if realm_normalized == "ats" else "ats"
            peer_account = find_account(peer_db, peer_realm, target_email)
            if peer_account:
                if action_normalized in ("reset-mfa", "break-glass"):
                    if peer_realm == "ats":
                        peer_account.is_mfa_enabled = False
                    else:
                        peer_account.mfa_enabled = False
                    peer_account.mfa_secret = None
                    if hasattr(peer_account, "backup_codes"):
                        peer_account.backup_codes = None
                    peer_account.mfa_verified_at = None
                    peer_account.totp_failed_attempts = 0
                    peer_account.totp_locked_until = None

                if action_normalized in ("reset-password", "break-glass") and temp_pwd_generated:
                    peer_account.password = get_password_hash(temp_pwd_generated)
                    peer_account.is_first_login = True
                    peer_account.password_changed_at = now_utc
                    peer_account.mfa_verified_at = None

                peer_account.session_version = (getattr(peer_account, "session_version", 1) or 1) + 1
                peer_db.commit()

        # AUDIT LOG AMAN: TIDAK MENCATAT PASSWORD
        logger.info(
            f"RECOVERY_SUCCESS realm={realm_normalized} account_id={account.id} "
            f"email={target_email} action={action_normalized} sync={sync} "
            f"session_version={account.session_version} is_first_login={getattr(account, 'is_first_login', None)}"
        )

        msg = f"Pemulihan akun [{realm_normalized.upper()}] ID={account.id} ({account.email}) berhasil dieksekusi dengan aksi '{action_normalized}'."
        return True, msg, temp_pwd_generated

    except Exception as exc:
        if active_db:
            active_db.rollback()
        logger.error(
            f"RECOVERY_ERROR realm={realm_normalized} identifier={identifier} "
            f"action={action_normalized} error={str(exc)}"
        )
        return False, f"Terjadi kesalahan saat pemulihan: {str(exc)}", None
    finally:
        if close_ats and db_ats:
            db_ats.close()
        if close_cms and db_cms:
            db_cms.close()


def main():
    parser = argparse.ArgumentParser(
        description="PT ITSP Multi-Realm Offline Disaster Recovery & Emergency Reset Tool"
    )
    parser.add_argument(
        "--realm",
        required=True,
        choices=["ats", "cms"],
        help="Target realm basis data akun (ats: recruitment_admins, cms: users). Wajib eksplisit.",
    )
    parser.add_argument(
        "--identifier",
        required=True,
        help="Pengenal akun target: email, username, atau ID numerik.",
    )
    parser.add_argument(
        "--action",
        required=True,
        choices=["reset-mfa", "reset-password", "break-glass"],
        help="Aksi pemulihan yang akan dijalankan.",
    )
    parser.add_argument(
        "--password",
        default=None,
        help="Kata sandi baru pilihan operator (opsional). Jika tidak diisi, dibuatkan otomatis.",
    )
    parser.add_argument(
        "--sync",
        action="store_true",
        default=False,
        help="Sinkronisasikan reset kredensial ke realm pasangan jika email akun ditemukan sama.",
    )

    args = parser.parse_args()

    success, message, temp_pwd = execute_recovery(
        realm=args.realm,
        identifier=args.identifier,
        action=args.action,
        custom_password=args.password,
        sync=args.sync,
    )

    print("\n" + "=" * 60)
    print("HASIL PEMULIHAN AKUN:")
    print("=" * 60)
    print(f"Status   : {'SUKSES' if success else 'GAGAL'}")
    print(f"Pesan    : {message}")
    if temp_pwd:
        print(f"Temporary Password : {temp_pwd}")
        print("PERINGATAN: Berikan kata sandi sementara ini kepada pemilik akun melalui kanal aman.")
        print("Akun diwajibkan mengganti kata sandi pada saat login pertama kali (first-login).")
    print("=" * 60 + "\n")

    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
