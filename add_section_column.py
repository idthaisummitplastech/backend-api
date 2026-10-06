"""Add section column to job_postings table."""
import sys, os
sys.stdout.reconfigure(encoding='utf-8')
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app.db.session import engine
from sqlalchemy import text

with engine.connect() as conn:
    result = conn.execute(text(
        "SELECT column_name FROM information_schema.columns "
        "WHERE table_name='job_postings' AND column_name='section'"
    ))
    exists = result.fetchone()
    if exists:
        print('Column section already exists in job_postings')
    else:
        conn.execute(text('ALTER TABLE job_postings ADD COLUMN section VARCHAR(150)'))
        conn.commit()
        print('Column section added to job_postings')
