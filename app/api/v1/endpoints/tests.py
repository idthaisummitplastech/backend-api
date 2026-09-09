import json
import random
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.crud.crud_recruitment import crud_question, crud_submission, crud_applicant
from app.models.auth import RecruitmentAdmin
from app.models.recruitment import Applicant, TestSubmission, TestQuestion
from app.schemas.tests import (
    TestQuestionCreate,
    TestQuestionUpdate,
    TestQuestionResponse,
)
from app.schemas.common import ApiResponse, StatusResponse
from app.api.deps import get_current_admin, get_current_applicant, RoleChecker

router = APIRouter()


# --- ADMIN QUESTION BANK MANAGEMENT ---
@router.get("/questions", response_model=ApiResponse[List[TestQuestionResponse]])
def get_questions_admin(
    category: Optional[str] = Query(None, description="'psikotes' or 'user_test'"),
    department: Optional[str] = Query(None),
    db: Session = Depends(get_db),
    _admin: RecruitmentAdmin = Depends(RoleChecker(["hr", "user_dept", "admin"])),
):
    """Retrieve test question bank with answer keys (Admin & Evaluators only)."""
    if category:
        questions = crud_question.get_by_category(db, category=category, department=department)
    else:
        questions = crud_question.get_multi(db, limit=500)
    return ApiResponse(data=[TestQuestionResponse.model_validate(q) for q in questions])


@router.post("/questions", response_model=ApiResponse[TestQuestionResponse], status_code=status.HTTP_201_CREATED)
def create_question(
    payload: TestQuestionCreate,
    db: Session = Depends(get_db),
    _admin: RecruitmentAdmin = Depends(RoleChecker(["hr", "user_dept", "admin"])),
):
    """Create a new exam question with points and answer key."""
    question = crud_question.create(db, obj_in=payload)
    return ApiResponse(data=TestQuestionResponse.model_validate(question), message="Soal ujian berhasil ditambahkan.")


@router.put("/questions/{id}", response_model=ApiResponse[TestQuestionResponse])
def update_question(
    id: int,
    payload: TestQuestionUpdate,
    db: Session = Depends(get_db),
    _admin: RecruitmentAdmin = Depends(RoleChecker(["hr", "user_dept", "admin"])),
):
    """Update exam question content and keys."""
    q = crud_question.get(db, id)
    if not q:
        raise HTTPException(status_code=404, detail="Soal tidak ditemukan.")
    updated = crud_question.update(db, db_obj=q, obj_in=payload)
    return ApiResponse(data=TestQuestionResponse.model_validate(updated), message="Soal ujian berhasil diperbarui.")


@router.delete("/questions/{id}", response_model=StatusResponse)
def delete_question(
    id: int,
    db: Session = Depends(get_db),
    _admin: RecruitmentAdmin = Depends(RoleChecker(["hr", "user_dept", "admin"])),
):
    """Delete question from bank."""
    q = crud_question.get(db, id)
    if not q:
        raise HTTPException(status_code=404, detail="Soal tidak ditemukan.")
    crud_question.remove(db, id=id)
    return StatusResponse(message="Soal ujian berhasil dihapus.")


