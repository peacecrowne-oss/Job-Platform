"""Ashby Connector (STORY-019).

Implements requirement.md's literal functional requirement: a connector
against Ashby's public Job Board API
(https://api.ashbyhq.com/posting-api/job-board/{jobBoardName}), fully
unauthenticated and publicly documented. No pagination: the endpoint
returns the complete job set in a single response.

Field mapping was verified against a real live board during implementation
(board "ashby" -- Ashby's own careers board, 62 real jobs) rather than
implemented from documentation alone: every field name below
(`department`, `team`, `employmentType`, `location`, `secondaryLocations`,
`publishedAt`, `isListed`, `workplaceType`, `jobUrl`, `applyUrl`,
`descriptionHtml`) was confirmed present on real records. No job on that
board carried a `compensation` field -- consistent with requirement.md's
own edge case naming compensation as commonly absent -- so the compensation
mapping below is conservative and shape-matched-or-None, not verified
against a real populated example.

`workplaceType`/`employmentType` are genuinely mappable to Job's
`work_mode`/`employment_type` (unlike Greenhouse, which had no equivalent
field) -- an unrecognized `employmentType` value maps to `"other"`, an
existing, intentional CHECK-constraint value (see job.py) meaning "source
gave something that doesn't fit," not a fabrication. An unrecognized
`workplaceType` maps to `None` (no equivalent open-ended value exists for
`work_mode`).

`secondaryLocations` has no canonical field to map to -- NormalizedJobRecord
has no multi-location field, and adding one isn't literally required by
this Story's AC -- so it's preserved in `raw_metadata` only.

`descriptionHtml` (or `descriptionPlain` as fallback) is stored verbatim in
`description_full` -- untrusted external content, never parsed or
sanitized here (STORY-047's job).

Every request goes through the injected `self.http_client` only -- this
file never imports `urllib`/`requests`/sockets, so STORY-017's policy
enforcement applies to every Ashby request without any extra code here.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from pydantic import BaseModel, Field

from app.connectors.base import BaseConnector, NormalizedJobRecord
from app.connectors.errors import ConnectorConfigError, ConnectorSourceFormatError
from app.connectors.registry import register_connector

_WORKPLACE_TYPE_MAP = {
    "remote": "remote",
    "hybrid": "hybrid",
    "onsite": "on_site",
}

_EMPLOYMENT_TYPE_MAP = {
    "fulltime": "full_time",
    "parttime": "part_time",
    "intern": "internship",
    "internship": "internship",
    "temporary": "temporary",
    "contract": "contract",
    "apprenticeship": "apprenticeship",
}

_COMPENSATION_INTERVAL_MAP = {
    "yearly": "yearly",
    "annual": "yearly",
    "monthly": "monthly",
    "hourly": "hourly",
    "daily": "daily",
    "weekly": "weekly",
}


class AshbyConnectorConfig(BaseModel):
    # Public identifier -- part of a public URL, not a secret.
    job_board_name: str = Field(min_length=1, pattern=r"^[A-Za-z0-9_-]+$")
    # Non-secret; overridable only for testability. Defaults to Ashby's
    # real, documented API host.
    api_base_url: str = "https://api.ashbyhq.com"


def _parse_published_at(value: Any) -> date | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value)).date()
    except ValueError:
        return None


def _map_department(raw_record: dict[str, Any]) -> str | None:
    parts = [
        p for p in (raw_record.get("department"), raw_record.get("team")) if p
    ]
    return ", ".join(parts) if parts else None


def _map_workplace_type(raw_record: dict[str, Any]) -> str | None:
    value = raw_record.get("workplaceType")
    if not value:
        return None
    return _WORKPLACE_TYPE_MAP.get(str(value).lower())


def _map_employment_type(raw_record: dict[str, Any]) -> str | None:
    value = raw_record.get("employmentType")
    if not value:
        return None
    return _EMPLOYMENT_TYPE_MAP.get(str(value).lower(), "other")


def _map_compensation(raw_record: dict[str, Any]) -> dict[str, Any]:
    """Only maps compensation when the structure exactly matches the
    expected minimal shape. Never guesses currency/period; malformed or
    unrecognized shapes leave every field None rather than raising --
    compensation is best-effort, not required for a valid record."""
    empty = {
        "compensation_min": None,
        "compensation_max": None,
        "compensation_currency": None,
        "compensation_period": None,
    }
    compensation = raw_record.get("compensation")
    if not isinstance(compensation, dict):
        return empty
    components = compensation.get("summaryComponents")
    if not isinstance(components, list) or not components:
        return empty
    component = components[0]
    if not isinstance(component, dict):
        return empty

    def _decimal(value: Any) -> Decimal | None:
        if value is None:
            return None
        try:
            return Decimal(str(value))
        except InvalidOperation:
            return None

    interval = component.get("interval")
    period = _COMPENSATION_INTERVAL_MAP.get(str(interval).lower()) if interval else None

    return {
        "compensation_min": _decimal(component.get("minValue")),
        "compensation_max": _decimal(component.get("maxValue")),
        "compensation_currency": component.get("currencyCode"),
        "compensation_period": period,
    }


@register_connector("ashby")
class AshbyConnector(BaseConnector):
    config_model = AshbyConnectorConfig

    def _jobs_url(self) -> str:
        return f"{self.config.api_base_url}/posting-api/job-board/{self.config.job_board_name}"

    def fetch(self) -> Iterator[dict[str, Any]]:
        response = self.http_client.get(self._jobs_url())

        if response.status_code == 404:
            raise ConnectorConfigError(
                f"Ashby job board not found for {self.config.job_board_name!r}",
                context={"status_code": 404},
            )
        if not (200 <= response.status_code < 300):
            raise ConnectorSourceFormatError(
                f"Ashby returned an unexpected status fetching jobs: {response.status_code}",
                context={"status_code": response.status_code},
            )

        try:
            payload = response.json()
        except (json.JSONDecodeError, ValueError) as exc:
            raise ConnectorSourceFormatError(
                f"Ashby response body was not valid JSON: {exc}"
            ) from exc

        jobs = payload.get("jobs") if isinstance(payload, dict) else None
        if not isinstance(jobs, list):
            raise ConnectorSourceFormatError(
                "Ashby response did not contain a 'jobs' list",
                context={"payload_type": type(payload).__name__},
            )

        for job in jobs:
            # Defense in depth: the public endpoint is believed to only
            # ever return listed jobs, but an explicit isListed=False is
            # still honored if it's ever present. Absence of the field is
            # not treated as a signal to exclude.
            if isinstance(job, dict) and job.get("isListed") is False:
                continue
            yield job

    def normalize(self, raw_record: dict[str, Any]) -> NormalizedJobRecord:
        raw_id = raw_record.get("id")
        if raw_id is None:
            raise ConnectorSourceFormatError(
                "Ashby job record is missing required field 'id'",
                context={"raw_record_keys": list(raw_record.keys())},
            )

        description = raw_record.get("descriptionHtml") or raw_record.get("descriptionPlain")

        return NormalizedJobRecord(
            source_job_id=str(raw_id),
            job_title=raw_record.get("title"),
            source_url=raw_record.get("jobUrl"),
            application_url=raw_record.get("applyUrl"),
            description_full=description,
            location_raw=raw_record.get("location"),
            department=_map_department(raw_record),
            work_mode=_map_workplace_type(raw_record),
            employment_type=_map_employment_type(raw_record),
            posting_date=_parse_published_at(raw_record.get("publishedAt")),
            raw_metadata=raw_record,
            **_map_compensation(raw_record),
        )
