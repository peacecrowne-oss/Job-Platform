"""baseline

Establishes the Alembic migration framework itself (STORY-009). Deliberately
a no-op: no ORM models exist yet (that's STORY-010+), so there is no schema to
create. Running `alembic upgrade head` still creates Alembic's own
`alembic_version` tracking table and records this revision as current, which
is what proves the framework actually works against the real database.

Revision ID: 02b03a7430e2
Revises:
Create Date: 2026-08-19 20:06:14.935651

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '02b03a7430e2'
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# Repo convention (STORY-009): every migration must implement a real,
# reversible downgrade() unless downgrading genuinely isn't safe/possible —
# in that case, raise NotImplementedError with a comment explaining why,
# rather than silently leaving an empty function that looks reversible but
# isn't.


def upgrade() -> None:
    pass  # intentional no-op — see module docstring


def downgrade() -> None:
    pass  # intentional no-op — see module docstring
