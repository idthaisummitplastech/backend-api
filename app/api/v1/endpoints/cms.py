import json
import re
from typing import Any, Dict, List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy.orm import Session

from app.db.session import get_db_company as get_db, get_db as get_karir_db
from app.crud.crud_cms import CMSModelRegistry, crud_contact
from app.models.cms import (
    SiteSetting,
    NavMenu,
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
from app.api.deps import get_current_admin, RoleChecker
from app.core.middleware import limiter
from app.core.security import get_password_hash, verify_password

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
    _admin=Depends(RoleChecker(["admin"])),
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


# --- DASHBOARD STATS FOR WEB PERUSAHAAN ---
@router.get("/dashboard-stats")
def get_dashboard_stats(
    db: Session = Depends(get_db),
):
    """Retrieve summarized statistics for CMS Admin Dashboard."""
    product_count = db.query(Product).count()
    cert_count = db.query(Certification).count()
    facility_count = db.query(Facility).count()
    service_count = db.query(Service).count()
    blog_count = db.query(BlogPost).count()
    report_count = db.query(SustainabilityReport).count()
    contact_count = db.query(ContactSubmission).count()
    unread_contacts = db.query(ContactSubmission).filter(ContactSubmission.is_read == False).count()
    user_count = db.query(User).count()
    recent_contacts_raw = (
        db.query(ContactSubmission)
        .order_by(ContactSubmission.created_at.desc())
        .limit(5)
        .all()
    )
    recent_contacts = []
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
    user_id: int = Query(...),
    db: Session = Depends(get_db),
):
    """Fetch CMS user profile."""
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
    db: Session = Depends(get_db),
    karir_db: Session = Depends(get_karir_db),
):
    """Update CMS user profile, password, or MFA."""
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
        if len(new_password) < 6:
            raise HTTPException(status_code=400, detail="Kata sandi baru minimal 6 karakter.")

        hashed = get_password_hash(new_password)
        user.password = hashed
        db.commit()

        # Sync to recruitment_admins if exists
        rec_admin = karir_db.query(RecruitmentAdmin).filter(RecruitmentAdmin.email == user.email).first()
        if rec_admin:
            rec_admin.password = hashed
            karir_db.commit()

        return ApiResponse(message="Kata sandi berhasil diubah.")

    elif action == "toggle_mfa":
        enabled = payload.get("enabled")
        new_status = bool(enabled) if enabled is not None else not user.mfa_enabled
        user.mfa_enabled = new_status
        if payload.get("mfa_secret") or payload.get("mfaSecret"):
            user.mfa_secret = payload.get("mfa_secret") or payload.get("mfaSecret")
        if payload.get("backup_codes") or payload.get("backupCodes"):
            bc = payload.get("backup_codes") or payload.get("backupCodes")
            user.backup_codes = bc if isinstance(bc, str) else json.dumps(bc)
        db.commit()
        return ApiResponse(data={"mfa_enabled": new_status}, message="Status MFA berhasil diperbarui.")

    raise HTTPException(status_code=400, detail="Aksi tidak valid.")


# --- DYNAMIC CMS CRUD FOR WEB PERUSAHAAN ---
@router.get("/{model}")
def get_cms_items(
    model: str,
    db: Session = Depends(get_db),
):
    """
    Retrieve dynamic CMS records for Web Perusahaan.
    Supports: settings, nav-menus, hero-sections, announcements, partners,
    features, services, products, blog-posts, testimonials, faqs, statistics,
    certifications, facilities, sustainability-reports, users.
    """
    crud = CMSModelRegistry.get_crud(model)
    if not crud:
        raise HTTPException(status_code=404, detail=f"Model CMS '{model}' tidak ditemukan.")

    order_col = None
    if hasattr(crud.model, "sort_order"):
        order_col = crud.model.sort_order.asc()
    elif hasattr(crud.model, "id"):
        order_col = crud.model.id.asc() if model == "users" else crud.model.id.desc()

    items = crud.get_multi(db, limit=300, order_by=order_col)

    results = []
    for item in items:
        d = {c.name: getattr(item, c.name) for c in item.__table__.columns}
        # Hide raw passwords when querying users
        if model == "users" and "password" in d:
            d["password"] = "******"
        results.append(d)

    return ApiResponse(data=results)


@router.get("/{model}/{id}")
def get_cms_item_by_id(
    model: str,
    id: int,
    db: Session = Depends(get_db),
):
    """Retrieve single CMS record by ID."""
    crud = CMSModelRegistry.get_crud(model)
    if not crud:
        raise HTTPException(status_code=404, detail=f"Model CMS '{model}' tidak ditemukan.")

    item = crud.get(db, id)
    if not item:
        raise HTTPException(status_code=404, detail=f"Data {model} dengan ID {id} tidak ditemukan.")

    item_dict = {c.name: getattr(item, c.name) for c in item.__table__.columns}
    return ApiResponse(data=item_dict)


