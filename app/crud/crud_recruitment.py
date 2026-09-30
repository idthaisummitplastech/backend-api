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
    DataKaryawan,
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

    def get_multi_with_details(
        self,
        db: Session,
        *,
        skip: int = 0,
        limit: int = 300,
        order_by: Any = None,
        filters: Optional[Dict[str, Any]] = None,
    ) -> List[Applicant]:
        query = (
            db.query(self.model)
            .options(
                joinedload(self.model.job_posting),
                joinedload(self.model.interviews),
                joinedload(self.model.test_submissions),
                joinedload(self.model.karyawan_data),
            )
        )
        if filters:
            for key, val in filters.items():
                if hasattr(self.model, key) and val is not None:
                    query = query.filter(getattr(self.model, key) == val)
        if order_by is not None:
            query = query.order_by(order_by)
        elif hasattr(self.model, "id"):
            query = query.order_by(self.model.id.desc())
        return query.offset(skip).limit(limit).all()

    def get_with_details_by_identifier(self, db: Session, identifier: Any) -> Optional[Applicant]:
        query = (
            db.query(self.model)
            .options(
                joinedload(self.model.job_posting),
                joinedload(self.model.interviews),
                joinedload(self.model.test_submissions),
                joinedload(self.model.karyawan_data),
            )
        )
        id_str = str(identifier).strip()
        if id_str.isdigit():
            return query.filter(self.model.id == int(id_str)).first()
        return query.filter(self.model.email == id_str.lower()).first()

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


def is_dept_match(q_dept: Optional[str], target_dept: Optional[str]) -> bool:
    """Check if question department matches target department, taking into account aliases."""
    if not q_dept or not target_dept:
        return False
    qd = q_dept.strip().lower()
    td = target_dept.strip().lower()
    if qd == td:
        return True

    # IT aliases
    it_keywords = [
        "it",
        "information technology",
        "teknologi informasi",
        "it & systems",
        "it & enterprise system",
        "sistem informasi",
        "ti",
    ]
    qd_is_it = any(qd == k or f" {k} " in f" {qd} " or qd.startswith(k + " ") or qd.endswith(" " + k) for k in it_keywords)
    td_is_it = any(td == k or f" {k} " in f" {td} " or td.startswith(k + " ") or td.endswith(" " + k) for k in it_keywords)
    if qd_is_it and td_is_it:
        return True

    # Engineering aliases
    eng_keywords = ["engineering", "rekayasa", "teknik"]
    qd_is_eng = any(k in qd for k in eng_keywords)
    td_is_eng = any(k in td for k in eng_keywords)
    if qd_is_eng and td_is_eng:
        return True

    # Produksi aliases
    prod_keywords = ["produksi", "production", "manufaktur", "manufacturing"]
    if any(k in qd for k in prod_keywords) and any(k in td for k in prod_keywords):
        return True

    # Quality aliases
    qa_keywords = ["quality", "qa", "qc", "mutu"]
    if any(k in qd for k in qa_keywords) and any(k in td for k in qa_keywords):
        return True

    # HSE aliases
    hse_keywords = ["hse", "k3", "she", "safety"]
    if any(k in qd for k in hse_keywords) and any(k in td for k in hse_keywords):
        return True

    return qd in td or td in qd


class CRUDQuestion(CRUDBase[TestQuestion, TestQuestionCreate, TestQuestionUpdate]):
    """Exam questions bank repository."""
    def get_by_category(self, db: Session, category: str, department: Optional[str] = None) -> List[TestQuestion]:
        q = db.query(self.model).filter(self.model.category == category)
        if not department:
            return q.order_by(self.model.sort_order.asc(), self.model.id.asc()).all()

        dept_clean = department.strip().lower()
        if dept_clean in ["all", "semua departemen", "all departments", ""]:
            return q.order_by(self.model.sort_order.asc(), self.model.id.asc()).all()

        all_qs = q.order_by(self.model.sort_order.asc(), self.model.id.asc()).all()
        if dept_clean == "general":
            return [item for item in all_qs if (item.department or "").strip().lower() == "general"]

        return [item for item in all_qs if is_dept_match(item.department, department)]


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


