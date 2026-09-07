from datetime import datetime, timezone
import random
import string
from typing import Any, Dict, Optional
from sqlalchemy.orm import Session
from fastapi import HTTPException, status
from app.crud.crud_recruitment import (
    crud_applicant,
    crud_karyawan,
    crud_interview,
    crud_setting,
)
from app.models.auth import RecruitmentAdmin
from app.models.recruitment import Applicant, KaryawanSementara
from app.schemas.recruitment import AdvanceStageRequest
from app.services.email_service import email_service
from app.core.config import settings


class RecruitmentWorkflowService:
    """
    Core Recruitment ATS Workflow Engine implementing the 7 selection stages:
    1: Screening Administrasi (HR)
    2: Ujian Psikotes Online (HR)
    3: Ujian Teknis (User Dept)
    4: Interview HR (HR)
    5: Interview Teknis / User (User Dept)
    6: Medical Check-Up / MCU (HR)
    7: Offering Letter & Onboarding (HR)
    """

    HR_STAGES = [1, 2, 4, 6, 7]
    USER_DEPT_STAGES = [3, 5]

    def _generate_random_token(self, length: int = 8) -> str:
        """Generate high-entropy alphanumeric session token."""
        return "".join(random.choices(string.ascii_uppercase + string.digits, k=length))

    def _generate_nik_sementara(self, db: Session, department: str) -> str:
        """Generate standardized temporary employee NIK e.g. ITSP-2026-IT-001."""
        year = datetime.now().year
        dept_code = "".join([c for c in department if c.isalnum()])[:4].upper() or "GEN"
        prefix = f"ITSP-{year}-{dept_code}-"
        
        # Find highest count
        count = crud_karyawan.count(db) + 1
        return f"{prefix}{count:03d}"

    def validate_rbac_stage(self, admin: RecruitmentAdmin, applicant: Applicant) -> None:
        """Enforce strict departmental and role-based stage access control."""
        if admin.role == "admin":
            return  # Superadmin bypass

        if admin.role == "user_dept":
            if applicant.current_stage not in self.USER_DEPT_STAGES:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail=f"Akses Ditolak: User Departemen hanya berhak mengevaluasi Tahap 3 (Ujian Teknis) & Tahap 5 (Interview User). Tahap {applicant.current_stage} adalah wewenang HR.",
                )

            # Department scope check
            user_dept = (admin.department or "").strip().lower()
            job_dept = (applicant.job_posting.department or "").strip().lower() if applicant.job_posting else ""
            if user_dept and job_dept and (user_dept not in job_dept and job_dept not in user_dept):
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail=f"Akses Ditolak: Anda login untuk divisi '{admin.department}'. Pelamar ini melamar untuk divisi '{job_dept}'.",
                )

        elif admin.role == "hr":
            if applicant.current_stage not in self.HR_STAGES:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail=f"Akses Ditolak: Tahap {applicant.current_stage} merupakan wewenang evaluasi teknis Tim User Departemen.",
                )

    def process_stage_action(
        self,
        db: Session,
        admin: RecruitmentAdmin,
        payload: AdvanceStageRequest,
    ) -> Dict[str, Any]:
        """Execute stage progression, rejection, or scheduling with email notifications."""
        applicant = crud_applicant.get_with_details(db, payload.applicant_id)
        if not applicant:
            raise HTTPException(status_code=404, detail="Pelamar tidak ditemukan.")

        # Validate RBAC permissions
        self.validate_rbac_stage(admin, applicant)

        action = payload.action.lower()
        now = datetime.now(timezone.utc)
        job_title = applicant.job_posting.title if applicant.job_posting else "Posisi Terkait"

        # 1. REJECTION
        if action == "reject":
            applicant.stage_status = "failed"
            applicant.failed_at_stage = applicant.current_stage
            applicant.rejection_reason = payload.rejection_reason or payload.notes or "Kualifikasi belum sesuai kriteria yang dibutuhkan."
            db.commit()

            # Email notification
            email_service.send_rejection_notice(
                to_email=applicant.email,
                name=applicant.full_name,
                position=job_title,
                reason=applicant.rejection_reason,
            )
            return {"success": True, "message": "Pelamar dinyatakan tidak lolos seleksi.", "applicant": applicant}

        # 2. UPDATE TOKEN / TEST SESSION
        if action in ["update_test_session", "update_token"]:
            if applicant.current_stage == 2:
                if payload.token:
                    applicant.psikotes_token = payload.token.strip().upper()
                if payload.scheduled_at:
                    applicant.psikotes_scheduled_at = payload.scheduled_at
                if payload.location:
                    applicant.psikotes_location = payload.location
            elif applicant.current_stage == 3:
                if payload.token:
                    applicant.user_test_token = payload.token.strip().upper()
                if payload.scheduled_at:
                    applicant.user_test_scheduled_at = payload.scheduled_at
                if payload.location:
                    applicant.user_test_location = payload.location
            else:
                raise HTTPException(status_code=400, detail="Pelamar tidak pada tahap ujian token.")
            
            db.commit()
            return {"success": True, "message": "Jadwal dan token sesi berhasil diperbarui.", "applicant": applicant}

        # 3. ADVANCE TO NEXT STAGE
        if action == "advance":
            if applicant.current_stage >= 7:
                raise HTTPException(status_code=400, detail="Pelamar telah menyelesaikan seluruh tahapan seleksi.")

            # Transition logic per stage
            if applicant.current_stage == 1:
                # Stage 1 -> 2 (Lolos Screening, Persiapkan Psikotes)
                applicant.current_stage = 2
                applicant.stage_status = "in_progress"
                applicant.screening_notes = payload.notes or "Lolos evaluasi kualifikasi administrasi HR."
                applicant.psikotes_token = payload.token or self._generate_random_token()
                applicant.psikotes_scheduled_at = payload.scheduled_at or now

                # Dispatch email
                test_url = f"{settings.FRONTEND_CAREER_URL}/portal/test/psikotes"
                email_service.send_screening_passed(
                    to_email=applicant.email,
                    name=applicant.full_name,
                    position=job_title,
                    token=applicant.psikotes_token,
                    test_url=test_url,
                )

            elif applicant.current_stage == 2:
                # Stage 2 -> 3 (Lolos Psikotes, Persiapkan Ujian Teknis User)
                applicant.current_stage = 3
                applicant.stage_status = "in_progress"
                applicant.user_test_token = payload.token or self._generate_random_token()
                applicant.user_test_scheduled_at = payload.scheduled_at or now

            elif applicant.current_stage == 3:
                # Stage 3 -> 4 (Lolos Ujian Teknis, Persiapkan Interview HR)
                applicant.current_stage = 4
                applicant.stage_status = "in_progress"
                if payload.scheduled_at:
                    crud_interview.create(
                        db,
                        obj_in={
                            "applicant_id": applicant.id,
                            "interview_type": "hr",
                            "scheduled_at": payload.scheduled_at,
                            "location_mode": payload.location or "online",
                            "meeting_platform": payload.meeting_platform or "teams",
                            "meeting_link": payload.meeting_link,
                            "meeting_passcode": payload.meeting_passcode,
                            "interviewer_name": payload.interviewer_name or admin.name,
                            "notes": payload.notes,
                        },
                    )

            elif applicant.current_stage == 4:
                # Stage 4 -> 5 (Lolos Interview HR, Persiapkan Interview User Dept)
                applicant.current_stage = 5
                applicant.stage_status = "in_progress"
                if payload.scheduled_at:
                    crud_interview.create(
                        db,
                        obj_in={
                            "applicant_id": applicant.id,
                            "interview_type": "user",
                            "scheduled_at": payload.scheduled_at,
                            "location_mode": payload.location or "online",
                            "meeting_platform": payload.meeting_platform or "teams",
                            "meeting_link": payload.meeting_link,
                            "meeting_passcode": payload.meeting_passcode,
                            "interviewer_name": payload.interviewer_name or admin.name,
                            "notes": payload.notes,
                        },
                    )

            elif applicant.current_stage == 5:
                # Stage 5 -> 6 (Lolos Interview User, Rujukan MCU)
                applicant.current_stage = 6
                applicant.stage_status = "in_progress"
                applicant.mcu_notes = payload.notes or "Disetujui untuk rujukan Medical Check-Up (MCU)."

            elif applicant.current_stage == 6:
                # Stage 6 -> 7 (MCU Fit, Terbitkan Offering Letter)
                applicant.current_stage = 7
                applicant.stage_status = "in_progress"
                applicant.offering_status = "issued"
                applicant.offering_salary = payload.salary_offer or "Sesuai Standar Perusahaan"
                applicant.offering_letter = payload.notes or "Draft Surat Penawaran Kerja (Offering Letter) Resmi PT ITSP."

            db.commit()
            return {"success": True, "message": f"Pelamar berhasil diloloskan ke Tahap {applicant.current_stage}.", "applicant": applicant}

        # 4. SIGN CONTRACT & ONBOARDING (STAGE 7)
        if action == "sign_contract":
            if applicant.current_stage != 7:
                raise HTTPException(status_code=400, detail="Penandatanganan kontrak hanya untuk Tahap 7.")

            applicant.stage_status = "passed"
            applicant.offering_status = "accepted"
            applicant.contract_signed_at = now

            # Generate NIK Karyawan Sementara
            dept_name = applicant.job_posting.department if applicant.job_posting else "General"
            nik = self._generate_nik_sementara(db, dept_name)

            crud_karyawan.create(
                db,
                obj_in={
                    "applicant_id": applicant.id,
                    "nik_sementara": nik,
                    "nama_lengkap": applicant.full_name,
                    "email": applicant.email,
                    "no_hp": applicant.phone,
                    "departemen": dept_name,
                    "jabatan": applicant.job_posting.title if applicant.job_posting else "Staf",
                    "tanggal_bergabung": now,
                    "status_integrasi": "ready",
                },
            )
            db.commit()
            return {"success": True, "message": f"Kontrak disetujui. NIK Sementara berhasil diterbitkan: {nik}."}

        raise HTTPException(status_code=400, detail=f"Action '{action}' tidak dikenali.")


recruitment_service = RecruitmentWorkflowService()
