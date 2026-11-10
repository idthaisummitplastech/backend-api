import json
import re
from typing import Any, Dict, List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.security import HTTPAuthorizationCredentials
from sqlalchemy.orm import Session

from app.db.session import get_db_company as get_db, get_db as get_karir_db
from app.crud.crud_cms import CMSModelRegistry, crud_contact
from app.models.cms import (
    SiteSetting,
    NavMenu,
    AdminMenu,
    HeroSection,
    Product,
    Certification,
    Facility,
    Service,
    BlogPost,
    ContactSubmission,
    SustainabilityReport,
)
from app.models.auth import User, RecruitmentAdmin
from app.schemas.cms import ContactSubmissionCreate, ContactSubmissionResponse
from app.schemas.common import ApiResponse, StatusResponse
from app.api.deps import get_current_admin, RoleChecker, security_scheme
from app.api.v1.endpoints.auth import require_internal_secret
from app.core.middleware import limiter
from app.core.security import get_password_hash, verify_password, create_access_token, verify_totp

router = APIRouter()


def camel_to_snake(name: str) -> str:
    s1 = re.sub(r'(.)([A-Z][a-z]+)', r'\1_\2', name)
    return re.sub(r'([a-z0-9])([A-Z])', r'\1_\2', s1).lower()


# --- PUBLIC CONTACT INQUIRY ---
@router.post("/contact-us", response_model=ApiResponse[ContactSubmissionResponse], status_code=status.HTTP_201_CREATED)
@limiter.limit("5/minute")
def submit_contact_form(
    request: Request,
    payload: ContactSubmissionCreate,
    db: Session = Depends(get_db),
):
    """Submit public contact form inquiry (Company Profile)."""
    item = crud_contact.create(db, obj_in=payload.model_dump())
    return ApiResponse(
        data=ContactSubmissionResponse.model_validate(item),
        message="Pesan Anda telah berhasil dikirim ke tim PT ITSP.",
    )


# --- NAV MENUS REORDER ---
@router.post("/nav-menus/reorder")
def reorder_nav_menus(
    payload: List[Dict[str, Any]],
    db: Session = Depends(get_db),
    _admin=Depends(RoleChecker(["admin", "marketing"])),
):
    """Reorder navigation menu items."""
    for item in payload:
        menu_id = item.get("id")
        sort_order = item.get("sort_order") if "sort_order" in item else item.get("sortOrder", 0)
        parent_id = item.get("parent_id") if "parent_id" in item else item.get("parentId")
        if menu_id:
            menu = db.query(NavMenu).filter(NavMenu.id == menu_id).first()
            if menu:
                menu.sort_order = int(sort_order)
                if parent_id is not None:
                    menu.parent_id = int(parent_id) if parent_id else None
    db.commit()
    return ApiResponse(message="Urutan menu navigasi berhasil diperbarui.")


# --- ADMIN MENUS (DINAMIS SIDEBAR & TOP NAV) ---
@router.get("/admin-menus")
def list_admin_menus(
    request: Request,
    portal: Optional[str] = Query(None, description="perusahaan | karir | both"),
    location: Optional[str] = Query(None, description="admin_sidebar | admin_top"),
    role: Optional[str] = Query(None, description="filter by role, e.g. admin"),
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security_scheme),
    db: Session = Depends(get_db),
    karir_db: Session = Depends(get_karir_db),
):
    """Admin menus read — wajib autentikasi (internal secret atau JWT admin). is_active=true only."""
    check_cms_model_access("admin-menus", request=request, db=karir_db, credentials=credentials)
    q = db.query(AdminMenu).filter(AdminMenu.is_active == True)  # noqa: E712
    if portal:
        q = q.filter((AdminMenu.portal == portal) | (AdminMenu.portal == "both"))
    if location:
        q = q.filter(AdminMenu.location == location)
    if role:
        # allowed_roles NULL = allow all, else CSV contains role
        q = q.filter((AdminMenu.allowed_roles.is_(None)) | (AdminMenu.allowed_roles.ilike(f"%{role}%")))
    items = q.order_by(AdminMenu.sort_order.asc(), AdminMenu.id.asc()).all()
    data = [{c.name: getattr(it, c.name) for c in it.__table__.columns} for it in items]
    return ApiResponse(data=data)


@router.post("/admin-menus/reorder")
def reorder_admin_menus(
    payload: List[Dict[str, Any]],
    db: Session = Depends(get_db),
    _admin=Depends(RoleChecker(["admin"])),
):
    """Reorder admin menu items."""
    for item in payload:
        menu_id = item.get("id")
        sort_order = item.get("sort_order") if "sort_order" in item else item.get("sortOrder", 0)
        parent_id = item.get("parent_id") if "parent_id" in item else item.get("parentId")
        if menu_id:
            menu = db.query(AdminMenu).filter(AdminMenu.id == menu_id).first()
            if menu:
                menu.sort_order = int(sort_order)
                if parent_id is not None:
                    menu.parent_id = int(parent_id) if parent_id else None
    db.commit()
    return ApiResponse(message="Urutan menu admin berhasil diperbarui.")