@router.post("/{model}", status_code=status.HTTP_201_CREATED)
def create_cms_item(
    model: str,
    payload: Dict[str, Any],
    db: Session = Depends(get_db),
    karir_db: Session = Depends(get_karir_db),
    _admin=Depends(RoleChecker(["admin"])),
):
    """Create dynamic CMS record (Admin only)."""
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
        user_email = (normalized_data.get("email") or "").strip().lower()
        if not user_email:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Email wajib diisi.")
        
        # Check duplicate in Company Profile DB
        existing_user = db.query(User).filter(User.email.ilike(user_email)).first()
        if existing_user:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Email '{user_email}' sudah terdaftar pada pengguna lain. Gunakan alamat email lain.",
            )

        pwd = normalized_data.get("password")
        if pwd and not str(pwd).startswith("$2b$"):
            normalized_data["password"] = get_password_hash(str(pwd))
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

    # If new user has an admin/hr/user_dept role, also sync to Career Portal
    if model == "users" and normalized_data.get("role") in ["admin", "hr", "user_dept"]:
        try:
            email_val = normalized_data.get("email")
            existing_rec = karir_db.query(RecruitmentAdmin).filter(RecruitmentAdmin.email.ilike(email_val)).first()
            if not existing_rec:
                base_username = email_val.split("@")[0]
                username = base_username
                counter = 1
                while karir_db.query(RecruitmentAdmin).filter(RecruitmentAdmin.username == username).first():
                    username = f"{base_username}{counter}"
                    counter += 1
                new_rec = RecruitmentAdmin(
                    username=username,
                    name=normalized_data.get("name", username),
                    email=email_val,
                    password=normalized_data.get("password"),
                    role=normalized_data.get("role"),
                    is_mfa_enabled=bool(normalized_data.get("mfa_enabled", False)),
                )
                karir_db.add(new_rec)
                karir_db.commit()
        except Exception:
            karir_db.rollback()

    item_dict = {c.name: getattr(new_item, c.name) for c in new_item.__table__.columns}
    if "password" in item_dict:
        item_dict["password"] = "******"

    return ApiResponse(data=item_dict, message=f"Data {model} berhasil ditambahkan.")


@router.put("/{model}/{id}")
def update_cms_item(
    model: str,
    id: int,
    payload: Dict[str, Any],
    db: Session = Depends(get_db),
    karir_db: Session = Depends(get_karir_db),
    _admin=Depends(RoleChecker(["admin"])),
):
    """Update dynamic CMS record (Admin only)."""
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
            if not str(pwd).startswith("$2b$"):
                normalized_data["password"] = get_password_hash(str(pwd).strip())
            else:
                normalized_data["password"] = str(pwd).strip()

        if "backup_codes" in normalized_data and not isinstance(normalized_data["backup_codes"], str):
            normalized_data["backup_codes"] = json.dumps(normalized_data["backup_codes"])

        # Sync to recruitment_admins if email matched
        if old_email:
            rec_admin = karir_db.query(RecruitmentAdmin).filter(RecruitmentAdmin.email == old_email).first()
            if rec_admin:
                if "name" in normalized_data:
                    rec_admin.name = normalized_data["name"]
                if "email" in normalized_data:
                    rec_admin.email = normalized_data["email"]
                if "role" in normalized_data:
                    rec_admin.role = normalized_data["role"]
                if "password" in normalized_data:
                    rec_admin.password = normalized_data["password"]
                karir_db.commit()

    clean_data = {k: v for k, v in normalized_data.items() if hasattr(crud.model, k) and k not in ["id", "created_at", "updated_at"]}
    updated = crud.update(db, db_obj=item, obj_in=clean_data)

    item_dict = {c.name: getattr(updated, c.name) for c in updated.__table__.columns}
    if "password" in item_dict:
        item_dict["password"] = "******"

    return ApiResponse(data=item_dict, message=f"Data {model} berhasil diperbarui.")


@router.delete("/{model}/{id}", response_model=StatusResponse)
def delete_cms_item(
    model: str,
    id: int,
    db: Session = Depends(get_db),
    _admin=Depends(RoleChecker(["admin"])),
):
    """Delete dynamic CMS record (Admin only)."""
    crud = CMSModelRegistry.get_crud(model)
    if not crud:
        raise HTTPException(status_code=404, detail=f"Model CMS '{model}' tidak ditemukan.")

    item = crud.get(db, id)
    if not item:
        raise HTTPException(status_code=404, detail=f"Data {model} tidak ditemukan.")

    crud.remove(db, id=id)
    return StatusResponse(message=f"Data {model} berhasil dihapus.")
