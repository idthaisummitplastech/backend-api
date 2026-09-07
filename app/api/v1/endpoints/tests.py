from typing import Any, Dict, List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.crud.crud_recruitment import crud_question, crud_submission
from app.models.auth import RecruitmentAdmin
from app.models.recruitment import Applicant
from app.schemas.tests import (
    TestQuestionCreate,
    TestQuestionUpdate,
    TestQuestionResponse,
    TestStartRequest,
    TestSubmissionRequest,
    ViolationReportRequest,
)
from app.schemas.common import ApiResponse, StatusResponse
from app.services.test_engine_service import test_engine_service
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
@router.post("/start")
def candidate_start_exam(
    payload: TestStartRequest,
    current_applicant: Applicant = Depends(get_current_applicant),
    db: Session = Depends(get_db),
):
    """Validate exam session token and receive randomized question set."""
    return test_engine_service.start_exam_session(
        db,
        applicant=current_applicant,
        test_type=payload.test_type,
        token=payload.token,
    )


@router.post("/violation")
def candidate_record_violation(
    payload: ViolationReportRequest,
    current_applicant: Applicant = Depends(get_current_applicant),
    db: Session = Depends(get_db),
):
    """Log anti-cheat tab-switching violation strike."""
    return test_engine_service.record_violation(
        db,
        applicant=current_applicant,
        test_type=payload.test_type,
        reason=payload.reason,
    )


@router.post("/submit")
def candidate_submit_exam(
    payload: TestSubmissionRequest,
    current_applicant: Applicant = Depends(get_current_applicant),
    db: Session = Depends(get_db),
):
    """Submit completed exam answers for automatic grading."""
    return test_engine_service.evaluate_and_submit(
        db,
        applicant=current_applicant,
        test_type=payload.test_type,
        candidate_answers=payload.answers,
    )