# --- DASHBOARD STATS FOR WEB PERUSAHAAN ---
@router.get("/dashboard-stats")
def get_dashboard_stats(
    request: Request,
    db: Session = Depends(get_db),
):
    """Retrieve summarized statistics for CMS Admin Dashboard."""
    require_internal_secret(request)

    admin_role = (request.headers.get("x-admin-role") or request.headers.get("X-Admin-Role") or "").lower()
    if admin_role not in ["admin", "superadmin", "marketing"]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Akses ditolak. Wewenang peran admin atau marketing diperlukan.",
        )

    product_count = db.query(Product).count()
    cert_count = db.query(Certification).count()
    facility_count = db.query(Facility).count()
    service_count = db.query(Service).count()
    blog_count = db.query(BlogPost).count()
    report_count = db.query(SustainabilityReport).count()
    contact_count = db.query(ContactSubmission).count()
    unread_contacts = db.query(ContactSubmission).filter(ContactSubmission.is_read == False).count()
    user_count = db.query(User).count()

    # CAND-CMS-DASH-01: Daftar rincian kontak terbaru (nama, email, subjek) hanya untuk role admin
    recent_contacts = []
    if admin_role in ["admin", "superadmin"]:
        recent_contacts_raw = (
            db.query(ContactSubmission)
            .order_by(ContactSubmission.created_at.desc())
            .limit(5)
            .all()
        )
        for c in recent_contacts_raw:
            recent_contacts.append({
                "id": c.id,
                "name": c.name,
                "email": c.email,
                "subject": c.subject,
                "created_at": c.created_at.isoformat() if c.created_at else "",
                "is_read": c.is_read,
            })

    return ApiResponse(data={
        "product_count": product_count,
        "cert_count": cert_count,
        "facility_count": facility_count,
        "service_count": service_count,
        "blog_count": blog_count,
        "report_count": report_count,
        "contact_count": contact_count,
        "unread_contacts": unread_contacts,
        "user_count": user_count,
        "recent_contacts": recent_contacts,
    })


# --- PROFILE ENDPOINTS FOR CMS ADMIN ---
@router.get("/profile")
def get_cms_profile(
    request: Request,
    user_id: int = Query(...),
    db: Session = Depends(get_db),
):
    """Fetch CMS user profile."""
    require_internal_secret(request)
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="Pengguna tidak ditemukan.")

    backup_codes_count = 0
    if user.backup_codes:
        try:
            backup_codes_count = len(json.loads(user.backup_codes))
        except Exception:
            pass

    return ApiResponse(data={
        "id": user.id,
        "name": user.name,
        "email": user.email,
        "role": user.role,
        "mfa_enabled": user.mfa_enabled,
        "backup_codes_count": backup_codes_count,
        "created_at": user.created_at.isoformat() if user.created_at else "",
    })


