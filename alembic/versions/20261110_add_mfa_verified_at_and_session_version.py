"""add mfa_verified_at, password_changed_at, and session_version

Revision ID: 20261110_mfa_session_fields
Revises: 
Create Date: 2026-11-10 12:00:00.000000

Catatan Multi-Database:
File migrasi ini aman dijalankan terpisah untuk DATABASE_URL (Career DB)
maupun DATABASE_COMPANY_URL (Company DB). Script secara otomatis mendeteksi
keberadaan tabel target sebelum menjalankan penambahan/penghapusan kolom.

Perintah Eksekusi Rilis (Terpisah):
1. Career DB (web_karir):
   DATABASE_URL="<CAREER_DB_DSN>" alembic upgrade head
2. Company DB (web_perusahaan):
   DATABASE_URL="<COMPANY_DB_DSN>" alembic upgrade head
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '20261110_mfa_session_fields'
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = inspector.get_table_names()

    # 1. Update tabel recruitment_admins (khusus basis data web_karir)
    if 'recruitment_admins' in tables:
        existing_cols = [c['name'] for c in inspector.get_columns('recruitment_admins')]
        if 'mfa_verified_at' not in existing_cols:
            op.add_column('recruitment_admins', sa.Column('mfa_verified_at', sa.DateTime(timezone=True), nullable=True))
        if 'password_changed_at' not in existing_cols:
            op.add_column('recruitment_admins', sa.Column('password_changed_at', sa.DateTime(timezone=True), nullable=True))
        if 'session_version' not in existing_cols:
            op.add_column('recruitment_admins', sa.Column('session_version', sa.Integer(), nullable=False, server_default='1'))
        if 'totp_failed_attempts' not in existing_cols:
            op.add_column('recruitment_admins', sa.Column('totp_failed_attempts', sa.Integer(), nullable=False, server_default='0'))
        if 'totp_locked_until' not in existing_cols:
            op.add_column('recruitment_admins', sa.Column('totp_locked_until', sa.DateTime(timezone=True), nullable=True))
        if 'last_used_totp_timestep' not in existing_cols:
            op.add_column('recruitment_admins', sa.Column('last_used_totp_timestep', sa.Integer(), nullable=True))

    # 2. Update tabel users (khusus basis data web_perusahaan)
    if 'users' in tables:
        existing_cols = [c['name'] for c in inspector.get_columns('users')]
        if 'mfa_verified_at' not in existing_cols:
            op.add_column('users', sa.Column('mfa_verified_at', sa.DateTime(timezone=True), nullable=True))
        if 'password_changed_at' not in existing_cols:
            op.add_column('users', sa.Column('password_changed_at', sa.DateTime(timezone=True), nullable=True))
        if 'session_version' not in existing_cols:
            op.add_column('users', sa.Column('session_version', sa.Integer(), nullable=False, server_default='1'))
        if 'totp_failed_attempts' not in existing_cols:
            op.add_column('users', sa.Column('totp_failed_attempts', sa.Integer(), nullable=False, server_default='0'))
        if 'totp_locked_until' not in existing_cols:
            op.add_column('users', sa.Column('totp_locked_until', sa.DateTime(timezone=True), nullable=True))
        if 'last_used_totp_timestep' not in existing_cols:
            op.add_column('users', sa.Column('last_used_totp_timestep', sa.Integer(), nullable=True))


def downgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = inspector.get_table_names()

    if 'users' in tables:
        cols = [c['name'] for c in inspector.get_columns('users')]
        for c in ['last_used_totp_timestep', 'totp_locked_until', 'totp_failed_attempts', 'session_version', 'password_changed_at', 'mfa_verified_at']:
            if c in cols:
                op.drop_column('users', c)

    if 'recruitment_admins' in tables:
        cols = [c['name'] for c in inspector.get_columns('recruitment_admins')]
        for c in ['last_used_totp_timestep', 'totp_locked_until', 'totp_failed_attempts', 'session_version', 'password_changed_at', 'mfa_verified_at']:
            if c in cols:
                op.drop_column('recruitment_admins', c)
