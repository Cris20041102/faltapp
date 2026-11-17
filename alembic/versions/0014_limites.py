"""intentos y correos recientes en la BD: el límite sobrevive reinicios

Revision ID: 0014
Revises: 0013
Create Date: 2026-11-16 12:00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '0014'
down_revision: Union[str, Sequence[str], None] = '0013'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table('rate_limits',
                    sa.Column('key', sa.String(length=80), nullable=False),
                    sa.Column('times', sa.JSON(), nullable=False),
                    sa.PrimaryKeyConstraint('key'))


def downgrade() -> None:
    op.drop_table('rate_limits')