@router.post("/profile")
def update_cms_profile(
    payload: Dict[str, Any],
    request: Request,
    db: Session = Depends(get_db),
    karir_db: Session = Depends(get_karir_db),
):
    """Update CMS user profile, password, or MFA."""
    require_internal_secret(request)
    user_id = payload.get("user_id") or payload.get("userId")
    if not user_id:
        raise HTTPException(status_code=400, detail="User ID wajib disertakan.")

    user = db.query(User).filter(User.id == int(user_id)).first()
    if not user:
        raise HTTPException(status_code=404, detail="Pengguna tidak ditemukan.")

    action = payload.get("action")
    if action == "update_profile":
        name = str(payload.get("name", "")).strip()
        if not name:
            raise HTTPException(status_code=400, detail="Nama wajib diisi.")
        user.name = name
        db.commit()

        # Sync to recruitment_admins if exists
        rec_admin = karir_db.query(RecruitmentAdmin).filter(RecruitmentAdmin.email == user.email).first()
        if rec_admin:
            rec_admin.name = name
            karir_db.commit()

        return ApiResponse(message="Profil berhasil diperbarui.")

    elif action == "change_password":
        current_password = str(payload.get("current_password") or payload.get("currentPassword", ""))
        new_password = str(payload.get("new_password") or payload.get("newPassword", ""))
        if not current_password or not new_password:
            raise HTTPException(status_code=400, detail="Kata sandi saat ini dan baru wajib diisi.")
        if not verify_password(current_password, user.password):
            raise HTTPException(status_code=400, detail="Kata sandi saat ini tidak sesuai.")
        if len(new_password) < 12:
            raise HTTPException(status_code=400, detail="Kata sandi baru minimal 12 karakter.")

        hashed = get_password_hash(new_password)
        user.password = hashed
        user.is_first_login = False
        db.commit()

        # Sync to recruitment_admins if exists
        rec_admin = karir_db.query(RecruitmentAdmin).filter(RecruitmentAdmin.email == user.email).first()
        if rec_admin:
            rec_admin.password = hashed
            rec_admin.is_first_login = False
            karir_db.commit()

        # Terbitkan token penuh baru jika MFA sudah aktif
        new_token = None
        if user.mfa_enabled:
            new_token = create_access_token(
                subject=str(user.id),
                role=user.role,
                department=getattr(user, "department", None),
                extra_claims={"email": user.email, "name": user.name, "employee_id": getattr(user, "employee_id", None), "type": "cms"},
            )

        resp_data = {"token": new_token} if new_token else None
        return ApiResponse(data=resp_data, message="Kata sandi berhasil diubah.")

    elif action == "toggle_mfa":
        enabled = payload.get("enabled")
        new_status = bool(enabled) if enabled is not None else not user.mfa_enabled
        admin_roles = ["admin", "hr", "user_dept", "marketing"]

        # Admin, HR, User Dept, Marketing wajib MFA — tidak boleh dinonaktifkan
        if not new_status and user.role in admin_roles:
            raise HTTPException(
                status_code=400,
                detail="MFA wajib aktif untuk akun administrator dan tidak dapat dinonaktifkan.",
            )

        # Mematikan MFA untuk akun lain wajib memverifikasi password atau kode TOTP
        if not new_status and user.mfa_enabled:
            current_pw = str(payload.get("current_password") or payload.get("currentPassword", "")).strip()
            totp_code = str(payload.get("code") or payload.get("totp_code", "")).strip()
            pw_ok = current_pw and verify_password(current_pw, user.password)
            totp_ok = totp_code and user.mfa_secret and verify_totp(user.mfa_secret, totp_code)
            if not (pw_ok or totp_ok):
                raise HTTPException(
                    status_code=400,
                    detail="Mematikan MFA memerlukan verifikasi kata sandi atau kode TOTP yang valid.",
                )

        user.mfa_enabled = new_status
        if payload.get("mfa_secret") or payload.get("mfaSecret"):
            user.mfa_secret = payload.get("mfa_secret") or payload.get("mfaSecret")
        if payload.get("backup_codes") or payload.get("backupCodes"):
            bc = payload.get("backup_codes") or payload.get("backupCodes")
            user.backup_codes = bc if isinstance(bc, str) else json.dumps(bc)
        db.commit()

        # Sync to recruitment_admins if exists
        rec_admin = karir_db.query(RecruitmentAdmin).filter(RecruitmentAdmin.email == user.email).first()
        if rec_admin:
            rec_admin.is_mfa_enabled = new_status
            if user.mfa_secret:
                rec_admin.mfa_secret = user.mfa_secret
            karir_db.commit()

        # Terbitkan token penuh baru jika MFA baru saja diaktifkan dan password sudah diganti
        new_token = None
        if new_status and not getattr(user, "is_first_login", False):
            new_token = create_access_token(
                subject=str(user.id),
                role=user.role,
                department=getattr(user, "department", None),
                extra_claims={"email": user.email, "name": user.name, "employee_id": getattr(user, "employee_id", None), "type": "cms"},
            )

        return ApiResponse(
            data={"mfa_enabled": new_status, "token": new_token},
            message="Status MFA berhasil diperbarui.",
        )

    raise HTTPException(status_code=400, detail="Aksi tidak valid.")



# Kolom rahasia yang DILARANG KERAS dikembalikan oleh serializer publik / dinamis
SENSITIVE_MODEL_COLUMNS: Dict[str, Any] = {
    "users": {"password", "mfa_secret", "backup_codes"},
}


