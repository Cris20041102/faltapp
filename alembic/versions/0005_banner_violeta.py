"""banner por defecto con el violeta del nuevo estilo

Revision ID: 0005
Revises: 0004
Create Date: 2026-10-04 21:45:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '0005'
down_revision: Union[str, Sequence[str], None] = '0004'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # el índigo deja de ser parte de la paleta: los banners con el color por defecto antiguo pasan al violeta
    op.execute("UPDATE users SET banner_color = '#713dff' WHERE banner_color = '#4f46e5'")
    with op.batch_alter_table('users', schema=None) as batch_op:
        batch_op.alter_column('banner_color', existing_type=sa.String(length=7), server_default='#713dff')


def downgrade() -> None:
    with op.batch_alter_table('users', schema=None) as batch_op:
        batch_op.alter_column('banner_color', existing_type=sa.String(length=7), server_default='#4f46e5')
    op.execute("UPDATE users SET banner_color = '#4f46e5' WHERE banner_color = '#713dff'")
