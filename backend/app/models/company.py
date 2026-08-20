"""Canonical Company model (STORY-011).

Implements exactly what requirement.md's functional requirements name: name,
normalized name/slug, domain, optional metadata. No `website`/`careers_url`/
`description`/`logo_url`/`industry` columns are invented — anything beyond
those four groups belongs in `company_metadata` (JSONB) if and when a
connector actually supplies it, not as a speculative typed column now.

`normalized_name` is read as *one* field ("normalized name/slug"), not two —
a single normalized value that also serves as the natural slug/lookup key.
It is auto-derived from `name` via `normalize_company_name()` and is never
set independently, so the two can never drift out of sync.

The Python attribute is `company_metadata`, not `metadata` — SQLAlchemy's
`DeclarativeBase` reserves `metadata` for the schema's own `MetaData` object,
so using it as a column name would collide with that.

Company resolution/matching logic (looking up or creating a Company row for
a given source's company name) deliberately lives with the connector
framework per this Story's own technical note (STORY-016) — nothing here
does that. `normalize_company_name()` is exposed for STORY-016 to reuse, but
is not called by any ingestion code in this repository yet.
"""

from __future__ import annotations

import datetime
import re
import uuid

from sqlalchemy import DateTime, String, UniqueConstraint, func, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship, validates

from app.db import Base

_TRIVIAL_TRAILING_PUNCTUATION = ".,;:!?"


def normalize_company_name(name: str) -> str:
    """Minimum normalization for exact company-name matching (STORY-011):
    case, whitespace, and trivial trailing punctuation only.

    Deliberately NOT fuzzy matching: no legal-suffix stripping (Inc/LLC/
    Corp), no abbreviation expansion, no typo tolerance. "Acme Inc." and
    "ACME Corporation" are intentionally left distinct.
    """
    normalized = name.strip().lower()
    normalized = re.sub(r"\s+", " ", normalized)
    normalized = normalized.rstrip(_TRIVIAL_TRAILING_PUNCTUATION)
    return normalized


class Company(Base):
    __tablename__ = "companies"
    __table_args__ = (
        UniqueConstraint("normalized_name", name="uq_companies_normalized_name"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )

    name: Mapped[str] = mapped_column(String(500), nullable=False)
    normalized_name: Mapped[str] = mapped_column(String(500), nullable=False)
    domain: Mapped[str | None] = mapped_column(String(255), nullable=True)
    company_metadata: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )

    jobs = relationship("Job", back_populates="company")

    @validates("name")
    def _derive_normalized_name(self, key: str, value: str) -> str:
        self.normalized_name = normalize_company_name(value)
        return value