def serialize_cms_record(
    model: str,
    item: Any,
    rec_admin_map: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Serialisasi entitas ORM menjadi dictionary dengan blacklist ketat kolom rahasia.
    Memastikan kredensial seperti hash password, mfa_secret, dan backup_codes
    tidak pernah bocor pada respons GET list maupun GET single item.
    """
    sensitive_cols = SENSITIVE_MODEL_COLUMNS.get(model.lower(), set())
    d = {
        c.name: getattr(item, c.name)
        for c in item.__table__.columns
        if c.name not in sensitive_cols
    }

    if model.lower() == "users":
        em = (d.get("email") or "").lower()
        ra = (rec_admin_map or {}).get(em) if rec_admin_map else None
        dept_default = {
            "hr": "Human Capital",
            "user_dept": "Engineering",
            "admin": "IT & Systems",
            "marketing": "Marketing",
        }.get(d.get("role"), "General Management")
        d["username"] = getattr(item, "username", None) or (ra.username if (ra and ra.username) else None) or em.split("@")[0]
        d["department"] = getattr(item, "department", None) or (ra.department if (ra and ra.department) else None) or dept_default
        d["is_mfa_enabled"] = bool(d.get("mfa_enabled") or (ra and ra.is_mfa_enabled))
        d["isMfaEnabled"] = d["is_mfa_enabled"]
        d["is_active"] = bool(d.get("is_active", True) if d.get("is_active") is not None else True)
        d["portal_access"] = (d.get("portal_access") or (getattr(ra, "portal_access", None) if ra else None) or "both")
        d["portalAccess"] = d["portal_access"]
        d["isActive"] = d["is_active"]

    return d


# Daftar model CMS yang dapat dibaca secara publik oleh situs utama
PUBLIC_GET_MODELS = {
    "hero-sections",
    "nav-menus",
    "announcements",
    "partners",
    "features",
    "services",
    "products",
    "blog-posts",
    "testimonials",
    "faqs",
    "statistics",
    "certifications",
    "facilities",
    "sustainability-reports",
    "pages",
    "settings",
}

# Model konten CMS yang dapat ditulis oleh peran admin dan marketing (16 model)
CMS_CONTENT_MODELS = {
    "settings",
    "nav-menus",
    "hero-sections",
    "announcements",
    "partners",
    "features",
    "services",
    "products",
    "blog-posts",
    "testimonials",
    "faqs",
    "statistics",
    "certifications",
    "facilities",
    "sustainability-reports",
    "pages",
}

# Model sensitif yang wajib diotentikasi dan hanya boleh dikelola oleh peran admin
SENSITIVE_MODELS = {
    "users",
    "contacts",
    "admin-menus",
}
SENSITIVE_GET_MODELS = SENSITIVE_MODELS


def check_cms_write_access(model: str, admin: RecruitmentAdmin) -> None:
    """
    Validasi otorisasi tulis (POST/PUT/DELETE) model CMS:
    - Model sensitif (users, contacts, admin-menus) HANYA untuk role 'admin' / 'superadmin'.
    - Model konten (CMS_CONTENT_MODELS) diizinkan untuk role 'admin' dan 'marketing'.
    - Model di luar registri ditolak (403) jika bukan admin.
    """
    m = model.lower()
    role = (admin.role or "").lower()
    if m in SENSITIVE_MODELS:
        if role not in ("admin", "superadmin"):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Akses ditolak. Model '{model}' hanya dapat dikelola oleh Administrator.",
            )
    elif m in CMS_CONTENT_MODELS:
        if role not in ("admin", "superadmin", "marketing"):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Akses ditolak. Model '{model}' memerlukan wewenang admin atau marketing.",
            )
    else:
        if role not in ("admin", "superadmin"):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Akses ditolak.",
            )


def check_cms_model_access(
    model: str,
    request: Request,
    db: Session,
    credentials: Optional[HTTPAuthorizationCredentials] = None,
) -> Optional[RecruitmentAdmin]:
    """
    Periksa hak akses pembacaan model CMS:
    - Model dalam PUBLIC_GET_MODELS diizinkan tanpa autentikasi.
    - Model sensitif (users, contacts, admin-menus) dan model baru (default-deny) WAJIB autentikasi.
    - Model 'users' hanya diizinkan untuk peran 'admin'.
    """
    m = model.lower()
    if m in PUBLIC_GET_MODELS:
        return None

    # Default-deny: wajib autentikasi (X-Internal-Secret dengan X-Admin-Role / X-Admin-Id atau Bearer JWT)
    admin = get_current_admin(request=request, credentials=credentials, db=db)
    if m == "users" and admin.role not in ("admin", "superadmin"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Akses ditolak. Model 'users' hanya dapat diakses oleh peran admin.",
        )
    return admin


# --- DYNAMIC CMS CRUD FOR WEB PERUSAHAAN ---
@router.get("/{model}")
def get_cms_items(
    model: str,
    request: Request,
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security_scheme),
    db: Session = Depends(get_db),
    karir_db: Session = Depends(get_karir_db),
):
    """
    Retrieve dynamic CMS records for Web Company & Web Karir.
    Supports: settings, nav-menus, hero-sections, announcements, partners,
    features, services, products, blog-posts, testimonials, faqs, statistics,
    certifications, facilities, sustainability-reports, users.
    """
    crud = CMSModelRegistry.get_crud(model)
    if not crud:
        raise HTTPException(status_code=404, detail=f"Model CMS '{model}' tidak ditemukan.")

    # Proteksi akses model sensitif & default-deny untuk model baru
    check_cms_model_access(model, request=request, db=karir_db, credentials=credentials)

    # Bidirectional synchronization for users between web_perusahaan and web_karir
    if model == "users":
        # 1. Import any users from recruitment_admins (web_karir) to company users (web_perusahaan)
        try:
            rec_admins = karir_db.query(RecruitmentAdmin).all()
            existing_company_users = {u.email.lower(): u for u in db.query(User).all() if u.email}
            synced_to_company = False
            for ra in rec_admins:
                if ra.email and ra.email.lower() not in existing_company_users:
                    new_u = User(
                        username=ra.username,
                        email=ra.email.lower(),
                        name=ra.name or ra.username,
                        password=ra.password,
                        role=ra.role,
                        department=ra.department,
                        mfa_enabled=ra.is_mfa_enabled,
                        mfa_secret=ra.mfa_secret,
                        is_active=getattr(ra, "is_active", True),
                        portal_access=getattr(ra, "portal_access", "both") or "both",
                    )
                    db.add(new_u)
                    synced_to_company = True
                elif ra.email and ra.email.lower() in existing_company_users:
                    cu = existing_company_users[ra.email.lower()]
                    if getattr(cu, "username", None) and not ra.username:
                        ra.username = cu.username
                        karir_db.commit()
                    elif not getattr(cu, "username", None) and ra.username:
                        cu.username = ra.username
                        synced_to_company = True
                    if getattr(cu, "department", None) and not ra.department:
                        ra.department = cu.department
                        karir_db.commit()
                    elif not getattr(cu, "department", None) and ra.department:
                        cu.department = ra.department
                        synced_to_company = True
                    # sync is_active/portal_access
                    try:
                        if hasattr(cu, "is_active") and hasattr(ra, "is_active"):
                            if cu.is_active != ra.is_active:
                                cu.is_active = ra.is_active
                                synced_to_company = True
                        if hasattr(cu, "portal_access") and hasattr(ra, "portal_access"):
                            if (cu.portal_access or "both") != (ra.portal_access or "both"):
                                cu.portal_access = ra.portal_access
                                synced_to_company = True
                    except Exception:
                        pass
            if synced_to_company:
                db.commit()
        except Exception:
            db.rollback()

        # 2. Sync company users (admin/hr/user_dept) to recruitment_admins if missing
        try:
            existing_rec_emails = {ra.email.lower(): ra for ra in karir_db.query(RecruitmentAdmin).all() if ra.email}
            company_users = db.query(User).all()
            synced_to_rec = False
            for cu in company_users:
                if cu.email and cu.email.lower() not in existing_rec_emails and cu.role in ["admin", "hr", "user_dept"]:
                    base_username = getattr(cu, "username", None) or cu.email.split("@")[0]
                    cand_username = base_username
                    counter = 1
                    while karir_db.query(RecruitmentAdmin).filter(RecruitmentAdmin.username.ilike(cand_username)).first():
                        cand_username = f"{base_username}{counter}"
                        counter += 1

                    dept_default = {
                        "hr": "Human Capital",
                        "user_dept": "Engineering",
                        "admin": "IT & Systems",
                    }.get(cu.role, "General Management")
                    new_ra = RecruitmentAdmin(
                        username=cand_username,
                        email=cu.email.lower(),
                        name=cu.name,
                        password=cu.password,
                        role=cu.role,
                        department=getattr(cu, "department", None) or dept_default,
                        is_mfa_enabled=cu.mfa_enabled,
                        mfa_secret=cu.mfa_secret,
                        is_active=getattr(cu, "is_active", True),
                        portal_access=getattr(cu, "portal_access", "both") or "both",
                    )
                    karir_db.add(new_ra)
                    synced_to_rec = True
            if synced_to_rec:
                karir_db.commit()
        except Exception:
            karir_db.rollback()

    order_col = None
    if hasattr(crud.model, "sort_order"):
        order_col = crud.model.sort_order.asc()
    elif hasattr(crud.model, "id"):
        order_col = crud.model.id.asc() if model == "users" else crud.model.id.desc()

    if model == "nav-menus":
        try:
            from sqlalchemy import text
            db.execute(text("ALTER TABLE nav_menus ADD COLUMN IF NOT EXISTS is_maintenance BOOLEAN DEFAULT FALSE;"))
            db.commit()
        except Exception:
            db.rollback()

    try:
        items = crud.get_multi(db, limit=300, order_by=order_col)
    except Exception as exc:
        db.rollback()
        if model == "nav-menus":
            from sqlalchemy import text
            try:
                db.execute(text("ALTER TABLE nav_menus ADD COLUMN IF NOT EXISTS is_maintenance BOOLEAN DEFAULT FALSE;"))
                db.commit()
                items = crud.get_multi(db, limit=300, order_by=order_col)
            except Exception:
                db.rollback()
                # Direct fallback query excluding is_maintenance if DB schema has issues
                rows = db.execute(text("SELECT id, title, url, location, section, sort_order, is_active, parent_id, created_at, updated_at FROM nav_menus ORDER BY sort_order ASC")).fetchall()
                results = []
                for r in rows:
                    row_dict = dict(r._mapping)
                    row_dict["is_maintenance"] = False
                    results.append(row_dict)
                return ApiResponse(data=results)
        else:
            raise exc

    # Map of rec_admins by email for enrichment
    rec_admin_map = {}
    if model == "users":
        try:
            rec_admin_map = {ra.email.lower(): ra for ra in karir_db.query(RecruitmentAdmin).all() if ra.email}
        except Exception:
            pass

    results = [serialize_cms_record(model, item, rec_admin_map) for item in items]
    return ApiResponse(data=results)


@router.get("/{model}/{id}")
def get_cms_item_by_id(
    model: str,
    id: int,
    request: Request,
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security_scheme),
    db: Session = Depends(get_db),
    karir_db: Session = Depends(get_karir_db),
):
    """Retrieve single CMS record by ID."""
    crud = CMSModelRegistry.get_crud(model)
    if not crud:
        raise HTTPException(status_code=404, detail=f"Model CMS '{model}' tidak ditemukan.")

    check_cms_model_access(model, request=request, db=karir_db, credentials=credentials)

    item = crud.get(db, id)
    if not item:
        raise HTTPException(status_code=404, detail=f"Data {model} dengan ID {id} tidak ditemukan.")

    rec_admin_map = {}
    if model.lower() == "users":
        try:
            rec_admin_map = {ra.email.lower(): ra for ra in karir_db.query(RecruitmentAdmin).all() if ra.email}
        except Exception:
            pass

    item_dict = serialize_cms_record(model, item, rec_admin_map)
    return ApiResponse(data=item_dict)


@router.post("/{model}", status_code=status.HTTP_201_CREATED)
def create_cms_item(
    model: str,
    payload: Dict[str, Any],
    db: Session = Depends(get_db),
    karir_db: Session = Depends(get_karir_db),
    current_admin: RecruitmentAdmin = Depends(get_current_admin),
):
    """Create dynamic CMS record (Admin or Marketing depending on model)."""
    check_cms_write_access(model, current_admin)
    crud = CMSModelRegistry.get_crud(model)
    if not crud:
        raise HTTPException(status_code=404, detail=f"Model CMS '{model}' tidak ditemukan.")

    # Handle special case: settings batch update
    if model == "settings":
        if "settings" in payload and isinstance(payload["settings"], dict):
            for k, v in payload["settings"].items():
                setting_obj = db.query(SiteSetting).filter(SiteSetting.key == k).first()
                if setting_obj:
                    setting_obj.value = str(v)
                else:
                    db.add(SiteSetting(key=k, value=str(v)))
            db.commit()
            return ApiResponse(message="Pengaturan situs berhasil diperbarui.")

    # Normalize camelCase to snake_case
    normalized_data: Dict[str, Any] = {}
    for k, v in payload.items():
        snake_k = camel_to_snake(k)
        normalized_data[snake_k] = v

    # User special handling: hash password & duplicate check
    if model == "users":
        # Handle action == 'reset_mfa'
        if normalized_data.get("action") == "reset_mfa":
            user_id = int(normalized_data.get("user_id") or payload.get("userId") or 0)
            if not user_id:
                raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="User ID wajib diisi.")

            target_email = None
            user_name = "Pengguna"

            # 1. Reset in User (web_perusahaan)
            comp_user = db.query(User).filter(User.id == user_id).first()
            if comp_user:
                comp_user.mfa_enabled = False
                comp_user.mfa_secret = None
                comp_user.backup_codes = None
                db.commit()
                target_email = comp_user.email
                user_name = comp_user.name
            else:
                rec_user = karir_db.query(RecruitmentAdmin).filter(RecruitmentAdmin.id == user_id).first()
                if not rec_user:
                    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Akun pengguna tidak ditemukan.")
                rec_user.is_mfa_enabled = False
                rec_user.mfa_secret = None
                karir_db.commit()
                target_email = rec_user.email
                user_name = rec_user.name

            # 2. Sync to other database
            if target_email:
                ra = karir_db.query(RecruitmentAdmin).filter(RecruitmentAdmin.email.ilike(target_email)).first()
                if ra:
                    ra.is_mfa_enabled = False
                    ra.mfa_secret = None
                    karir_db.commit()
                cu = db.query(User).filter(User.email.ilike(target_email)).first()
                if cu:
                    cu.mfa_enabled = False
                    cu.mfa_secret = None
                    cu.backup_codes = None
                    db.commit()

            return ApiResponse(message=f"MFA Google Authenticator untuk akun {user_name} berhasil direset.")

        user_email = (normalized_data.get("email") or "").strip().lower()
        if not user_email:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Email wajib diisi.")

        pwd = normalized_data.get("password")
        if pwd is not None:
            pwd_str = str(pwd).strip()
            if pwd_str.startswith("$2b$") or pwd_str.startswith("$2a$"):
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Password harus berupa teks polos, hash password tidak diperkenankan.",
                )
            if len(pwd_str) < 12:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Kata sandi minimal terdiri dari 12 karakter.",
                )
            normalized_data["password"] = get_password_hash(pwd_str)

        # Check duplicate in Company Profile DB
        existing_user = db.query(User).filter(User.email.ilike(user_email)).first()
        if existing_user:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Email '{user_email}' sudah terdaftar pada pengguna lain. Gunakan alamat email lain.",
            )

        # Set username
        desired_username = (normalized_data.get("username") or user_email.split("@")[0]).strip()
        normalized_data["username"] = desired_username

        # Set department
        dept_default = {
            "hr": "Human Capital",
            "user_dept": "Engineering",
            "admin": "IT & Systems",
            "marketing": "Marketing",
        }.get(normalized_data.get("role"), "General Management")
        normalized_data["department"] = (normalized_data.get("department") or dept_default).strip()

        # Defaults for new fields
        if not normalized_data.get("is_active") and "is_active" not in normalized_data:
            normalized_data["is_active"] = True
        # validate portal_access
        pa = str(normalized_data.get("portal_access") or "both").lower().strip()
        if pa not in ("perusahaan","karir","both"):
            pa = "both"
        normalized_data["portal_access"] = pa
        if "backup_codes" in normalized_data and not isinstance(normalized_data["backup_codes"], str):
            normalized_data["backup_codes"] = json.dumps(normalized_data["backup_codes"])

    clean_data = {k: v for k, v in normalized_data.items() if hasattr(crud.model, k) and k not in ["id", "created_at", "updated_at"]}
    
    try:
        new_item = crud.create(db, obj_in=clean_data)
    except Exception as exc:
        db.rollback()
        err_str = str(exc)
        if "unique" in err_str.lower() or "duplicate" in err_str.lower():
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Data yang Anda masukkan sudah ada di sistem (duplikat). Periksa kembali email atau data unik lainnya.",
            )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Gagal menyimpan data: {err_str[:150]}",
        )

    # If new user has an admin/hr/user_dept role, also sync to Career Portal (with is_active + portal_access)
    if model == "users" and normalized_data.get("role") in ["admin", "hr", "user_dept"]:
        try:
            email_val = normalized_data.get("email")
            existing_rec = karir_db.query(RecruitmentAdmin).filter(RecruitmentAdmin.email.ilike(email_val)).first()
            dept_val = normalized_data.get("department") or {
                "hr": "Human Capital",
                "user_dept": "Engineering",
                "admin": "IT & Systems",
            }.get(normalized_data.get("role"), "General Management")

            if not existing_rec:
                base_username = (normalized_data.get("username") or email_val.split("@")[0]).strip()
                username = base_username
                counter = 1
                while karir_db.query(RecruitmentAdmin).filter(RecruitmentAdmin.username.ilike(username)).first():
                    username = f"{base_username}{counter}"
                    counter += 1
                new_rec = RecruitmentAdmin(
                    username=username,
                    name=normalized_data.get("name", username),
                    email=email_val,
                    password=normalized_data.get("password"),
                    role=normalized_data.get("role"),
                    department=dept_val,
                    is_mfa_enabled=bool(normalized_data.get("mfa_enabled", False)),
                    is_active=bool(normalized_data.get("is_active", True)),
                    portal_access=str(normalized_data.get("portal_access", "both")),
                )
                karir_db.add(new_rec)
                karir_db.commit()
            else:
                if normalized_data.get("username"):
                    existing_rec.username = normalized_data["username"].strip()
                if normalized_data.get("department"):
                    existing_rec.department = normalized_data["department"].strip()
                existing_rec.name = normalized_data.get("name", existing_rec.name)
                existing_rec.role = normalized_data.get("role", existing_rec.role)
                try:
                    existing_rec.is_active = bool(normalized_data.get("is_active", existing_rec.is_active))
                    existing_rec.portal_access = str(normalized_data.get("portal_access", getattr(existing_rec, "portal_access", "both") or "both"))
                except Exception:
                    pass
                karir_db.commit()
        except Exception:
            karir_db.rollback()

    item_dict = serialize_cms_record(model, new_item)
    return ApiResponse(data=item_dict, message=f"Data {model} berhasil ditambahkan.")


@router.put("/{model}/{id}")
def update_cms_item(
    model: str,
    id: int,
    payload: Dict[str, Any],
    db: Session = Depends(get_db),
    karir_db: Session = Depends(get_karir_db),
    current_admin: RecruitmentAdmin = Depends(get_current_admin),
):
    """Update dynamic CMS record (Admin or Marketing depending on model)."""
    check_cms_write_access(model, current_admin)
    crud = CMSModelRegistry.get_crud(model)
    if not crud:
        raise HTTPException(status_code=404, detail=f"Model CMS '{model}' tidak ditemukan.")

    item = crud.get(db, id)
    if not item:
        raise HTTPException(status_code=404, detail=f"Data {model} dengan ID {id} tidak ditemukan.")

    # Normalize camelCase to snake_case
    normalized_data: Dict[str, Any] = {}
    for k, v in payload.items():
        snake_k = camel_to_snake(k)
        normalized_data[snake_k] = v

    # User special handling: hash password and sync
    if model == "users":
        old_email = getattr(item, "email", None)
        pwd = normalized_data.get("password") or normalized_data.get("new_password")
        if pwd and str(pwd).strip():
            pwd_str = str(pwd).strip()
            if pwd_str.startswith("$2b$") or pwd_str.startswith("$2a$"):
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Password harus berupa teks polos, hash password tidak diperkenankan.",
                )
            if len(pwd_str) < 12:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Kata sandi minimal terdiri dari 12 karakter.",
                )
            normalized_data["password"] = get_password_hash(pwd_str)

        if "backup_codes" in normalized_data and not isinstance(normalized_data["backup_codes"], str):
            normalized_data["backup_codes"] = json.dumps(normalized_data["backup_codes"])

        new_username = (normalized_data.get("username") or "").strip()
        new_dept = (normalized_data.get("department") or "").strip()
        if new_username:
            normalized_data["username"] = new_username
        if new_dept:
            normalized_data["department"] = new_dept

        # Sync to recruitment_admins if matched
        try:
            rec_admin = None
            if old_email:
                rec_admin = karir_db.query(RecruitmentAdmin).filter(RecruitmentAdmin.email.ilike(old_email)).first()
            if not rec_admin and "email" in normalized_data:
                rec_admin = karir_db.query(RecruitmentAdmin).filter(RecruitmentAdmin.email.ilike(normalized_data["email"])).first()
            if not rec_admin and getattr(item, "username", None):
                rec_admin = karir_db.query(RecruitmentAdmin).filter(RecruitmentAdmin.username.ilike(getattr(item, "username"))).first()

            if rec_admin:
                if new_username:
                    other_u = karir_db.query(RecruitmentAdmin).filter(
                        (RecruitmentAdmin.username.ilike(new_username)) & (RecruitmentAdmin.id != rec_admin.id)
                    ).first()
                    if not other_u:
                        rec_admin.username = new_username
                if "name" in normalized_data and normalized_data["name"]:
                    rec_admin.name = normalized_data["name"]
                if "email" in normalized_data and normalized_data["email"]:
                    rec_admin.email = normalized_data["email"].strip().lower()
                if "role" in normalized_data and normalized_data["role"]:
                    rec_admin.role = normalized_data["role"]
                if new_dept:
                    rec_admin.department = new_dept
                if "password" in normalized_data and normalized_data["password"]:
                    rec_admin.password = normalized_data["password"]
                # Sync is_active & portal_access
                if "is_active" in normalized_data:
                    rec_admin.is_active = bool(normalized_data["is_active"])
                if "portal_access" in normalized_data and normalized_data["portal_access"]:
                    pa2 = str(normalized_data["portal_access"]).lower().strip()
                    if pa2 in ("perusahaan","karir","both"):
                        rec_admin.portal_access = pa2
                karir_db.commit()
            else:
                target_role = normalized_data.get("role", getattr(item, "role", "hr"))
                if target_role in ["admin", "hr", "user_dept"]:
                    target_email = (normalized_data.get("email") or old_email or "").strip().lower()
                    base_u = new_username or target_email.split("@")[0]
                    u_cand = base_u
                    cnt = 1
                    while karir_db.query(RecruitmentAdmin).filter(RecruitmentAdmin.username.ilike(u_cand)).first():
                        u_cand = f"{base_u}{cnt}"
                        cnt += 1
                    new_ra = RecruitmentAdmin(
                        username=u_cand,
                        name=normalized_data.get("name", getattr(item, "name", "")),
                        email=target_email,
                        password=normalized_data.get("password", getattr(item, "password", "")),
                        role=target_role,
                        department=new_dept or "Human Capital",
                        is_mfa_enabled=getattr(item, "mfa_enabled", False),
                        mfa_secret=getattr(item, "mfa_secret", None),
                        is_active=bool(normalized_data.get("is_active", True)),
                        portal_access=str(normalized_data.get("portal_access", "both")),
                    )
                    karir_db.add(new_ra)
                    karir_db.commit()
        except Exception:
            karir_db.rollback()

    clean_data = {k: v for k, v in normalized_data.items() if hasattr(crud.model, k) and k not in ["id", "created_at", "updated_at"]}
    updated = crud.update(db, db_obj=item, obj_in=clean_data)

    item_dict = serialize_cms_record(model, updated)
    return ApiResponse(data=item_dict, message=f"Data {model} berhasil diperbarui.")


@router.delete("/{model}/{id}", response_model=StatusResponse)
def delete_cms_item(
    model: str,
    id: int,
    db: Session = Depends(get_db),
    karir_db: Session = Depends(get_karir_db),
    current_admin: RecruitmentAdmin = Depends(get_current_admin),
):
    """Delete dynamic CMS record (Admin or Marketing depending on model)."""
    check_cms_write_access(model, current_admin)
    crud = CMSModelRegistry.get_crud(model)
    if not crud:
        raise HTTPException(status_code=404, detail=f"Model CMS '{model}' tidak ditemukan.")

    item = crud.get(db, id)
    if not item:
        raise HTTPException(status_code=404, detail=f"Data {model} tidak ditemukan.")

    if model == "users" and hasattr(item, "email") and item.email:
        try:
            karir_db.query(RecruitmentAdmin).filter(RecruitmentAdmin.email.ilike(item.email)).delete()
            karir_db.commit()
        except Exception:
            karir_db.rollback()

    crud.remove(db, id=id)
    return StatusResponse(message=f"Data {model} berhasil dihapus.")
