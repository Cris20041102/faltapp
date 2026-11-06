"""código de recuperación de la cuenta (solo su hash)

Revision ID: 0012
Revises: 0011
Create Date: 2026-11-06 12:00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '0012'
down_revision: Union[str, Sequence[str], None] = '0011'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table('users', schema=None) as batch_op:
        batch_op.add_column(sa.Column('recovery_hash', sa.String(length=200), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table('users', schema=None) as batch_op:
        batch_op.drop_column('recovery_hash')
