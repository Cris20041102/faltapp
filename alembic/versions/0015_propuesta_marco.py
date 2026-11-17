"""qué faltas marcó cada propuesta: al borrarla se quitan solo esas

Revision ID: 0015
Revises: 0014
Create Date: 2026-11-16 18:00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '0015'
down_revision: Union[str, Sequence[str], None] = '0014'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table('proposal_members', schema=None) as batch_op:
        batch_op.add_column(sa.Column('marked', sa.JSON(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table('proposal_members', schema=None) as batch_op:
        batch_op.drop_column('marked')
