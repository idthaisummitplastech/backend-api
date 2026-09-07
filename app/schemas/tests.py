from datetime import datetime
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, ConfigDict, Field


class TestQuestionBase(BaseModel):
    category: str = Field(..., description="'psikotes' or 'user_test'")
    department: Optional[str] = "General"
    question: str
    question_type: str = "single_choice"
    image_url: Optional[str] = None
    options: str = Field(..., description="JSON string array of options e.g. [\"A\", \"B\", \"C\", \"D\"]")
    points: int = 10
    sort_order: int = 0


class TestQuestionCreate(TestQuestionBase):
    correct_key: Optional[str] = None


class TestQuestionUpdate(BaseModel):
    category: Optional[str] = None
    department: Optional[str] = None
    question: Optional[str] = None
    question_type: Optional[str] = None
    image_url: Optional[str] = None
    options: Optional[str] = None
    correct_key: Optional[str] = None
    points: Optional[int] = None
    sort_order: Optional[int] = None


class TestQuestionResponse(TestQuestionBase):
    id: int
    correct_key: Optional[str] = None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class TestQuestionCandidateView(BaseModel):
    """Secure question view presented to applicants (EXCLUDES correct_key)."""
    id: int
    category: str
    department: Optional[str] = None
    question: str
    question_type: str
    image_url: Optional[str] = None
    options: List[str]  # Parsed and shuffled options
    points: int
    sort_order: int


class TestStartRequest(BaseModel):
    test_type: str = Field(..., description="'psikotes' or 'user_test'")
    token: str = Field(..., min_length=4)


class TestSubmissionRequest(BaseModel):
    test_type: str
    answers: Dict[str, Any]  # {question_id: selected_key}


class ViolationReportRequest(BaseModel):
    test_type: str
    reason: str = "tab_switch"


class TestSubmissionResponse(BaseModel):
    id: int
    applicant_id: int
    test_type: str
    score: Optional[int] = 0
    show_score: bool
    violations_count: int
    is_locked: bool
    is_passed: Optional[bool] = None
    started_at: Optional[datetime] = None
    submitted_at: Optional[datetime] = None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)
