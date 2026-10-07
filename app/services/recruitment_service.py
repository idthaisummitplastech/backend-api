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
    is_dept_match,
)
from app.models.auth import RecruitmentAdmin
from app.models.recruitment import Applicant, KaryawanSementara, InterviewSchedule
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
        """Enforce departmental and role-based stage access control."""
        # Superadmin and HR have full progression authority across all stages (including Stage 3 & 5)
        if admin.role in ["admin", "hr"]:
            return

        if admin.role == "user_dept":
            if applicant.current_stage not in self.USER_DEPT_STAGES:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail=f"Akses Ditolak: User Departemen hanya berhak mengevaluasi Tahap 3 (Ujian Teknis) & Tahap 5 (Interview User). Tahap {applicant.current_stage} dikelola oleh HR / Admin.",
                )

            # Department scope check using is_dept_match
            job_dept = applicant.job_posting.department if applicant.job_posting else ""
            if not is_dept_match(admin.department, job_dept):
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail=f"Akses Ditolak: Anda login untuk divisi '{admin.department}'. Pelamar ini melamar untuk divisi '{job_dept}'.",
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
        action = (payload.action or "").strip().lower()
        # Normalisasi alias frontend: 'approve' == 'advance'
        if action == "approve":
            action = "advance"

        # For scheduling/token updates and manual stage overrides, HR and admin have full control
        # RBAC stage restriction only applies to standard stage progression (advance/reject)
        if action not in ["update_test_session", "update_token", "override_stage", "manual_stage", "set_stage"] or admin.role not in ["hr", "admin"]:
            self.validate_rbac_stage(admin, applicant)

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
            dur = payload.duration_minutes
            if payload.scheduled_until and payload.scheduled_at:
                diff_sec = (payload.scheduled_until - payload.scheduled_at).total_seconds()
                if diff_sec > 0:
                    dur = int(diff_sec / 60)

            if applicant.current_stage == 2:
                if payload.token:
                    applicant.psikotes_token = payload.token.strip().upper()
                if payload.scheduled_at:
                    applicant.psikotes_scheduled_at = payload.scheduled_at
                if dur:
                    applicant.psikotes_duration_minutes = dur
                if payload.location:
                    applicant.psikotes_location = payload.location
                if payload.maps_url:
                    applicant.psikotes_maps_url = payload.maps_url
            elif applicant.current_stage == 3:
                if payload.token:
                    applicant.user_test_token = payload.token.strip().upper()
                if payload.scheduled_at:
                    applicant.user_test_scheduled_at = payload.scheduled_at
                if dur:
                    applicant.user_test_duration_minutes = dur
                if payload.location:
                    applicant.user_test_location = payload.location
                if payload.maps_url:
                    applicant.user_test_maps_url = payload.maps_url
            else:
                raise HTTPException(status_code=400, detail="Pelamar tidak pada tahap ujian token.")
            
            db.commit()
            return {"success": True, "message": "Jadwal dan token sesi berhasil diperbarui.", "applicant": applicant}

        # 2b. UPDATE OFFERING LETTER FORMAT & SIGNATURE (HR/Admin Editor)
        if action == "update_offering":
            if payload.salary_offer:
                applicant.offering_salary = payload.salary_offer
            if payload.notes:
                applicant.offering_letter = payload.notes
            if payload.offering_attachment is not None:
                applicant.offering_attachment = payload.offering_attachment
            if payload.offering_clauses is not None:
                applicant.offering_clauses = payload.offering_clauses
            if payload.offering_signer_name:
                applicant.offering_signer_name = payload.offering_signer_name
            if payload.offering_signer_title:
                applicant.offering_signer_title = payload.offering_signer_title
            if payload.offering_signer_signature:
                applicant.offering_signer_signature = payload.offering_signer_signature
            if payload.offering_join_date:
                applicant.offering_join_date = payload.offering_join_date
            if payload.offering_ref_number:
                applicant.offering_ref_number = payload.offering_ref_number
            db.commit()
            return {"success": True, "message": "Format dan tanda tangan digital Offering Letter berhasil diperbarui.", "applicant": applicant}

        # 3. ADVANCE TO NEXT STAGE
        if action in ["advance", "approve"]:
            if applicant.current_stage >= 7:
                raise HTTPException(status_code=400, detail="Pelamar telah menyelesaikan seluruh tahapan seleksi.")

            email_sent = True
            email_error = None

            dur = payload.duration_minutes
            if payload.scheduled_until and payload.scheduled_at:
                diff_sec = (payload.scheduled_until - payload.scheduled_at).total_seconds()
                if diff_sec > 0:
                    dur = int(diff_sec / 60)

            # Transition logic per stage
            if applicant.current_stage == 1:
                # Stage 1 -> 2 (Lolos Screening, Persiapkan Psikotes)
                applicant.current_stage = 2
                applicant.stage_status = "in_progress"
                applicant.screening_notes = payload.notes or "Lolos evaluasi kualifikasi administrasi HR."
                applicant.psikotes_token = payload.token or self._generate_random_token()
                applicant.psikotes_scheduled_at = payload.scheduled_at or now
                if dur:
                    applicant.psikotes_duration_minutes = dur
                if payload.location:
                    applicant.psikotes_location = payload.location
                if payload.maps_url:
                    applicant.psikotes_maps_url = payload.maps_url

                # Dispatch email with schedule & maps if provided
                test_url = f"{settings.FRONTEND_CAREER_URL}/portal/test/psikotes"
                email_res = email_service.send_screening_passed(
                    to_email=applicant.email,
                    name=applicant.full_name,
                    position=job_title,
                    token=applicant.psikotes_token,
                    test_url=test_url,
                    location=applicant.psikotes_location,
                    maps_url=applicant.psikotes_maps_url,
                    scheduled_at=applicant.psikotes_scheduled_at,
                    duration_minutes=applicant.psikotes_duration_minutes,
                )
                email_sent = email_res.get("success", False)
                email_error = email_res.get("error", None)

            elif applicant.current_stage == 2:
                # Stage 2 -> 3 (Lolos Psikotes, Persiapkan Ujian Teknis User)
                applicant.current_stage = 3
                applicant.stage_status = "in_progress"
                applicant.user_test_token = payload.token or self._generate_random_token()
                applicant.user_test_scheduled_at = payload.scheduled_at or now
                if dur:
                    applicant.user_test_duration_minutes = dur
                if payload.location:
                    applicant.user_test_location = payload.location
                if payload.maps_url:
                    applicant.user_test_maps_url = payload.maps_url

                test_url = f"{settings.FRONTEND_CAREER_URL}/portal/test/user-test"
                email_res = email_service.send_user_test_invitation(
                    to_email=applicant.email,
                    name=applicant.full_name,
                    position=job_title,
                    token=applicant.user_test_token,
                    test_url=test_url,
                    location=applicant.user_test_location,
                    maps_url=applicant.user_test_maps_url,
                    scheduled_at=applicant.user_test_scheduled_at,
                    duration_minutes=applicant.user_test_duration_minutes,
                )
                email_sent = email_res.get("success", False)
                email_error = email_res.get("error", None)

            elif applicant.current_stage == 3:
                # Stage 3 -> 4 (Lolos Ujian Teknis, Persiapkan Interview HR)
                applicant.current_stage = 4
                applicant.stage_status = "in_progress"
                if payload.scheduled_at:
                    loc_str = str(payload.location or "").lower()
                    loc_mode = "onsite" if any(k in loc_str for k in ["plant", "pabrik", "gedung", "ruang", "onsite", "kiic", "giic"]) else "online"
                    crud_interview.create(
                        db,
                        obj_in={
                            "applicant_id": applicant.id,
                            "interview_type": "hr",
                            "scheduled_at": payload.scheduled_at,
                            "location_mode": loc_mode,
                            "meeting_platform": payload.meeting_platform or "teams",
                            "meeting_link": payload.meeting_link,
                            "meeting_passcode": payload.meeting_passcode,
                            "location_address": payload.location,
                            "maps_url": payload.maps_url,
                            "interviewer_name": payload.interviewer_name or admin.name,
                            "notes": payload.notes,
                        },
                    )
                    email_res = email_service.send_interview_invitation(
                        to_email=applicant.email,
                        name=applicant.full_name,
                        position=job_title,
                        interview_type="hr",
                        scheduled_at=payload.scheduled_at,
                        location_mode=loc_mode,
                        meeting_platform=payload.meeting_platform or "teams",
                        meeting_link=payload.meeting_link,
                        meeting_passcode=payload.meeting_passcode,
                        location_address=payload.location,
                        maps_url=payload.maps_url,
                        interviewer_name=payload.interviewer_name or admin.name,
                        notes=payload.notes,
                    )
                    email_sent = email_res.get("success", False)
                    email_error = email_res.get("error", None)
                else:
                    email_res = email_service.send_stage_passed_notification(
                        to_email=applicant.email,
                        name=applicant.full_name,
                        position=job_title,
                        stage_num=4,
                        stage_name="Interview HR Recruitment",
                        message=payload.notes or "Selamat! Hasil evaluasi Ujian Teknis Anda telah lolos. Anda berhak melanjutkan ke Tahap 4: Interview HR Recruitment bersama tim Human Capital PT ITSP.",
                        maps_url=payload.maps_url,
                    )
                    email_sent = email_res.get("success", False)
                    email_error = email_res.get("error", None)

            elif applicant.current_stage == 4:
                # Stage 4 -> 5 (Lolos Interview HR, Persiapkan Interview User Dept)
                applicant.current_stage = 5
                applicant.stage_status = "in_progress"
                if payload.scheduled_at:
                    loc_str = str(payload.location or "").lower()
                    loc_mode = "onsite" if any(k in loc_str for k in ["plant", "pabrik", "gedung", "ruang", "onsite", "kiic", "giic"]) else "online"
                    crud_interview.create(
                        db,
                        obj_in={
                            "applicant_id": applicant.id,
                            "interview_type": "user",
                            "scheduled_at": payload.scheduled_at,
                            "location_mode": loc_mode,
                            "meeting_platform": payload.meeting_platform or "teams",
                            "meeting_link": payload.meeting_link,
                            "meeting_passcode": payload.meeting_passcode,
                            "location_address": payload.location,
                            "maps_url": payload.maps_url,
                            "interviewer_name": payload.interviewer_name or admin.name,
                            "notes": payload.notes,
                        },
                    )
                    email_res = email_service.send_interview_invitation(
                        to_email=applicant.email,
                        name=applicant.full_name,
                        position=job_title,
                        interview_type="user",
                        scheduled_at=payload.scheduled_at,
                        location_mode=loc_mode,
                        meeting_platform=payload.meeting_platform or "teams",
                        meeting_link=payload.meeting_link,
                        meeting_passcode=payload.meeting_passcode,
                        location_address=payload.location,
                        maps_url=payload.maps_url,
                        interviewer_name=payload.interviewer_name or admin.name,
                        notes=payload.notes,
                    )
                    email_sent = email_res.get("success", False)
                    email_error = email_res.get("error", None)
                else:
                    email_res = email_service.send_stage_passed_notification(
                        to_email=applicant.email,
                        name=applicant.full_name,
                        position=job_title,
                        stage_num=5,
                        stage_name="Interview Teknis User Departemen",
                        message=payload.notes or "Selamat! Anda dinyatakan lolos sesi Interview HR. Tahap berikutnya adalah Interview Teknis bersama pimpinan User Departemen.",
                        maps_url=payload.maps_url,
                    )
                    email_sent = email_res.get("success", False)
                    email_error = email_res.get("error", None)

            elif applicant.current_stage == 5:
                # Stage 5 -> 6 (Lolos Interview User, Rujukan MCU)
                applicant.current_stage = 6
                applicant.stage_status = "in_progress"
                applicant.mcu_notes = payload.notes or "Disetujui untuk rujukan Medical Check-Up (MCU)."
                
                mcu_maps = payload.maps_url
                if not mcu_maps:
                    settings_list = crud_setting.get_multi(db, limit=100)
                    s_map = {s.key: s.value for s in settings_list}
                    mcu_maps = s_map.get("mcu_partner_maps") or s_map.get("mcu_partner_address") or ""

                email_res = email_service.send_stage_passed_notification(
                    to_email=applicant.email,
                    name=applicant.full_name,
                    position=job_title,
                    stage_num=6,
                    stage_name="Medical Check-Up (MCU)",
                    message=payload.notes or "Selamat! Anda dinyatakan lolos sesi interview user dan berhak melanjutkan ke Tahap 6: Medical Check-Up (MCU) di fasilitas kesehatan rekanan resmi PT Indonesia Thai Summit Plastech.",
                    maps_url=mcu_maps,
                )
                email_sent = email_res.get("success", False)
                email_error = email_res.get("error", None)

            elif applicant.current_stage == 6:
                # Stage 6 -> 7 (MCU Fit, Terbitkan Offering Letter)
                applicant.current_stage = 7
                applicant.stage_status = "in_progress"
                applicant.offering_status = "issued"
                applicant.offering_salary = payload.salary_offer or "Sesuai Standar Company"
                applicant.offering_letter = payload.notes or "Draft Surat Penawaran Kerja (Offering Letter) Resmi PT ITSP."
                if payload.offering_attachment:
                    applicant.offering_attachment = payload.offering_attachment
                if payload.offering_clauses:
                    applicant.offering_clauses = payload.offering_clauses
                if payload.offering_signer_name:
                    applicant.offering_signer_name = payload.offering_signer_name
                if payload.offering_signer_title:
                    applicant.offering_signer_title = payload.offering_signer_title
                if payload.offering_signer_signature:
                    applicant.offering_signer_signature = payload.offering_signer_signature
                if payload.offering_join_date:
                    applicant.offering_join_date = payload.offering_join_date
                if payload.offering_ref_number:
                    applicant.offering_ref_number = payload.offering_ref_number
                email_res = email_service.send_stage_passed_notification(
                    to_email=applicant.email,
                    name=applicant.full_name,
                    position=job_title,
                    stage_num=7,
                    stage_name="Offering Letter & Penawaran Kontrak",
                    message=f"Selamat! Hasil Medical Check-Up (MCU) Anda dinyatakan FIT TO WORK. PT Indonesia Thai Summit Plastech dengan bangga menerbitkan Surat Penawaran Kerja (Offering Letter) untuk posisi {job_title}. Silakan login ke Portal Karir untuk memeriksa rincian penawaran dan menandatangani kontrak kerja.",
                )
                email_sent = email_res.get("success", False)
                email_error = email_res.get("error", None)

            db.commit()
            return {
                "success": True,
                "message": f"Pelamar berhasil diloloskan ke Tahap {applicant.current_stage}.",
                "applicant": applicant,
                "email_sent": email_sent,
                "email_error": email_error,
            }

        # 4. OVERRIDE / MANUAL ADJUSTMENT (SUPER ADMIN & HR MANUAL STAGE CHANGER)
        if action in ["override_stage", "manual_stage", "set_stage"]:
            if admin.role not in ["admin", "hr"]:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Akses Ditolak: Hanya Administrator dan HR yang berwenang mengubah tahap seleksi secara manual.",
                )

            new_stage = payload.target_stage
            if not new_stage or new_stage < 1 or new_stage > 7:
                raise HTTPException(status_code=400, detail="Target tahap tidak valid (harus antara 1 hingga 7).")

            old_stage = applicant.current_stage
            applicant.current_stage = new_stage
            if payload.stage_status:
                applicant.stage_status = payload.stage_status
            if applicant.stage_status != "failed":
                applicant.failed_at_stage = None
                applicant.rejection_reason = None

            # If rolling back before stage 4 or 5, remove orphaned interview schedules for future stages
            if new_stage < 4:
                db.query(InterviewSchedule).filter(InterviewSchedule.applicant_id == applicant.id).delete()
            elif new_stage == 4:
                # Keep HR interview, remove user interviews
                db.query(InterviewSchedule).filter(InterviewSchedule.applicant_id == applicant.id, InterviewSchedule.interview_type == "user").delete()

            email_sent = True
            email_error = None
            if payload.send_email:
                stage_names = {
                    1: "Screening Berkas Administrasi",
                    2: "Ujian Psikotes Online",
                    3: "Ujian Teknis Kejuruan & Uraian Kasus",
                    4: "Interview HR Recruitment",
                    5: "Interview Teknis User Departemen",
                    6: "Medical Check-Up (MCU)",
                    7: "Offering Letter & Kontrak Kerja",
                }
                stage_name = stage_names.get(new_stage, f"Tahap {new_stage}")
                status_label = "Aktif (Sedang Berjalan)" if applicant.stage_status == "in_progress" else "Lolos" if applicant.stage_status == "passed" else "Gugur"
                email_res = email_service.send_stage_override_notification(
                    to_email=applicant.email,
                    name=applicant.full_name,
                    position=job_title,
                    stage_num=new_stage,
                    stage_name=stage_name,
                    status_text=status_label,
                    notes=payload.notes,
                )
                email_sent = email_res.get("success", False)
                email_error = email_res.get("error", None)

            db.commit()
            return {
                "success": True,
                "message": f"Tahap pelamar berhasil diubah secara manual dari Tahap {old_stage} menjadi Tahap {new_stage}.",
                "applicant": applicant,
                "email_sent": email_sent,
                "email_error": email_error,
            }

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
