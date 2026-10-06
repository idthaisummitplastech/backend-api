"""
Migration script: Create departments & sections tables and seed initial data.
Run: python migrate_departments.py
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app.db.session import engine, get_db
from app.models.department import Department, Section
from app.db.base_class import Base

# Create tables
Base.metadata.create_all(bind=engine, tables=[Department.__table__, Section.__table__])
print("[OK] Tables created: departments, sections")

# Seed data
INITIAL_DEPARTMENTS = [
    {"name": "Accounting & Finance", "code": "ACF", "sort_order": 1, "sections": []},
    {"name": "Assembly", "code": "ASM", "sort_order": 2, "sections": ["Assembly Line 1", "Assembly Line 2", "Assembly Final"]},
    {"name": "HQ Office", "code": "HQO", "sort_order": 3, "sections": []},
    {"name": "HR & GA", "code": "HRD", "sort_order": 4, "sections": ["Recruitment", "General Affair", "Payroll"]},
    {"name": "Injection", "code": "INJ", "sort_order": 5, "sections": ["Injection Molding", "Injection QC"]},
    {"name": "Interseat", "code": "INT", "sort_order": 6, "sections": []},
    {"name": "Local Manager", "code": "LM", "sort_order": 7, "sections": []},
    {"name": "Maintenance", "code": "MTC", "sort_order": 8, "sections": ["Electrical", "Mechanical", "Utility"]},
    {"name": "Marketing", "code": "MKT", "sort_order": 9, "sections": []},
    {"name": "Painting", "code": "PNT", "sort_order": 10, "sections": ["Painting Line", "Painting QC"]},
    {"name": "Planning", "code": "PLN", "sort_order": 11, "sections": ["Production Planning", "Material Planning"]},
    {"name": "Production", "code": "PRD", "sort_order": 12, "sections": ["Production Line 1", "Production Line 2"]},
    {"name": "Production Engineering", "code": "PE", "sort_order": 13, "sections": []},
    {"name": "Purchasing", "code": "PUR", "sort_order": 14, "sections": ["Local Purchasing", "Import Purchasing"]},
    {"name": "Quality Assurance", "code": "QA", "sort_order": 15, "sections": ["Incoming QC", "In-Process QC", "Final QC"]},
    {"name": "Rack", "code": "RCK", "sort_order": 16, "sections": []},
    {"name": "SYD & IT", "code": "SYD_IT", "sort_order": 17, "sections": [
        "System Development",
        "IT Infrastructure",
        "Network & Security",
        "ERP & SAP",
        "Software Development",
    ]},
    {"name": "Store", "code": "STR", "sort_order": 18, "sections": ["Finished Goods", "Raw Material", "Spare Part"]},
    {"name": "Thai Manager", "code": "TSP", "sort_order": 19, "sections": []},
    {"name": "Warehouse & Delivery", "code": "WD", "sort_order": 20, "sections": ["Warehouse", "Delivery", "Logistic"]},
]

db = next(get_db())
created = 0
skipped = 0

for dept_data in INITIAL_DEPARTMENTS:
    sections_names = dept_data.pop("sections", [])
    existing = db.query(Department).filter(Department.name == dept_data["name"]).first()
    if existing:
        dept = existing
        skipped += 1
        print(f"  ⏭️  Skipped (exists): {dept.name}")
    else:
        dept = Department(**dept_data)
        db.add(dept)
        db.flush()
        created += 1
        print(f"  ✅ Created dept: {dept.name}")

    # Seed sections
    for i, sec_name in enumerate(sections_names):
        sec_exists = db.query(Section).filter(
            Section.department_id == dept.id,
            Section.name == sec_name
        ).first()
        if not sec_exists:
            sec = Section(department_id=dept.id, name=sec_name, sort_order=i)
            db.add(sec)
            print(f"     + Section: {sec_name}")

db.commit()
print(f"\n🎉 Done! Created {created} departments, skipped {skipped} existing.")
