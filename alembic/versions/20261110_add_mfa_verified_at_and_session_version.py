"""add mfa_verified_at, password_changed_at, and session_version

Revision ID: 20261110_mfa_session_fields
Revises: 
Create Date: 2026-11-10 12:00:00.000000

Catatan: File migrasi ini HANYA disiapkan (Amandemen 4).
Urutan eksekusi saat rilis:
1. Backup basis data produksi (web_karir & web_perusahaan).
2. Jalankan `alembic upgrade head` pada kedua database target.
3. Deploy kode backend-api terbaru.
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '20261110_mfa_session_fields'
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    # 1. Update tabel recruitment_admins (web_karir)
    op.add_column('recruitment_admins', sa.Column('mfa_verified_at', sa.DateTime(timezone=True), nullable=True))
    op.add_column('recruitment_admins', sa.Column('password_changed_at', sa.DateTime(timezone=True), nullable=True))
    op.add_column('recruitment_admins', sa.Column('session_version', sa.Integer(), nullable=False, server_default='1'))
    op.add_column('recruitment_admins', sa.Column('totp_failed_attempts', sa.Integer(), nullable=False, server_default='0'))
    op.add_column('recruitment_admins', sa.Column('totp_locked_until', sa.DateTime(timezone=True), nullable=True))
    op.add_column('recruitment_admins', sa.Column('last_used_totp_timestep', sa.Integer(), nullable=True))

    # 2. Update tabel users (web_perusahaan)
    op.add_column('users', sa.Column('mfa_verified_at', sa.DateTime(timezone=True), nullable=True))
    op.add_column('users', sa.Column('password_changed_at', sa.DateTime(timezone=True), nullable=True))
    op.add_column('users', sa.Column('session_version', sa.Integer(), nullable=False, server_default='1'))
    op.add_column('users', sa.Column('totp_failed_attempts', sa.Integer(), nullable=False, server_default='0'))
    op.add_column('users', sa.Column('totp_locked_until', sa.DateTime(timezone=True), nullable=True))
    op.add_column('users', sa.Column('last_used_totp_timestep', sa.Integer(), nullable=True))


def downgrade():
    # Downgrade users
    op.drop_column('users', 'last_used_totp_timestep')
    op.drop_column('users', 'totp_locked_until')
    op.drop_column('users', 'totp_failed_attempts')
    op.drop_column('users', 'session_version')
    op.drop_column('users', 'password_changed_at')
    op.drop_column('users', 'mfa_verified_at')

    # Downgrade recruitment_admins
    op.drop_column('recruitment_admins', 'last_used_totp_timestep')
    op.drop_column('recruitment_admins', 'totp_locked_until')
    op.drop_column('recruitment_admins', 'totp_failed_attempts')
    op.drop_column('recruitment_admins', 'session_version')
    op.drop_column('recruitment_admins', 'password_changed_at')
    op.drop_column('recruitment_admins', 'mfa_verified_at')

