"""
Employee Import Service for PT Indonesia Thai Summit Plastech
Parses Excel sheets (ITSP, Trainee, Out) into structured employee data.
"""

import logging
from datetime import datetime, timezone
from typing import Any, Dict, Optional, List

logger = logging.getLogger("employee_import_service")


def clean_str(val: Any) -> Optional[str]:
    if val is None:
        return None
    s = str(val).strip()
    return s if s else None


def clean_date(val: Any) -> Optional[datetime]:
    if val is None:
        return None
    if isinstance(val, datetime):
        if val.tzinfo is None:
            return val.replace(tzinfo=timezone.utc)
        return val
    try:
        s = str(val).strip()
        if not s or s.lower() in ("none", "null", "-", "#n/a"):
            return None
        dt = datetime.fromisoformat(s[:10])
        return dt.replace(tzinfo=timezone.utc)
    except Exception:
        return None


def clean_int(val: Any) -> Optional[int]:
    if val is None:
        return None
    try:
        return int(float(str(val).strip()))
    except Exception:
        return None


def map_contract_status(status_raw: Optional[str]) -> str:
    if not status_raw:
        return "PKWT"
    sr = status_raw.strip().upper()
    if sr in ("P", "PERMANENT", "TETAP"):
        return "PKWTT"
    if sr in ("C", "CONTRACT", "KONTRAK"):
        return "PKWT"
    if sr in ("T", "TRAINEE", "MAGANG"):
        return "Trainee"
    if sr in ("TSP", "THAI", "EXPAT", "EXPATRIATE"):
        return "Expatriate"
    return status_raw[:50]


def find_header_col(headers: Dict[int, str], keywords: List[str]) -> Optional[int]:
    for col_idx, h in headers.items():
        hl = h.lower()
        for kw in keywords:
            if kw.lower() in hl:
                return col_idx
    return None


