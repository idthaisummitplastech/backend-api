import json
from datetime import datetime
from typing import Any, Dict, List, Optional, Union
from pydantic import BaseModel, ConfigDict, Field, field_validator


class TestQuestionBase(BaseModel):
    category: str = Field(..., description="'psikotes' or 'user_test'")
    department: Optional[str] = "General"
    question: str
    question_type: str = Field("single_choice", alias="questionType")
    image_url: Optional[str] = Field(None, alias="imageUrl")
    options: Union[str, List[str]] = Field(..., description="JSON string array of options e.g. [\"A\", \"B\", \"C\", \"D\"] or list of strings")
    points: int = 10
    sort_order: int = Field(0, alias="sortOrder")

    model_config = ConfigDict(populate_by_name=True, extra="ignore")

    @field_validator("options", mode="before")
    @classmethod
    def validate_options(cls, v: Any) -> str:
        if isinstance(v, (list, tuple)):
            return json.dumps(list(v))
        if isinstance(v, str):
            return v
        return "[]"


class TestQuestionCreate(TestQuestionBase):
    correct_key: Optional[str] = Field(None, alias="correctKey")


class TestQuestionUpdate(BaseModel):
    category: Optional[str] = None
    department: Optional[str] = None
    question: Optional[str] = None
    question_type: Optional[str] = Field(None, alias="questionType")
    image_url: Optional[str] = Field(None, alias="imageUrl")
    options: Optional[Union[str, List[str]]] = None
    correct_key: Optional[str] = Field(None, alias="correctKey")
    points: Optional[int] = None
    sort_order: Optional[int] = Field(None, alias="sortOrder")

    model_config = ConfigDict(populate_by_name=True, extra="ignore")

    @field_validator("options", mode="before")
    @classmethod
    def validate_options(cls, v: Any) -> Optional[str]:
        if v is None:
            return None
        if isinstance(v, (list, tuple)):
            return json.dumps(list(v))
        if isinstance(v, str):
            return v
        return "[]"


class TestQuestionResponse(TestQuestionBase):
    id: int
    correct_key: Optional[str] = None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True, populate_by_name=True, extra="ignore")


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
    answers: Optional[str] = None
    question_set: Optional[str] = None
    option_map: Optional[str] = None
    violations_count: int
    is_locked: bool
    is_passed: Optional[bool] = None
    started_at: Optional[datetime] = None
    submitted_at: Optional[datetime] = None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)
