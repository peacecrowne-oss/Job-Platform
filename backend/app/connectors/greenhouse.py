"""Greenhouse Connector (STORY-018).

Implements requirement.md's literal functional requirement: a connector
against Greenhouse's public Job Board API
(https://boards-api.greenhouse.io/v1/boards/{board_token}/jobs), fully
unauthenticated and publicly documented -- the same interface a Greenhouse-
hosted careers page (boards.greenhouse.io/<board_token>) itself calls to
render listings. No pagination: the list endpoint returns the complete job
set in a single response.

Field mapping is deliberately conservative -- see the approved plan for the
full table. Anything Greenhouse's base API doesn't reliably/consistently
provide (company_name, structured responsibilities/requirements/
qualifications sections, skills, structured location components, work_mode,
employment_type, seniority, compensation, benefits, posting/closing dates)
is left `None`, never guessed from inconsistent per-board `metadata`
entries. The entire raw job object is preserved in `raw_metadata` so
nothing is lost even though only a subset maps to canonical fields.

`description_full` stores Greenhouse's `content` field verbatim -- raw,
untrusted HTML. Nothing here parses, strips, or renders it; sanitization
before any display is STORY-047's job, not this one's.

Every request goes through the injected `self.http_client` (a
`PolicyEnforcingHttpClient` in production) -- this file never imports
`urllib`/`requests`/sockets, so STORY-017's policy enforcement (robots.txt,
User-Agent, response-code refusal) applies to every Greenhouse request
without any extra code here.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

from app.connectors.base import BaseConnector, NormalizedJobRecord
from app.connectors.errors import ConnectorConfigError, ConnectorSourceFormatError
from app.connectors.registry import register_connector


class GreenhouseConnectorConfig(BaseModel):
    # Public identifier -- part of a public URL, not a secret. Restricted to
    # a safe character set so it can never inject a path/query segment into
    # the constructed URL.
    board_token: str = Field(min_length=1, pattern=r"^[A-Za-z0-9_-]+$")
    # Non-secret; overridable only for testability (points a FakeTransport
    # at a fake host). Defaults to Greenhouse's real, documented API host.
    api_base_url: str = "https://boards-api.greenhouse.io"


def _parse_updated_at(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value))
    except ValueError:
        return None


@register_connector("greenhouse")
class GreenhouseConnector(BaseConnector):
    config_model = GreenhouseConnectorConfig

    def _jobs_url(self) -> str:
        return f"{self.config.api_base_url}/v1/boards/{self.config.board_token}/jobs"

    def fetch(self) -> Iterator[dict[str, Any]]:
        response = self.http_client.get(self._jobs_url(), params={"content": "true"})

        if response.status_code == 404:
            raise ConnectorConfigError(
                f"Greenhouse board not found for token {self.config.board_token!r}",
                context={"status_code": 404},
            )
        if not (200 <= response.status_code < 300):
            raise ConnectorSourceFormatError(
                f"Greenhouse returned an unexpected status fetching jobs: {response.status_code}",
                context={"status_code": response.status_code},
            )

        try:
            payload = response.json()
        except (json.JSONDecodeError, ValueError) as exc:
            raise ConnectorSourceFormatError(
                f"Greenhouse response body was not valid JSON: {exc}"
            ) from exc

        jobs = payload.get("jobs") if isinstance(payload, dict) else None
        if not isinstance(jobs, list):
            raise ConnectorSourceFormatError(
                "Greenhouse response did not contain a 'jobs' list",
                context={"payload_type": type(payload).__name__},
            )

        yield from jobs

    def normalize(self, raw_record: dict[str, Any]) -> NormalizedJobRecord:
        raw_id = raw_record.get("id")
        if raw_id is None:
            raise ConnectorSourceFormatError(
                "Greenhouse job record is missing required field 'id'",
                context={"raw_record_keys": list(raw_record.keys())},
            )

        location = raw_record.get("location") or {}
        location_raw = location.get("name") if isinstance(location, dict) else None

        departments = raw_record.get("departments") or []
        department_names = [
            d.get("name") for d in departments if isinstance(d, dict) and d.get("name")
        ]
        department = ", ".join(department_names) if department_names else None

        absolute_url = raw_record.get("absolute_url")

        return NormalizedJobRecord(
            source_job_id=str(raw_id),
            job_title=raw_record.get("title"),
            source_url=absolute_url,
            # Greenhouse boards conventionally serve applying and viewing at
            # the same page -- no distinct application URL is exposed.
            application_url=absolute_url,
            description_full=raw_record.get("content"),
            location_raw=location_raw,
            department=department,
            source_updated_at=_parse_updated_at(raw_record.get("updated_at")),
            raw_metadata=raw_record,
        )