class CRUDDataKaryawan(CRUDBase[DataKaryawan, Any, Any]):
    """Official Company Employee repository."""
    def get_by_employee_id(self, db: Session, employee_id: str) -> Optional[DataKaryawan]:
        return self.get_by_attribute(db, "employee_id", employee_id.strip())

    def get_by_applicant_id(self, db: Session, applicant_id: int) -> Optional[DataKaryawan]:
        return (
            db.query(self.model)
            .filter(self.model.applicant_id == applicant_id)
            .first()
        )

    def get_last_sequence(self, db: Session) -> int:
        """Get the highest employee sequence number in DB or from settings."""
        from sqlalchemy import func
        db_max = db.query(func.max(self.model.sequence_number)).scalar() or 0
        setting_val = crud_setting.get_value(db, "employee_last_sequence", "1529")
        try:
            setting_num = int(setting_val)
        except (ValueError, TypeError):
            setting_num = 1529
        return max(db_max, setting_num)

    def set_last_sequence(self, db: Session, sequence: int) -> int:
        crud_setting.set_value(db, "employee_last_sequence", str(sequence))
        return sequence

    def preview_next_employee_id(self, db: Session, join_date_val: Optional[Any] = None, custom_sequence: Optional[int] = None) -> Dict[str, Any]:
        """
        Calculates next employee ID format: {id}.{MM}.{YY}
        e.g., 1530.09.26
        """
        last_seq = self.get_last_sequence(db)
        next_seq = custom_sequence if custom_sequence is not None else (last_seq + 1)

        # Determine Month & Year from Join Date
        month_str = "09"
        year_str = "26"
        if join_date_val:
            if hasattr(join_date_val, 'month') and hasattr(join_date_val, 'year'):
                month_str = f"{join_date_val.month:02d}"
                year_str = f"{join_date_val.year % 100:02d}"
            elif isinstance(join_date_val, str):
                import re
                iso_match = re.search(r"(\d{4})-(\d{1,2})-(\d{1,2})", join_date_val)
                if iso_match:
                    year_full = int(iso_match.group(1))
                    month_int = int(iso_match.group(2))
                    month_str = f"{month_int:02d}"
                    year_str = f"{year_full % 100:02d}"
                else:
                    indo_months = {
                        "januari": 1, "februari": 2, "maret": 3, "april": 4, "mei": 5, "juni": 6,
                        "juli": 7, "agustus": 8, "september": 9, "oktober": 10, "november": 11, "desember": 12,
                    }
                    lower_val = join_date_val.lower()
                    found_m = None
                    for m_name, m_num in indo_months.items():
                        if m_name in lower_val:
                            found_m = m_num
                            break
                    if found_m:
                        month_str = f"{found_m:02d}"
                    year_match = re.search(r"\b(20\d{2})\b", join_date_val)
                    if year_match:
                        year_str = f"{int(year_match.group(1)) % 100:02d}"

        formatted_id = f"{next_seq}.{month_str}.{year_str}"
        return {
            "last_sequence": last_seq,
            "next_sequence": next_seq,
            "month": month_str,
            "year": year_str,
            "employee_id": formatted_id,
        }


crud_job = CRUDJob(JobPosting)
crud_applicant = CRUDApplicant(Applicant)
crud_interview = CRUDInterview(InterviewSchedule)
crud_question = CRUDQuestion(TestQuestion)
crud_submission = CRUDSubmission(TestSubmission)
crud_karyawan = CRUDKaryawan(KaryawanSementara)
crud_setting = CRUDSetting(RecruitmentSetting)
crud_data_karyawan = CRUDDataKaryawan(DataKaryawan)
