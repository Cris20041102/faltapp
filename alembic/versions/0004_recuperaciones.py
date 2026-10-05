"""recuperaciones

Revision ID: 0004
Revises: 0003
Create Date: 2026-10-04 21:30:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '0004'
down_revision: Union[str, Sequence[str], None] = '0003'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table('makeups',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('course_id', sa.Integer(), nullable=False),
    sa.Column('original', sa.Date(), nullable=False),
    sa.Column('date', sa.Date(), nullable=False),
    sa.ForeignKeyConstraint(['course_id'], ['courses.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('makeups', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_makeups_course_id'), ['course_id'], unique=False)


def downgrade() -> None:
    with op.batch_alter_table('makeups', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_makeups_course_id'))
    op.drop_table('makeups')
