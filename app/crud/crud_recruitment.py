from typing import Any, Dict, List, Optional
from sqlalchemy.orm import Session, joinedload
from app.crud.base import CRUDBase
from app.models.recruitment import (
    JobPosting,
    Applicant,
    InterviewSchedule,
    TestQuestion,
    TestSubmission,
    KaryawanSementara,
    RecruitmentSetting,
)
from app.schemas.recruitment import (
    JobPostingCreate,
    JobPostingUpdate,
    ApplicantCreate,
    ApplicantUpdate,
    InterviewScheduleCreate,
)
from app.schemas.tests import TestQuestionCreate, TestQuestionUpdate
from app.core.security import get_password_hash, verify_password


class CRUDJob(CRUDBase[JobPosting, JobPostingCreate, JobPostingUpdate]):
    """Job Vacancies repository."""
    def get_open_jobs(self, db: Session) -> List[JobPosting]:
        return db.query(self.model).filter(self.model.is_open == True).order_by(self.model.created_at.desc()).all()


class CRUDApplicant(CRUDBase[Applicant, ApplicantCreate, ApplicantUpdate]):
    """Candidate applications repository."""

    def get_by_email(self, db: Session, email: str) -> Optional[Applicant]:
        return self.get_by_attribute(db, "email", email.strip().lower())

    def get_with_details(self, db: Session, applicant_id: int) -> Optional[Applicant]:
        return (
            db.query(self.model)
            .options(
                joinedload(self.model.job_posting),
                joinedload(self.model.interviews),
                joinedload(self.model.test_submissions),
                joinedload(self.model.karyawan_data),
            )
            .filter(self.model.id == applicant_id)
            .first()
        )

    def create(self, db: Session, *, obj_in: ApplicantCreate) -> Applicant:
        data = obj_in.model_dump()
        data["password"] = get_password_hash(data["password"])
        data["email"] = data["email"].strip().lower()
        return super().create(db, obj_in=data)

    def authenticate(self, db: Session, *, email: str, password: str) -> Optional[Applicant]:
        applicant = self.get_by_email(db, email)
        if not applicant or not verify_password(password, applicant.password):
            return None
        return applicant


class CRUDInterview(CRUDBase[InterviewSchedule, InterviewScheduleCreate, Any]):
    """Interview scheduling repository."""
    def get_by_applicant(self, db: Session, applicant_id: int) -> List[InterviewSchedule]:
        return db.query(self.model).filter(self.model.applicant_id == applicant_id).all()


class CRUDQuestion(CRUDBase[TestQuestion, TestQuestionCreate, TestQuestionUpdate]):
    """Exam questions bank repository."""
    def get_by_category(self, db: Session, category: str, department: Optional[str] = None) -> List[TestQuestion]:
        q = db.query(self.model).filter(self.model.category == category)
        if department and department.lower() != "general":
            q = q.filter((self.model.department == department) | (self.model.department == "General") | (self.model.department == None))
        return q.order_by(self.model.sort_order.asc(), self.model.id.asc()).all()


class CRUDSubmission(CRUDBase[TestSubmission, Any, Any]):
    """Applicant test answers and scores repository."""
    def get_by_applicant_and_type(self, db: Session, applicant_id: int, test_type: str) -> Optional[TestSubmission]:
        return (
            db.query(self.model)
            .filter(self.model.applicant_id == applicant_id, self.model.test_type == test_type)
            .first()
        )


class CRUDKaryawan(CRUDBase[KaryawanSementara, Any, Any]):
    """Pre-onboarding new employee repository."""
    def get_by_nik(self, db: Session, nik: str) -> Optional[KaryawanSementara]:
        return self.get_by_attribute(db, "nik_sementara", nik.strip().upper())


class CRUDSetting(CRUDBase[RecruitmentSetting, Any, Any]):
    """System and recruitment settings repository."""
    def get_value(self, db: Session, key: str, default: str = "") -> str:
        obj = self.get_by_attribute(db, "key", key)
        return obj.value if obj else default

    def set_value(self, db: Session, key: str, value: str) -> RecruitmentSetting:
        obj = self.get_by_attribute(db, "key", key)
        if obj:
            obj.value = value
            db.commit()
            db.refresh(obj)
            return obj
        else:
            return self.create(db, obj_in={"key": key, "value": value})


crud_job = CRUDJob(JobPosting)
crud_applicant = CRUDApplicant(Applicant)
crud_interview = CRUDInterview(InterviewSchedule)
crud_question = CRUDQuestion(TestQuestion)
crud_submission = CRUDSubmission(TestSubmission)
crud_karyawan = CRUDKaryawan(KaryawanSementara)
crud_setting = CRUDSetting(RecruitmentSetting)
