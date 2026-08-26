"""add job closed_at and source freshness threshold

STORY-028 -- see app/models/job.py and app/models/source.py for the full
rationale. Autogenerate detected both new columns but not the CHECK
constraint on freshness_threshold_runs (Alembic's default autogenerate
does not diff CHECK constraints) -- added manually below, matching the
model's own `ck_sources_freshness_threshold_runs_positive`.

Revision ID: 8df3a134d9ed
Revises: 6570fa469a9b
Create Date: 2026-08-26 18:49:37.507449

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '8df3a134d9ed'
down_revision: Union[str, None] = '6570fa469a9b'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('jobs', sa.Column('closed_at', sa.DateTime(timezone=True), nullable=True))
    op.add_column('sources', sa.Column('freshness_threshold_runs', sa.Integer(), nullable=True))
    op.create_check_constraint(
        'ck_sources_freshness_threshold_runs_positive',
        'sources',
        'freshness_threshold_runs IS NULL OR freshness_threshold_runs > 0',
    )


def downgrade() -> None:
    op.drop_constraint('ck_sources_freshness_threshold_runs_positive', 'sources', type_='check')
    op.drop_column('sources', 'freshness_threshold_runs')
    op.drop_column('jobs', 'closed_at')
