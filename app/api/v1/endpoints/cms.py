from typing import Any, Dict, List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.crud.crud_cms import CMSModelRegistry, crud_contact
from app.models.cms import SiteSetting
from app.schemas.cms import ContactSubmissionCreate, ContactSubmissionResponse
from app.schemas.common import ApiResponse, StatusResponse
from app.api.deps import get_current_admin, RoleChecker
from app.core.middleware import limiter

router = APIRouter()


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
    certifications, facilities.
    """
    crud = CMSModelRegistry.get_crud(model)
    if not crud:
        raise HTTPException(status_code=404, detail=f"Model CMS '{model}' tidak ditemukan.")

    # Apply ordering by sort_order or id
    order_col = None
    if hasattr(crud.model, "sort_order"):
        order_col = crud.model.sort_order.asc()
    elif hasattr(crud.model, "id"):
        order_col = crud.model.id.desc()

    items = crud.get_multi(db, limit=300, order_by=order_col)
    
    # Return as list of dictionaries
    results = []
    for item in items:
        d = {c.name: getattr(item, c.name) for c in item.__table__.columns}
        results.append(d)

    return ApiResponse(data=results)


@router.post("/{model}", status_code=status.HTTP_201_CREATED)
def create_cms_item(
    model: str,
    payload: Dict[str, Any],
    db: Session = Depends(get_db),
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

    # Clean non-model fields
    clean_data = {k: v for k, v in payload.items() if hasattr(crud.model, k) and k not in ["id", "created_at", "updated_at"]}
    new_item = crud.create(db, obj_in=clean_data)

    item_dict = {c.name: getattr(new_item, c.name) for c in new_item.__table__.columns}
    return ApiResponse(data=item_dict, message=f"Data {model} berhasil ditambahkan.")


@router.put("/{model}/{id}")
def update_cms_item(
    model: str,
    id: int,
    payload: Dict[str, Any],
    db: Session = Depends(get_db),
    _admin=Depends(RoleChecker(["admin"])),
):
    """Update dynamic CMS record (Admin only)."""
    crud = CMSModelRegistry.get_crud(model)
    if not crud:
        raise HTTPException(status_code=404, detail=f"Model CMS '{model}' tidak ditemukan.")

    item = crud.get(db, id)
    if not item:
        raise HTTPException(status_code=404, detail=f"Data {model} dengan ID {id} tidak ditemukan.")

    clean_data = {k: v for k, v in payload.items() if hasattr(crud.model, k) and k not in ["id", "created_at", "updated_at"]}
    updated = crud.update(db, db_obj=item, obj_in=clean_data)

    item_dict = {c.name: getattr(updated, c.name) for c in updated.__table__.columns}
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
