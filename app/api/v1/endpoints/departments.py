"""FastAPI endpoint: Department & Section CRUD."""
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models.department import Department, Section
from app.schemas.department import (
    DepartmentCreate, DepartmentUpdate, DepartmentResponse, DepartmentSimple,
    SectionCreate, SectionUpdate, SectionResponse,
)
from app.schemas.common import ApiResponse, StatusResponse
from app.api.deps import RoleChecker

router = APIRouter()


# ────────────────────────────────────────────────
# DEPARTMENT endpoints
# ────────────────────────────────────────────────

@router.get("", response_model=ApiResponse[List[DepartmentResponse]])
def list_departments(
    active_only: bool = Query(False),
    db: Session = Depends(get_db),
):
    """List all departments with their sections. Public (used in job-apply dropdown)."""
    q = db.query(Department)
    if active_only:
        q = q.filter(Department.is_active == True)
    depts = q.order_by(Department.sort_order, Department.name).all()
    return ApiResponse(data=[DepartmentResponse.model_validate(d) for d in depts])


@router.get("/simple", response_model=ApiResponse[List[DepartmentSimple]])
def list_departments_simple(
    active_only: bool = Query(True),
    db: Session = Depends(get_db),
):
    """Lightweight list of departments for dropdowns."""
    q = db.query(Department)
    if active_only:
        q = q.filter(Department.is_active == True)
    depts = q.order_by(Department.sort_order, Department.name).all()
    return ApiResponse(data=[DepartmentSimple.model_validate(d) for d in depts])


@router.get("/{dept_id}", response_model=ApiResponse[DepartmentResponse])
def get_department(dept_id: int, db: Session = Depends(get_db)):
    dept = db.query(Department).filter(Department.id == dept_id).first()
    if not dept:
        raise HTTPException(status_code=404, detail="Departemen tidak ditemukan.")
    return ApiResponse(data=DepartmentResponse.model_validate(dept))


@router.post("", response_model=ApiResponse[DepartmentResponse], status_code=status.HTTP_201_CREATED)
def create_department(
    payload: DepartmentCreate,
    db: Session = Depends(get_db),
    _admin=Depends(RoleChecker(["hr", "admin"])),
):
    existing = db.query(Department).filter(Department.name == payload.name).first()
    if existing:
        raise HTTPException(status_code=400, detail="Nama departemen sudah ada.")
    dept = Department(**payload.model_dump())
    db.add(dept)
    db.commit()
    db.refresh(dept)
    return ApiResponse(data=DepartmentResponse.model_validate(dept), message="Departemen berhasil ditambahkan.")


@router.put("/{dept_id}", response_model=ApiResponse[DepartmentResponse])
def update_department(
    dept_id: int,
    payload: DepartmentUpdate,
    db: Session = Depends(get_db),
    _admin=Depends(RoleChecker(["hr", "admin"])),
):
    dept = db.query(Department).filter(Department.id == dept_id).first()
    if not dept:
        raise HTTPException(status_code=404, detail="Departemen tidak ditemukan.")
    if payload.name and payload.name != dept.name:
        dup = db.query(Department).filter(Department.name == payload.name, Department.id != dept_id).first()
        if dup:
            raise HTTPException(status_code=400, detail="Nama departemen sudah digunakan.")
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(dept, field, value)
    db.commit()
    db.refresh(dept)
    return ApiResponse(data=DepartmentResponse.model_validate(dept), message="Departemen berhasil diperbarui.")


@router.delete("/{dept_id}", response_model=StatusResponse)
def delete_department(
    dept_id: int,
    db: Session = Depends(get_db),
    _admin=Depends(RoleChecker(["hr", "admin"])),
):
    dept = db.query(Department).filter(Department.id == dept_id).first()
    if not dept:
        raise HTTPException(status_code=404, detail="Departemen tidak ditemukan.")
    db.delete(dept)
    db.commit()
    return StatusResponse(message=f"Departemen '{dept.name}' berhasil dihapus.")


# ────────────────────────────────────────────────
# SECTION endpoints
# ────────────────────────────────────────────────

@router.get("/{dept_id}/sections", response_model=ApiResponse[List[SectionResponse]])
def list_sections(dept_id: int, db: Session = Depends(get_db)):
    """List sections for a specific department."""
    dept = db.query(Department).filter(Department.id == dept_id).first()
    if not dept:
        raise HTTPException(status_code=404, detail="Departemen tidak ditemukan.")
    sections = db.query(Section).filter(Section.department_id == dept_id).order_by(Section.sort_order, Section.name).all()
    return ApiResponse(data=[SectionResponse.model_validate(s) for s in sections])


@router.post("/{dept_id}/sections", response_model=ApiResponse[SectionResponse], status_code=status.HTTP_201_CREATED)
def create_section(
    dept_id: int,
    payload: SectionCreate,
    db: Session = Depends(get_db),
    _admin=Depends(RoleChecker(["hr", "admin"])),
):
    dept = db.query(Department).filter(Department.id == dept_id).first()
    if not dept:
        raise HTTPException(status_code=404, detail="Departemen tidak ditemukan.")
    dup = db.query(Section).filter(Section.department_id == dept_id, Section.name == payload.name).first()
    if dup:
        raise HTTPException(status_code=400, detail="Nama section sudah ada di departemen ini.")
    section = Section(department_id=dept_id, **{k: v for k, v in payload.model_dump().items() if k != "department_id"})
    db.add(section)
    db.commit()
    db.refresh(section)
    return ApiResponse(data=SectionResponse.model_validate(section), message="Section berhasil ditambahkan.")


@router.put("/{dept_id}/sections/{section_id}", response_model=ApiResponse[SectionResponse])
def update_section(
    dept_id: int,
    section_id: int,
    payload: SectionUpdate,
    db: Session = Depends(get_db),
    _admin=Depends(RoleChecker(["hr", "admin"])),
):
    section = db.query(Section).filter(Section.id == section_id, Section.department_id == dept_id).first()
    if not section:
        raise HTTPException(status_code=404, detail="Section tidak ditemukan.")
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(section, field, value)
    db.commit()
    db.refresh(section)
    return ApiResponse(data=SectionResponse.model_validate(section), message="Section berhasil diperbarui.")


@router.delete("/{dept_id}/sections/{section_id}", response_model=StatusResponse)
def delete_section(
    dept_id: int,
    section_id: int,
    db: Session = Depends(get_db),
    _admin=Depends(RoleChecker(["hr", "admin"])),
):
    section = db.query(Section).filter(Section.id == section_id, Section.department_id == dept_id).first()
    if not section:
        raise HTTPException(status_code=404, detail="Section tidak ditemukan.")
    db.delete(section)
    db.commit()
    return StatusResponse(message=f"Section '{section.name}' berhasil dihapus.")
