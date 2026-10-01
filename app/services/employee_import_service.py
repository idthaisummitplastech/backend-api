"""
Employee Import Service for PT Indonesia Thai Summit Plastech
Parses Excel sheets (ITSP, Trainee, Out) into structured employee data.
Captures full contract history, years of service, age, level, section, and employee types.
"""

import json
import logging
from datetime import datetime, timezone
from typing import Any, Dict, Optional, List

logger = logging.getLogger("employee_import_service")


def clean_str(val: Any) -> Optional[str]:
    if val is None:
        return None
    s = str(val).strip()
    return s if s and s not in ("0", "-", "none", "nan", "null") else None


def clean_date(val: Any) -> Optional[datetime]:
    if val is None:
        return None
    if isinstance(val, datetime):
        if val.tzinfo is None:
            return val.replace(tzinfo=timezone.utc)
        return val
    try:
        s = str(val).strip()
        if not s or s.lower() in ("none", "null", "-", "#n/a", "0"):
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


def clean_float(val: Any) -> Optional[float]:
    if val is None:
        return None
    try:
        return round(float(str(val).strip()), 2)
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
    col_id = find_header_col(headers, ["id"])
    col_payroll_id = find_header_col(headers, ["payroll id", "payroll"])
    col_seq = find_header_col(headers, ["no", "no."])
    col_name = find_header_col(headers, ["name", "nama"])
    col_level = find_header_col(headers, ["level"])
    col_dept = find_header_col(headers, ["department", "departemen"])
    col_section = find_header_col(headers, ["section", "seksi"])
    col_position = find_header_col(headers, ["position", "jabatan"])
    col_status = find_header_col(headers, ["status employee", "status"])
    col_plant = find_header_col(headers, ["plant"])
    col_type = find_header_col(headers, ["type"])
    col_factory = find_header_col(headers, ["factory", "office"])
    col_joint_date = find_header_col(headers, ["joint date", "hire date", "join date"])
    col_yos = find_header_col(headers, ["years of service", "years of\nservice", "yos", "masa kerja"])
    col_ktp = find_header_col(headers, ["no. ktp", "ktp", "nik", "passport"])
    col_pob = find_header_col(headers, ["place of birth", "tempat lahir"])
    col_dob = find_header_col(headers, ["birth date", "tgl lahir", "tanggal lahir"])
    col_age = find_header_col(headers, ["age", "usia", "umur"])
    col_gender = find_header_col(headers, ["gender", "jenis kelamin"])
    col_kawin = find_header_col(headers, ["status kawin", "marital", "ptkp"])
    col_addr = find_header_col(headers, ["address", "alamat"])
    col_city = find_header_col(headers, ["city", "kota"])
    col_prov = find_header_col(headers, ["province", "provinsi"])
    col_edu = find_header_col(headers, ["education", "pendidikan"])
    col_major = find_header_col(headers, ["major", "jurusan"])
    col_school = find_header_col(headers, ["school name", "sekolah", "universitas"])
    col_phone = find_header_col(headers, ["phone no.", "phone", "no hp", "no. hp"])
    col_email = find_header_col(headers, ["email"])
    col_npwp = find_header_col(headers, ["npwp"])
    col_bpjs_tk = find_header_col(headers, ["jamsostek", "bpjs ketenagakerjaan", "kpj"])
    col_bank_acc = find_header_col(headers, ["account no.", "account no", "rekening"])
    col_mother = find_header_col(headers, ["name of mother", "mother", "ibu"])
    col_father = find_header_col(headers, ["name of father", "father", "ayah"])
    col_spouse = find_header_col(headers, ["husband/wife name", "husband", "wife", "suami", "istri", "pasangan"])
    col_family_count = find_header_col(headers, ["number of family member", "family member", "tanggungan"])
    col_remarks = find_header_col(headers, ["remarks", "keterangan"])

    # Detect Sibling and Children columns (often merged on row 1)
    sibling_cols: List[int] = []
    children_cols: List[int] = []
    for c in range(1, sheet.max_column + 1):
        h1 = str(sheet.cell(1, c).value or "").lower()
        if "sibling" in h1:
            sibling_cols = [c, c + 1, c + 2, c + 3]
        if "children" in h1:
            children_cols = [c, c + 1, c + 2]

    # Fallback to standard sheet positions if not detected from headers
    if not sibling_cols:
        sibling_cols = [56, 57, 58, 59] if sheet_name.lower() != "trainee" else [54, 55, 56, 57]
    if not children_cols:
        children_cols = [62, 63, 64] if sheet_name.lower() != "trainee" else [60, 61, 62]

    employees = []
    for r in range(header_row_idx + 1, sheet.max_row + 1):
        name = clean_str(sheet.cell(r, col_name).value) if col_name else None
        if not name or name.isdigit() or name.lower() in ("total", "sub total", "none", "nan"):
            continue

        raw_id_col2 = clean_str(sheet.cell(r, 2).value)
        raw_id_col3 = clean_str(sheet.cell(r, 3).value)

        if sheet_name.lower() == "trainee":
            # For trainees, Col 3 is N-012507139 (company trainee ID)
            emp_id = raw_id_col3 or (f"TR-{raw_id_col2}" if raw_id_col2 else f"TR-{r}")
            payroll_id_val = raw_id_col3
        else:
            # For ITSP employees, Col 2 is ID (004.02.16) and Col 3 is Payroll ID (ITSP.004.02.16)
            emp_id = raw_id_col2 or raw_id_col3 or f"EMP-{r}"
            payroll_id_val = raw_id_col3

        seq_num = None
        if col_seq:
            seq_num = clean_int(sheet.cell(r, col_seq).value)
        if not seq_num:
            seq_num = r

        joint_dt = clean_date(sheet.cell(r, col_joint_date).value) if col_joint_date else None

        # Parse contract history across contract columns (Cols 15 to 30)
        contracts = []
        c_seq = 1
        latest_contract_start = None
        latest_contract_end = None

        max_contract_col = 25 if sheet_name.lower() == "trainee" else 31
        for c in range(15, min(max_contract_col, sheet.max_column + 1), 2):
            st = clean_date(sheet.cell(r, c).value)
            en = clean_date(sheet.cell(r, c + 1).value)
            if st or en:
                num = (c - 15) // 2 + 1
                c_seq = num
                contracts.append({
                    "sequence": num,
                    "contract_name": f"Kontrak {num}",
                    "start_date": st.isoformat()[:10] if st else None,
                    "end_date": en.isoformat()[:10] if en else None,
                })
                if st:
                    latest_contract_start = st
                if en:
                    latest_contract_end = en

        dept = clean_str(sheet.cell(r, col_dept).value) if col_dept else None
        section = clean_str(sheet.cell(r, col_section).value) if col_section else None
        level = clean_str(sheet.cell(r, col_level).value) if col_level else None
        position = clean_str(sheet.cell(r, col_position).value) if col_position else None
        plant = clean_str(sheet.cell(r, col_plant).value) if col_plant else None
        emp_type = clean_str(sheet.cell(r, col_type).value) if col_type else None
        factory_office = clean_str(sheet.cell(r, col_factory).value) if col_factory else None

        # Status & sequence formatting
        status_raw = clean_str(sheet.cell(r, col_status).value) if col_status else None
        base_status = map_contract_status(status_raw)

        if sheet_name.lower() == "trainee":
            contract_status = f"Trainee {c_seq}" if c_seq > 1 else "Trainee"
        elif base_status == "PKWTT":
            contract_status = "PKWTT"
        elif base_status == "Expatriate":
            contract_status = "Expatriate"
        elif base_status == "PKWT":
            contract_status = f"PKWT {c_seq}"
        else:
            contract_status = base_status

        # Years of service
        yos_val = clean_float(sheet.cell(r, col_yos).value) if col_yos else None
        if yos_val is None and joint_dt:
            yos_val = round((datetime.now(timezone.utc) - joint_dt).days / 365.25, 2)

        # Age & Date of Birth
        dob = clean_date(sheet.cell(r, col_dob).value) if col_dob else None
        age_val = clean_int(sheet.cell(r, col_age).value) if col_age else None
        if age_val is None and dob:
            age_val = int((datetime.now(timezone.utc) - dob).days / 365.25)

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

        # Family data
        father = clean_str(sheet.cell(r, col_father).value) if col_father else None
        mother = clean_str(sheet.cell(r, col_mother).value) if col_mother else None
        spouse = clean_str(sheet.cell(r, col_spouse).value) if col_spouse else None

        parents = []
        if father and father != "0":
            parents.append({"relation": "Ayah", "name": father})
        if mother and mother != "0":
            parents.append({"relation": "Ibu", "name": mother})

        siblings_list = []
        for sc in sibling_cols:
            if sc <= sheet.max_column:
                sv = clean_str(sheet.cell(r, sc).value)
                if sv and sv != "0":
                    siblings_list.append(sv)

        children_list = []
        for cc in children_cols:
            if cc <= sheet.max_column:
                cv = clean_str(sheet.cell(r, cc).value)
                if cv and cv != "0":
                    children_list.append(cv)

        fam_count = clean_int(sheet.cell(r, col_family_count).value) if col_family_count else 0
        ptkp_val = clean_str(sheet.cell(r, col_kawin).value) if col_kawin else None
        npwp_val = clean_str(sheet.cell(r, col_npwp).value) if col_npwp else None
        bpjs_tk_val = clean_str(sheet.cell(r, col_bpjs_tk).value) if col_bpjs_tk else None
        bank_acc_val = clean_str(sheet.cell(r, col_bank_acc).value) if col_bank_acc else None

        emp_data = {
            "employee_id": emp_id,
            "payroll_id": payroll_id_val,
            "sequence_number": seq_num,
            "full_name": name,
            "job_title": position or "Staff",
            "department": dept or "General",
            "section": section,
            "level": level,
            "plant": plant or "KIIC",
            "work_location": plant or "Plant PT ITSP Karawang",
            "employee_type": emp_type,
            "factory_office": factory_office,
            "contract_start_date": latest_contract_start or joint_dt or datetime(2020, 1, 1, tzinfo=timezone.utc),
            "contract_end_date": latest_contract_end,
            "contract_status": contract_status,
            "contract_sequence": c_seq,
            "contract_history": json.dumps(contracts) if contracts else None,
            "years_of_service": yos_val,
            "employee_status": default_emp_status,
            "nik": ktp,
            "birth_place": clean_str(sheet.cell(r, col_pob).value) if col_pob else None,
            "birth_date": dob,
            "age": age_val,
            "gender": gender,
            "marriage_status": ptkp_val,
            "ptkp_status": ptkp_val,
            "address_ktp": clean_str(sheet.cell(r, col_addr).value) if col_addr else None,
            "city_ktp": clean_str(sheet.cell(r, col_city).value) if col_city else None,
            "province_ktp": clean_str(sheet.cell(r, col_prov).value) if col_prov else None,
            "last_education": clean_str(sheet.cell(r, col_edu).value) if col_edu else None,
            "major": clean_str(sheet.cell(r, col_major).value) if col_major else None,
            "school_name": clean_str(sheet.cell(r, col_school).value) if col_school else None,
            "phone": phone or "-",
            "email": email or f"{emp_id.replace('.', '').replace('-', '').lower()}@itsp.co.id",
            "npwp": npwp_val,
            "npwp_file": npwp_val,
            "bpjs_tk_no": bpjs_tk_val,
            "bpjs_ketenagakerjaan_file": bpjs_tk_val,
            "bank_account_no": bank_acc_val,
            "bank_name": "BCA",
            "father_name": father if father != "0" else None,
            "mother_name": mother if mother != "0" else None,
            "spouse_name": spouse if spouse != "0" else None,
            "family_parents": json.dumps(parents) if parents else None,
            "family_siblings": json.dumps(siblings_list) if siblings_list else None,
            "family_children": json.dumps(children_list) if children_list else None,
            "family_members_count": fam_count,
            "notes": clean_str(sheet.cell(r, col_remarks).value) if col_remarks else None,
        }
        employees.append(emp_data)

    logger.info("Sheet [%s]: Terbaca %d data karyawan valid.", sheet_name, len(employees))
    return employees
