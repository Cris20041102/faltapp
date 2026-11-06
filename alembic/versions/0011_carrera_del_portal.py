"""la carrera viene del portal (Phoenix): nombres de hasta 120 caracteres

Revision ID: 0011
Revises: 0010
Create Date: 2026-11-06 21:00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '0011'
down_revision: Union[str, Sequence[str], None] = '0010'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table('users', schema=None) as batch_op:
        batch_op.alter_column('career', type_=sa.String(length=120), existing_type=sa.String(length=60),
                              existing_nullable=False, existing_server_default='')


def downgrade() -> None:
    with op.batch_alter_table('users', schema=None) as batch_op:
        batch_op.alter_column('career', type_=sa.String(length=60), existing_type=sa.String(length=120),
                              existing_nullable=False, existing_server_default='')
