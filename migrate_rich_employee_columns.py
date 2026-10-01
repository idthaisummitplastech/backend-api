import sys
from app.db.session import SessionLocal
from sqlalchemy import text

db = SessionLocal()

alter_queries = [
    "ALTER TABLE data_karyawan ADD COLUMN IF NOT EXISTS payroll_id VARCHAR(50);",
    "ALTER TABLE data_karyawan ADD COLUMN IF NOT EXISTS plant VARCHAR(50);",
    "ALTER TABLE data_karyawan ADD COLUMN IF NOT EXISTS ptkp_status VARCHAR(20);",
    "ALTER TABLE data_karyawan ADD COLUMN IF NOT EXISTS npwp VARCHAR(50);",
    "ALTER TABLE data_karyawan ADD COLUMN IF NOT EXISTS bpjs_tk_no VARCHAR(50);",
    "ALTER TABLE data_karyawan ADD COLUMN IF NOT EXISTS bank_account_no VARCHAR(50);",
    "ALTER TABLE data_karyawan ADD COLUMN IF NOT EXISTS bank_name VARCHAR(50) DEFAULT 'BCA';",
    "ALTER TABLE data_karyawan ADD COLUMN IF NOT EXISTS father_name VARCHAR(150);",
    "ALTER TABLE data_karyawan ADD COLUMN IF NOT EXISTS mother_name VARCHAR(150);",
    "ALTER TABLE data_karyawan ADD COLUMN IF NOT EXISTS spouse_name VARCHAR(150);",
    "ALTER TABLE data_karyawan ADD COLUMN IF NOT EXISTS family_children TEXT;",
    "ALTER TABLE data_karyawan ADD COLUMN IF NOT EXISTS family_members_count INTEGER DEFAULT 0;",
]

for q in alter_queries:
    try:
        db.execute(text(q))
        print("Executed:", q)
    except Exception as e:
        print("Error on:", q, e)

db.commit()
print("All rich employee columns migrated successfully!")
db.close()