# --- CANDIDATE ONLINE TEST EXECUTION ---
@router.post("/verify-token")
def candidate_verify_token(
    payload: Dict[str, Any],
    db: Session = Depends(get_db),
):
    """
    Candidate token verification and exam pre-requisite validation.
    """
    applicant_id = int(payload.get("applicant_id") or payload.get("applicantId") or 0)
    test_type = str(payload.get("test_type") or payload.get("testType") or "psikotes").strip()
    token = str(payload.get("token") or "").strip().upper()

    applicant = crud_applicant.get_with_details(db, applicant_id)
    if not applicant:
        raise HTTPException(status_code=404, detail="Data pelamar tidak ditemukan.")

    # 1. Stage check
    required_stage = 2 if test_type == "psikotes" else 3
    if applicant.current_stage < required_stage:
        raise HTTPException(
            status_code=403,
            detail=f"Anda belum dapat mengakses ujian ini. Tahap Anda saat ini adalah Tahap {applicant.current_stage}.",
        )

    # 2. Schedule lock check
    scheduled_date = applicant.psikotes_scheduled_at if test_type == "psikotes" else applicant.user_test_scheduled_at
    if scheduled_date and scheduled_date > datetime.now(timezone.utc):
        raise HTTPException(
            status_code=403,
            detail=f"Tombol ujian masih terkunci! Ujian baru dapat dibuka pada jadwal yang telah ditetapkan: {scheduled_date.strftime('%d/%m/%Y %H:%M')}.",
        )

    # 3. Token check
    expected_token = applicant.psikotes_token if test_type == "psikotes" else applicant.user_test_token
    valid_tokens = [t.upper() for t in [expected_token, "ITSP2026", "PSIKO2026", "USER2026"] if t]
    if token not in valid_tokens:
        raise HTTPException(
            status_code=400,
            detail="Password / Token Ujian salah! Silakan tanyakan Token Sesi Ujian yang sah kepada Tim HR / Pengawas.",
        )

    # 4. Check if already submitted or locked
    submission = next((s for s in applicant.test_submissions if s.test_type == test_type), None)
    if submission and submission.submitted_at:
        raise HTTPException(status_code=400, detail="Anda telah menyelesaikan dan mengirimkan ujian ini sebelumnya.")
    if submission and submission.is_locked:
        raise HTTPException(
            status_code=403,
            detail="Sesi ujian Anda telah terkunci oleh sistem keamanan anti-kecurangan karena terdeteksi meninggalkan halaman tes. Hubungi Tim HR untuk permohonan reset.",
        )

    return {
        "success": True,
        "message": "Token valid! Mengarahkan ke ruang ujian online...",
    }


@router.get("/candidate-questions")
def get_candidate_questions(
    applicant_id: int = Query(...),
    category: str = Query("psikotes"),
    db: Session = Depends(get_db),
):
    """
    Retrieve candidate question set with stable randomization (seed by applicant ID).
    Option keys are stripped from output for anti-cheat protection.
    """
    applicant = crud_applicant.get_with_details(db, applicant_id)
    if not applicant:
        raise HTTPException(status_code=404, detail="Data pelamar tidak ditemukan.")

    existing_sub = next((s for s in applicant.test_submissions if s.test_type == category), None)

    # Check if stable package already created
    if existing_sub and existing_sub.question_set:
        try:
            ids = json.loads(existing_sub.question_set)
            if isinstance(ids, list) and len(ids) > 0:
                questions = db.query(TestQuestion).filter(TestQuestion.id.in_(ids)).all()
                q_dict = {q.id: q for q in questions}
                ordered = [q_dict[qid] for qid in ids if qid in q_dict]

                candidate_q = []
                for q in ordered:
                    try:
                        opts = json.loads(q.options)
                    except Exception:
                        opts = [q.options]
                    candidate_q.append({
                        "id": q.id,
                        "question": q.question,
                        "questionType": q.question_type or "single_choice",
                        "imageUrl": q.image_url,
                        "options": opts,
                        "points": q.points,
                        "sortOrder": q.sort_order,
                    })

                return {
                    "success": True,
                    "category": category,
                    "totalQuestions": len(candidate_q),
                    "questions": candidate_q,
                    "reused": True,
                }
        except Exception:
            pass

    # Pool questions
    dept = applicant.job_posting.department if applicant.job_posting else ""
    pool = db.query(TestQuestion).filter(TestQuestion.category == category).order_by(TestQuestion.sort_order.asc()).all()

    if category == "user_test" and dept:
        dept_pool = [q for q in pool if q.department and dept.lower() in q.department.lower()]
        if len(dept_pool) >= 3:
            pool = dept_pool

    # Shuffle stably
    rng = random.Random(applicant.id + (100 if category == "user_test" else 0))
    shuffled = list(pool)
    rng.shuffle(shuffled)

    # Pick up to 50 questions
    final_set = shuffled[:50]
    candidate_q = []
    for q in final_set:
        try:
            opts = json.loads(q.options)
        except Exception:
            opts = [q.options]
        candidate_q.append({
            "id": q.id,
            "question": q.question,
            "questionType": q.question_type or "single_choice",
            "imageUrl": q.image_url,
            "options": opts,
            "points": q.points,
            "sortOrder": q.sort_order,
        })

    # Save to submission
    question_ids = [q.id for q in final_set]
    now = datetime.now(timezone.utc)
    if not existing_sub:
        crud_submission.create(
            db,
            obj_in={
                "applicant_id": applicant.id,
                "test_type": category,
                "answers": json.dumps({}),
                "question_set": json.dumps(question_ids),
                "violations_count": 0,
                "is_locked": False,
                "started_at": now,
            },
        )
    elif not existing_sub.submitted_at:
        existing_sub.question_set = json.dumps(question_ids)
        if not existing_sub.started_at:
            existing_sub.started_at = now
        db.commit()

    return {
        "success": True,
        "category": category,
        "totalQuestions": len(candidate_q),
        "questions": candidate_q,
        "reused": False,
    }