def parse_employee_sheet(
    sheet: Any,
    sheet_name: str,
    default_emp_status: str = "active",
) -> List[Dict[str, Any]]:
    """Parse employee sheet flexibly by header row."""
    # Find header row (check rows 1 to 12)
    header_row_idx = 2
    headers: Dict[int, str] = {}
    for r in range(1, 13):
        h_cand = {}
        for c in range(1, sheet.max_column + 1):
            v = sheet.cell(r, c).value
            if v:
                h_cand[c] = str(v).replace("\n", " ").strip()
        text_row = " ".join(h_cand.values()).lower()
        if "name" in text_row or "payroll" in text_row or "department" in text_row:
            header_row_idx = r
            headers = h_cand
            break

    if not headers:
        logger.warning("Header tidak ditemukan di sheet %s", sheet_name)
        return []

    # Map column names
    col_id = find_header_col(headers, ["payroll id", "payroll", "id"])
    col_seq = find_header_col(headers, ["no", "no."])
    col_name = find_header_col(headers, ["name", "nama"])
    col_dept = find_header_col(headers, ["department", "departemen"])
    col_position = find_header_col(headers, ["position", "jabatan"])
    col_status = find_header_col(headers, ["status employee", "status"])
    col_plant = find_header_col(headers, ["plant"])
    col_joint_date = find_header_col(headers, ["joint date", "hire date", "join date"])
    col_ktp = find_header_col(headers, ["no. ktp", "ktp", "nik", "passport"])
    col_pob = find_header_col(headers, ["place of birth", "tempat lahir"])
    col_dob = find_header_col(headers, ["birth date", "tgl lahir", "tanggal lahir"])
    col_age = find_header_col(headers, ["age", "usia", "umur"])
    col_gender = find_header_col(headers, ["gender", "jenis kelamin"])
    col_kawin = find_header_col(headers, ["status kawin", "marital"])
    col_addr = find_header_col(headers, ["address", "alamat"])
    col_city = find_header_col(headers, ["city", "kota"])
    col_prov = find_header_col(headers, ["province", "provinsi"])
    col_edu = find_header_col(headers, ["education", "pendidikan"])
    col_major = find_header_col(headers, ["major", "jurusan"])
    col_school = find_header_col(headers, ["school name", "sekolah", "universitas"])
    col_phone = find_header_col(headers, ["phone no.", "phone", "no hp", "no. hp"])
    col_email = find_header_col(headers, ["email"])
    col_remarks = find_header_col(headers, ["remarks", "keterangan"])

    employees = []
    for r in range(header_row_idx + 1, sheet.max_row + 1):
        name = clean_str(sheet.cell(r, col_name).value) if col_name else None
        if not name or name.isdigit() or name.lower() in ("total", "sub total", "none", "nan"):
            continue

        raw_id = clean_str(sheet.cell(r, col_id).value) if col_id else None
        if not raw_id:
            raw_id = clean_str(sheet.cell(r, 2).value) or clean_str(sheet.cell(r, 3).value) or f"EMP-{sheet_name}-{r}"

        emp_id = str(raw_id).strip()

        seq_num = None
        if col_seq:
            seq_num = clean_int(sheet.cell(r, col_seq).value)
        if not seq_num:
            seq_num = r

        joint_dt = clean_date(sheet.cell(r, col_joint_date).value) if col_joint_date else None
        latest_end_dt = None
        for c in range(14, min(31, sheet.max_column + 1)):
            header_text = headers.get(c, "").lower()
            if "end" in header_text:
                end_cand = clean_date(sheet.cell(r, c).value)
                if end_cand:
                    if not latest_end_dt or end_cand > latest_end_dt:
                        latest_end_dt = end_cand

        dept = clean_str(sheet.cell(r, col_dept).value) if col_dept else None
        position = clean_str(sheet.cell(r, col_position).value) if col_position else None
        plant = clean_str(sheet.cell(r, col_plant).value) if col_plant else None
        status_raw = clean_str(sheet.cell(r, col_status).value) if col_status else None
        contract_status = map_contract_status(status_raw)
        if sheet_name.lower() == "trainee":
            contract_status = "Trainee"

        phone = clean_str(sheet.cell(r, col_phone).value) if col_phone else None
        email = clean_str(sheet.cell(r, col_email).value) if col_email else None
        ktp = clean_str(sheet.cell(r, col_ktp).value) if col_ktp else None

        gender_raw = clean_str(sheet.cell(r, col_gender).value) if col_gender else None
        gender = None
        if gender_raw:
            gl = gender_raw.upper()
            if gl.startswith("M") or gl.startswith("L"):
                gender = "Laki-laki"
            elif gl.startswith("F") or gl.startswith("P"):
                gender = "Perempuan"
            else:
                gender = gender_raw

        emp_data = {
            "employee_id": emp_id,
            "sequence_number": seq_num,
            "full_name": name,
            "job_title": position or "Staff",
            "department": dept or "General",
            "work_location": plant or "Plant PT ITSP Karawang",
            "contract_start_date": joint_dt or datetime(2020, 1, 1, tzinfo=timezone.utc),
            "contract_end_date": latest_end_dt,
            "contract_status": contract_status,
            "employee_status": default_emp_status,
            "nik": ktp,
            "birth_place": clean_str(sheet.cell(r, col_pob).value) if col_pob else None,
            "birth_date": clean_date(sheet.cell(r, col_dob).value) if col_dob else None,
            "age": clean_int(sheet.cell(r, col_age).value) if col_age else None,
            "gender": gender,
            "marriage_status": clean_str(sheet.cell(r, col_kawin).value) if col_kawin else None,
            "address_ktp": clean_str(sheet.cell(r, col_addr).value) if col_addr else None,
            "city_ktp": clean_str(sheet.cell(r, col_city).value) if col_city else None,
            "province_ktp": clean_str(sheet.cell(r, col_prov).value) if col_prov else None,
            "last_education": clean_str(sheet.cell(r, col_edu).value) if col_edu else None,
            "major": clean_str(sheet.cell(r, col_major).value) if col_major else None,
            "school_name": clean_str(sheet.cell(r, col_school).value) if col_school else None,
            "phone": phone or "-",
            "email": email or f"{emp_id.replace('.', '').replace('-', '').lower()}@itsp.co.id",
            "notes": clean_str(sheet.cell(r, col_remarks).value) if col_remarks else None,
        }
        employees.append(emp_data)

    logger.info("Sheet [%s]: Terbaca %d data karyawan valid.", sheet_name, len(employees))
    return employees
