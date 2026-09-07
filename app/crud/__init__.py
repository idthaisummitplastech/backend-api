"""CRUD repositories package exporting all database access objects."""
from app.crud.base import CRUDBase
from app.crud.crud_auth import crud_admin, crud_user
from app.crud.crud_recruitment import (
    crud_job,
    crud_applicant,
    crud_interview,
    crud_question,
    crud_submission,
    crud_karyawan,
    crud_setting,
)
from app.crud.crud_cms import CMSModelRegistry, crud_contact

__all__ = [
    "CRUDBase",
    "crud_admin",
    "crud_user",
    "crud_job",
    "crud_applicant",
    "crud_interview",
    "crud_question",
    "crud_submission",
    "crud_karyawan",
    "crud_setting",
    "CMSModelRegistry",
    "crud_contact",
]
