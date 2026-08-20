"""Connector contract (STORY-016).

Implements requirement.md's literal functional requirement: "Abstract base
connector defining fetch() / normalize() / validate() steps; ... per-
connector configuration schema." Three sequential steps per record: fetch()
returns raw source records, normalize() shapes one into the canonical
intermediate representation (`NormalizedJobRecord`), validate() is a
connector-owned, overridable sanity check on the normalized result — NOT
STORY-027's shared, cross-connector data-quality gate (required title/
company/source_url, sanity checks), which is a separate, later, pipeline-
wide step. This distinction was flagged in the approved plan and implemented
as presented.

No concrete `HttpClient` implementation ships here — only the Protocol.
STORY-017's own acceptance criterion is "a connector cannot make outbound
requests without going through the policy-enforcing client"; shipping a
working (unenforced) client here would let a connector make real, unvetted
requests before STORY-017 exists. Since no real connector exists yet either
(Greenhouse/Ashby are STORY-018/019), leaving this unimplemented costs
nothing now and guarantees the only way a future connector reaches the
network is through whatever client STORY-017 supplies.

Secrets convention (documentation only — nothing to enforce yet, since no
real connector needs a secret): a connector's `config_model` should hold a
*reference* to a credential, e.g. `api_token_env_var: str` naming an
environment variable to resolve at runtime via `os.environ`, never the
literal secret value — `Source.config` is a plain JSONB column, visible to
anyone who can query the database.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Iterator, Mapping
from datetime import date, datetime
from decimal import Decimal
from typing import Any, ClassVar, Protocol

from pydantic import BaseModel

from app.connectors.errors import ConnectorConfigError


class NormalizedJobRecord(BaseModel):
    """Canonical intermediate representation a connector produces from one
    raw source record — not persisted directly; the shared ingestion
    pipeline (a later Story) is what turns this into a `Job` row.

    Mirrors `Job`'s ingestion-relevant columns exactly, excluding `id`,
    `company_id`, `source`, `created_at`/`updated_at`, `first_seen_at`/
    `last_seen_at` (persistence-layer concerns) and `content_hash`
    (computed centrally by the shared pipeline so the hash algorithm stays
    consistent regardless of which connector produced the record).

    Only `source_job_id` is required ("stable source-job identity"); every
    other field defaults to `None` — nothing is fabricated. `unknown` is not
    used as a value anywhere here, consistent with STORY-010's own
    precedent that no canonical job field uses `unknown` as a controlled
    value; `None` is the only representation of absent/unclassified data.
    """

    source_job_id: str

    job_title: str | None = None
    company_name: str | None = None
    source_url: str | None = None

    description_full: str | None = None
    responsibilities: str | None = None
    requirements: str | None = None
    preferred_requirements: str | None = None
    qualifications: str | None = None

    skills: list[str] | None = None
    skills_raw: str | None = None

    location_raw: str | None = None
    location_city: str | None = None
    location_region: str | None = None
    location_country: str | None = None

    work_mode: str | None = None
    employment_type: str | None = None
    seniority: str | None = None
    department: str | None = None

    compensation_min: Decimal | None = None
    compensation_max: Decimal | None = None
    compensation_currency: str | None = None
    compensation_period: str | None = None

    benefits: list[str] | None = None

    posting_date: date | None = None
    closing_date: date | None = None
    application_url: str | None = None
    source_updated_at: datetime | None = None

    raw_metadata: dict[str, Any] | None = None


class HttpResponse(Protocol):
    """The minimum shape a connector needs from an HTTP response, regardless
    of which concrete HTTP client implementation eventually supplies it."""

    status_code: int
    headers: Mapping[str, str]

    def json(self) -> Any: ...

    @property
    def text(self) -> str: ...


class HttpClient(Protocol):
    """Injected into every connector's constructor — the *only* seam
    through which a connector may reach the network. No implementation of
    this Protocol ships in STORY-016; see module docstring."""

    def get(
        self,
        url: str,
        *,
        params: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
        timeout: float | None = None,
    ) -> HttpResponse: ...


class BaseConnector(ABC):
    """Abstract base every connector implements. Adding a new connector
    means writing one subclass and registering it (see registry.py) — no
    change to this file, `registry.py`, or any orchestration code, per this
    Story's own acceptance criterion.
    """

    connector_type: ClassVar[str]
    config_model: ClassVar[type[BaseModel]]

    def __init__(self, config: dict[str, Any], http_client: HttpClient) -> None:
        try:
            self.config = self.config_model.model_validate(config)
        except Exception as exc:  # pydantic.ValidationError, narrowed to one error type
            raise ConnectorConfigError(
                f"Invalid configuration for connector type {self.connector_type!r}: {exc}"
            ) from exc
        self.http_client = http_client

    @abstractmethod
    def fetch(self) -> Iterator[dict[str, Any]]:
        """Yield raw source records. Pagination, if any, is handled
        internally by the connector using `self.http_client` — not a
        separate interface method, since pagination styles vary too much
        across sources to standardize now."""
        raise NotImplementedError

    @abstractmethod
    def normalize(self, raw_record: dict[str, Any]) -> NormalizedJobRecord:
        """Convert one raw record into the canonical intermediate shape."""
        raise NotImplementedError

    def validate(self, record: NormalizedJobRecord) -> bool:
        """Connector-owned sanity check on a normalized record. Default:
        require a non-empty `source_job_id`. Override for source-specific
        structural checks; this is not STORY-027's shared validation gate."""
        return bool(record.source_job_id)
