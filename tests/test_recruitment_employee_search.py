"""Tes pencarian GET /api/v1/recruitment/employees (B1).

Fokus: pencarian token per kata, normalisasi spasi, trim, dan tanpa duplikat.
Endpoint dipanggil langsung dengan session SQLite in-memory agar tidak memerlukan
database produksi maupun autentikasi jaringan.
"""
import os
from datetime import datetime, timezone

os.environ["ENVIRONMENT"] = "test"
os.environ["DEBUG"] = "true"

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.models.recruitment import DataKaryawan
from app.api.v1.endpoints.recruitment import get_employees_list


@pytest.fixture()
def db():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    session = SessionLocal()
    try:
        session.add_all([
            DataKaryawan(
                employee_id="1530.09.26",
                sequence_number=1530,
                full_name="Rifqi Ahmad Alfaridzi",
                first_name="Rifqi",
                last_name="Alfaridzi",
                nik="3201012345670001",
                email="rifqi.ahmad@example.test",
                department="SYD & IT",
                job_title="Software Engineer",
                employee_status="active",
                contract_start_date=datetime(2025, 1, 1, tzinfo=timezone.utc),
            ),
            DataKaryawan(
                employee_id="1531.10.26",
                sequence_number=1531,
                full_name="Siti Nurhaliza",
                first_name="Siti",
                last_name="Nurhaliza",
                nik="3201012345670002",
                email="siti.nurhaliza@example.test",
                department="Human Resources",
                job_title="HR Specialist",
                employee_status="active",
                contract_start_date=datetime(2025, 1, 1, tzinfo=timezone.utc),
            ),
            DataKaryawan(
                employee_id="1532.11.26",
                sequence_number=1532,
                full_name="Ahmad Fauzi",
                first_name="Ahmad",
                last_name="Fauzi",
                nik="3201012345670003",
                email="ahmad.fauzi@example.test",
                department="Production",
                job_title="Operator",
                employee_status="active",
                contract_start_date=datetime(2025, 1, 1, tzinfo=timezone.utc),
            ),
        ])
        session.commit()
        yield session
    finally:
        session.close()
        engine.dispose()


def _employee_ids(result):
    return [emp["employee_id"] for emp in result["employees"]]


def _search(db, term):
    return get_employees_list(
        department=None,
        contract_status=None,
        employee_status="all",
        contract_eval=None,
        search=term,
        sort="asc",
        db=db,
        _admin=None,
    )


def test_search_by_first_name(db):
    assert _employee_ids(_search(db, "Rifqi")) == ["1530.09.26"]


def test_search_by_last_name(db):
    assert _employee_ids(_search(db, "Nurhaliza")) == ["1531.10.26"]


def test_search_two_words_tokenized(db):
    # "Ahmad Alfaridzi" cocok ke kolom berbeda pada baris yang sama.
    assert _employee_ids(_search(db, "Ahmad Alfaridzi")) == ["1530.09.26"]


def test_search_normalizes_extra_whitespace(db):
    assert _employee_ids(_search(db, "   Ahmad    Alfaridzi   ")) == ["1530.09.26"]


def test_search_not_found(db):
    result = _search(db, "NamaYangTidakAda")
    assert result["employees"] == []
    assert result["total"] == 0


def test_search_matches_email_and_employee_id(db):
    assert _employee_ids(_search(db, "siti.nurhaliza@example.test")) == ["1531.10.26"]
    assert _employee_ids(_search(db, "1532.11.26")) == ["1532.11.26"]


def test_search_no_duplicates_when_multiple_columns_match(db):
    # "ahmad" cocok di full_name dan email pada baris yang sama -> harus 1 baris.
    ids = _employee_ids(_search(db, "ahmad"))
    assert ids == ["1530.09.26", "1532.11.26"]
    assert len(ids) == len(set(ids))
