"""add source refresh_interval_minutes

STORY-021 — see app/models/source.py for the full rationale (NULL means
"use Settings.default_refresh_interval_minutes"). Autogenerate detected
the new column but not the CHECK constraint (Alembic's default
autogenerate does not diff CHECK constraints) -- added manually below,
matching the model's own `ck_sources_refresh_interval_minutes_positive`.

Revision ID: 6570fa469a9b
Revises: 4a2ec55ea99c
Create Date: 2026-08-25 19:40:35.864677

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '6570fa469a9b'
down_revision: Union[str, None] = '4a2ec55ea99c'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('sources', sa.Column('refresh_interval_minutes', sa.Integer(), nullable=True))
    op.create_check_constraint(
        'ck_sources_refresh_interval_minutes_positive',
        'sources',
        'refresh_interval_minutes IS NULL OR refresh_interval_minutes > 0',
    )


def downgrade() -> None:
    op.drop_constraint('ck_sources_refresh_interval_minutes_positive', 'sources', type_='check')
    op.drop_column('sources', 'refresh_interval_minutes')