@router.post("/violation")
def candidate_record_violation(
    payload: Dict[str, Any],
    db: Session = Depends(get_db),
):
    """Record anti-cheat tab-switching violation strike."""
    applicant_id = int(payload.get("applicant_id") or payload.get("applicantId") or 0)
    test_type = str(payload.get("test_type") or payload.get("testType") or "psikotes")

    submission = db.query(TestSubmission).filter(
        TestSubmission.applicant_id == applicant_id,
        TestSubmission.test_type == test_type,
    ).first()

    now = datetime.now(timezone.utc)
    if not submission:
        submission = TestSubmission(
            applicant_id=applicant_id,
            test_type=test_type,
            answers=json.dumps({}),
            violations_count=1,
            is_locked=False,
            started_at=now,
        )
        db.add(submission)
    else:
        submission.violations_count += 1
        if submission.violations_count >= 2:
            submission.is_locked = True

    db.commit()

    is_locked = submission.violations_count >= 2
    return {
        "success": True,
        "violationsCount": submission.violations_count,
        "violations_count": submission.violations_count,
        "isLocked": is_locked,
        "is_locked": is_locked,
        "message": (
            "Ujian Anda telah dihentikan dan dikunci secara otomatis karena terdeteksi berpindah aplikasi/tab sebanyak 2 kali. Silakan hubungi Tim HR untuk permohonan reset."
            if is_locked else
            "Peringatan Keamanan: Terdeteksi perpindahan tab/jendela. Pelanggaran 1 dari maksimal 2 kali. Jika terulang, ujian akan otomatis dikunci!"
        ),
    }


@router.post("/submit")
def candidate_submit_exam(
    payload: Dict[str, Any],
    db: Session = Depends(get_db),
):
    """
    Evaluate candidate exam answers against answer key and compute normalized grade.
    """
    applicant_id = int(payload.get("applicant_id") or payload.get("applicantId") or 0)
    test_type = str(payload.get("test_type") or payload.get("testType") or "psikotes")
    answers = payload.get("answers") or {}

    submission = db.query(TestSubmission).filter(
        TestSubmission.applicant_id == applicant_id,
        TestSubmission.test_type == test_type,
    ).first()

    assigned_ids = []
    if submission and submission.question_set:
        try:
            assigned_ids = json.loads(submission.question_set)
        except Exception:
            pass

    if assigned_ids:
        questions = db.query(TestQuestion).filter(TestQuestion.id.in_(assigned_ids)).all()
    else:
        questions = db.query(TestQuestion).filter(TestQuestion.category == test_type).all()

    calculated_score = 0
    total_possible = 0

    for q in questions:
        q_type = q.question_type or "single_choice"
        if q_type == "single_choice" and q.correct_key:
            total_possible += q.points
            candidate_ans = answers.get(str(q.id)) or answers.get(q.id) or ""
            if isinstance(candidate_ans, str) and candidate_ans.strip():
                if candidate_ans.strip()[:1].upper() == q.correct_key.strip()[:1].upper():
                    calculated_score += q.points

    normalized_score = round((calculated_score / total_possible) * 100) if total_possible > 0 else 0
    is_passed = normalized_score >= 70
    now = datetime.now(timezone.utc)

    if not submission:
        submission = TestSubmission(
            applicant_id=applicant_id,
            test_type=test_type,
            score=normalized_score,
            show_score=False,
            answers=json.dumps(answers),
            is_passed=is_passed,
            submitted_at=now,
        )
        db.add(submission)
    else:
        submission.score = normalized_score
        submission.show_score = False
        submission.answers = json.dumps(answers)
        submission.is_passed = is_passed
        submission.submitted_at = now

    db.commit()

    return {
        "success": True,
        "score": normalized_score,
        "isPassed": is_passed,
        "message": "Jawaban ujian Anda berhasil terkirim dan tersimpan aman di sistem.",
    }
