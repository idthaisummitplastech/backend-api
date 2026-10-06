"""
Script untuk meng-update nama departemen dan mengisi section pada lowongan kerja lama
agar sinkron dengan 20 daftar Departemen & Section resmi yang baru.

Jalankan di server:
    venv\Scripts\python.exe update_job_departments.py
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from sqlalchemy import text
from app.db.session import engine, get_db
from app.models.recruitment import JobPosting, TestQuestion

def run_update():
    db = next(get_db())
    print("=" * 60)
    print("MEMULAI UPDATE DEPARTEMEN & SECTION")
    print("=" * 60)

    # 1. Update Job Postings
    jobs = db.query(JobPosting).all()
    print(f"\nDitemukan {len(jobs)} lowongan pekerjaan:")
    
    for job in jobs:
        old_dept = job.department
        old_sec = job.section
        title_lower = job.title.lower()
        dept_lower = (job.department or "").lower()

        # Mapping rule berdasarkan judul & departemen lama
        if "it & enterprise" in title_lower or "information technology" in dept_lower or dept_lower == "it":
            job.department = "SYD & IT"
            job.section = "IT Infrastructure"
        elif "mold maintenance" in title_lower or "engineering & tooling" in dept_lower:
            job.department = "Maintenance"
            job.section = "Mechanical"
        elif "quality control" in title_lower or "qc line" in title_lower:
            job.department = "Quality Assurance"
            job.section = "In-Process QC"
        elif "plastic injection" in title_lower or "injection molding" in title_lower:
            job.department = "Production"
            job.section = "Production Line 1"
        elif "hse" in title_lower or "hse" in dept_lower:
            job.department = "HR & GA"
            job.section = "General Affair"

        print(f"  [{job.id}] {job.title}")
        print(f"      Dept: '{old_dept}' -> '{job.department}'")
        print(f"      Section: '{old_sec}' -> '{job.section}'")

    # 2. Update Test Questions (jika ada)
    questions = db.query(TestQuestion).filter(TestQuestion.department.isnot(None)).all()
    if questions:
        print(f"\nMemeriksa {len(questions)} soal tes...")
        for q in questions:
            qd = (q.department or "").strip().lower()
            if qd in ["it", "information technology"]:
                q.department = "SYD & IT"
            elif qd in ["engineering", "engineering & tooling"]:
                q.department = "Maintenance"

    # 3. Update recruitment_admins jika ada yang departemennya Information Technology
    try:
        with engine.begin() as conn:
            conn.execute(text("UPDATE recruitment_admins SET department = 'SYD & IT' WHERE department IN ('Information Technology', 'IT')"))
            conn.execute(text("UPDATE recruitment_admins SET department = 'Maintenance' WHERE department = 'Engineering & Tooling'"))
            print("\n[OK] Tabel recruitment_admins diperbarui.")
    except Exception as e:
        print(f"\n[Info] Update recruitment_admins dilewati: {e}")

    # 4. Update data_karyawan jika ada yang departemennya Information Technology / Engineering
    try:
        with engine.begin() as conn:
            conn.execute(text("UPDATE data_karyawan SET department = 'SYD & IT' WHERE department IN ('Information Technology', 'IT') OR department ILIKE '%Information Technology%'"))
            conn.execute(text("UPDATE data_karyawan SET department = 'Maintenance' WHERE department IN ('Engineering & Tooling', 'Engineering') OR department ILIKE '%Engineering%'"))
            print("[OK] Tabel data_karyawan diperbarui.")
    except Exception as e:
        print(f"[Info] Update data_karyawan dilewati: {e}")

    db.commit()
    print("\n" + "=" * 60)
    print("SELESAI! Semua departemen & section telah diperbarui.")
    print("=" * 60)

if __name__ == "__main__":
    run_update()
