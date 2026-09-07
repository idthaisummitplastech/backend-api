import json
import random
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from sqlalchemy.orm import Session
from fastapi import HTTPException, status
from app.crud.crud_recruitment import crud_applicant, crud_question, crud_submission
from app.models.recruitment import Applicant, TestSubmission
from app.schemas.tests import TestQuestionCandidateView


class TestEngineService:
    """
    Online testing engine managing randomized question packages,
    anti-cheat violation telemetry, answer evaluation, and score calculation.
    """

    MAX_TAB_SWITCH_STRIKES = 3

    def start_exam_session(
        self,
        db: Session,
        applicant: Applicant,
        test_type: str,
        token: str,
    ) -> Dict[str, Any]:
        """Validate candidate token and prepare randomized question package."""
        # Check token validity
        token_clean = token.strip().upper()
        if test_type == "psikotes":
            if applicant.current_stage != 2:
                raise HTTPException(status_code=400, detail="Pelamar tidak sedang dalam tahap ujian Psikotes.")
            if not applicant.psikotes_token or applicant.psikotes_token.upper() != token_clean:
                raise HTTPException(status_code=401, detail="Token ujian Psikotes tidak valid.")
        elif test_type == "user_test":
            if applicant.current_stage != 3:
                raise HTTPException(status_code=400, detail="Pelamar tidak sedang dalam tahap Ujian Teknis User.")
            if not applicant.user_test_token or applicant.user_test_token.upper() != token_clean:
                raise HTTPException(status_code=401, detail="Token Ujian Teknis tidak valid.")
        else:
            raise HTTPException(status_code=400, detail="Jenis ujian tidak valid.")

        # Check existing submission
        existing = crud_submission.get_by_applicant_and_type(db, applicant.id, test_type)
        if existing and existing.submitted_at:
            raise HTTPException(status_code=400, detail="Anda telah menyelesaikan ujian ini.")

        # Get relevant questions
        dept = applicant.job_posting.department if applicant.job_posting else "General"
        questions = crud_question.get_by_category(db, category=test_type, department=dept)
        if not questions:
            raise HTTPException(status_code=404, detail="Bank soal ujian belum tersedia.")

        # Use applicant ID as random seed for persistent questions across page reloads
        rng = random.Random(applicant.id + (100 if test_type == "user_test" else 0))
        shuffled_questions = list(questions)
        rng.shuffle(shuffled_questions)

        # Sanitize view (Exclude correct_key)
        candidate_questions: List[Dict[str, Any]] = []
        for q in shuffled_questions:
            try:
                opts = json.loads(q.options)
            except Exception:
                opts = [q.options]

            candidate_questions.append({
                "id": q.id,
                "category": q.category,
                "department": q.department,
                "question": q.question,
                "question_type": q.question_type,
                "image_url": q.image_url,
                "options": opts,
                "points": q.points,
                "sort_order": q.sort_order,
            })

        # Save session in database if not created yet
        if not existing:
            crud_submission.create(
                db,
                obj_in={
                    "applicant_id": applicant.id,
                    "test_type": test_type,
                    "answers": json.dumps({}),
                    "question_set": json.dumps([q.id for q in shuffled_questions]),
                    "violations_count": 0,
                    "is_locked": False,
                    "started_at": datetime.now(timezone.utc),
                },
            )

        return {
            "success": True,
            "test_type": test_type,
            "applicant_name": applicant.full_name,
            "total_questions": len(candidate_questions),
            "questions": candidate_questions,
        }

    def record_violation(
        self,
        db: Session,
        applicant: Applicant,
        test_type: str,
        reason: str = "tab_switch",
    ) -> Dict[str, Any]:
        """Record anti-cheat strike when candidate switches tabs, alt-tabs, or opens devtools."""
        sub = crud_submission.get_by_applicant_and_type(db, applicant.id, test_type)
        if not sub:
            raise HTTPException(status_code=404, detail="Sesi ujian belum dimulai.")

        sub.violations_count += 1
        is_locked = sub.violations_count >= self.MAX_TAB_SWITCH_STRIKES
        if is_locked:
            sub.is_locked = True

        db.commit()

        return {
            "success": True,
            "violations_count": sub.violations_count,
            "max_allowed": self.MAX_TAB_SWITCH_STRIKES,
            "is_locked": is_locked,
            "message": "Peringatan anti-cheat tercatat." if not is_locked else "Ujian terkunci karena pelanggaran berulang.",
        }

    def evaluate_and_submit(
        self,
        db: Session,
        applicant: Applicant,
        test_type: str,
        candidate_answers: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Calculate total score against answer keys and seal the submission."""
        sub = crud_submission.get_by_applicant_and_type(db, applicant.id, test_type)
        if not sub:
            raise HTTPException(status_code=404, detail="Sesi ujian belum ditemukan.")
        if sub.submitted_at:
            raise HTTPException(status_code=400, detail="Ujian sudah pernah disubmit.")
        if sub.is_locked:
            raise HTTPException(status_code=403, detail="Ujian terkunci karena pelanggaran aturan anti-cheat.")

        dept = applicant.job_posting.department if applicant.job_posting else "General"
        questions = crud_question.get_by_category(db, category=test_type, department=dept)
        question_map = {str(q.id): q for q in questions}

        total_score = 0
        total_possible = 0

        for q_id_str, selected_key in candidate_answers.items():
            q = question_map.get(str(q_id_str))
            if q:
                total_possible += q.points
                if q.correct_key and str(selected_key).strip().upper() == q.correct_key.strip().upper():
                    total_score += q.points

        # Calculate final percentage
        percentage = round((total_score / total_possible * 100)) if total_possible > 0 else 0
        is_passed = percentage >= 65

        sub.answers = json.dumps(candidate_answers)
        sub.score = percentage
        sub.is_passed = is_passed
        sub.submitted_at = datetime.now(timezone.utc)
        db.commit()

        return {
            "success": True,
            "message": "Jawaban ujian berhasil dikumpulkan dan diproses.",
            "is_passed": is_passed,
        }


test_engine_service = TestEngineService()
