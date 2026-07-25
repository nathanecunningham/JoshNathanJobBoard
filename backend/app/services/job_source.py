"""External jobs-API seam: the ``JobSource`` interface + the JSearch provider.

JSearch (via RapidAPI) is the primary provider because it is the only free
general aggregator returning full ``job_description`` text, which match
scoring needs. The interface treats ``description`` as possibly absent so
degraded or supplemental providers (Adzuna, Remotive, USAJobs) can slot in
later without redesign.

Quota rules (see the plan's Key Technical Decisions): JSearch's free tier is
200 requests/month, hard cap. Each ``search`` page costs one request. The
provider reads the remaining monthly quota from RapidAPI's rate-limit
response headers and refuses to spend requests once it would drop below
``QUOTA_FLOOR`` — so the feature degrades loudly instead of going dead for
half the month.

Callers (``services/recommend.py``) obtain a provider via
:func:`build_provider` and mock this module at that boundary in tests.
"""

from typing import Protocol

import httpx
from pydantic import BaseModel

from app.config import get_settings

SEARCH_URL = "https://jsearch.p.rapidapi.com/search"
RAPIDAPI_HOST = "jsearch.p.rapidapi.com"
QUOTA_REMAINING_HEADER = "x-ratelimit-requests-remaining"

# Refuse to spend requests once the remaining monthly quota is below this,
# leaving headroom for extra refresh presses late in the month.
QUOTA_FLOOR = 20


class ProviderError(Exception):
    """The jobs provider failed (network error, unexpected HTTP status)."""


class ProviderUnavailableError(ProviderError):
    """No JSearch API key is configured — recommendations can't run."""


class ProviderQuotaError(ProviderError):
    """The provider's monthly request quota is exhausted or nearly so."""


class RawJob(BaseModel):
    """One posting as returned by a provider, before it becomes a Job row."""

    source_ref: str  # the provider's stable posting id
    company: str
    position: str
    description: str | None = None
    url: str | None = None
    location: str | None = None
    salary_min: float | None = None
    salary_max: float | None = None


class JobSource(Protocol):
    """What ``recommend.py`` needs from any jobs provider."""

    remaining_quota: int | None

    def search(
        self, query: str, location: str | None, pages: int
    ) -> list[RawJob]: ...


class JSearchProvider:
    """JSearch via RapidAPI. One HTTP request per result page."""

    def __init__(self, api_key: str, http_client: httpx.Client | None = None):
        self.api_key = api_key
        # Injectable so tests can pass an httpx.MockTransport-backed client.
        self._client = http_client or httpx.Client(timeout=30)
        self.remaining_quota: int | None = None

    def search(
        self, query: str, location: str | None = None, pages: int = 1
    ) -> list[RawJob]:
        """Fetch up to ``pages`` result pages (one request each).

        JSearch takes free-text queries, so location is folded into the query
        string. After each response the remaining monthly quota is read from
        the rate-limit header; once it is below ``QUOTA_FLOOR`` no further
        requests are made — an error if nothing was fetched yet, otherwise
        the partial results are returned.
        """
        full_query = f"{query} in {location}" if location else query
        jobs: list[RawJob] = []

        for page in range(1, pages + 1):
            if (
                self.remaining_quota is not None
                and self.remaining_quota < QUOTA_FLOOR
            ):
                if jobs:
                    break  # keep what this refresh already paid for
                raise ProviderQuotaError(
                    f"Only {self.remaining_quota} JSearch requests remain "
                    f"this month (floor is {QUOTA_FLOOR}) — refusing to "
                    "spend more. The quota resets at the start of the next "
                    "month."
                )

            try:
                response = self._client.get(
                    SEARCH_URL,
                    params={"query": full_query, "page": page, "num_pages": 1},
                    headers={
                        "X-RapidAPI-Key": self.api_key,
                        "X-RapidAPI-Host": RAPIDAPI_HOST,
                    },
                )
            except httpx.HTTPError as exc:
                raise ProviderError(f"JSearch request failed: {exc}") from exc

            if response.status_code == 429:
                raise ProviderQuotaError(
                    "JSearch monthly request quota is exhausted (HTTP 429). "
                    "It resets at the start of the next month; until then, "
                    "recommendation refreshes are unavailable."
                )
            if response.status_code != 200:
                raise ProviderError(
                    f"JSearch returned HTTP {response.status_code}."
                )

            remaining = response.headers.get(QUOTA_REMAINING_HEADER)
            if remaining is not None and remaining.isdigit():
                self.remaining_quota = int(remaining)

            for item in response.json().get("data", []):
                jobs.append(self._parse_job(item))

        return jobs

    @staticmethod
    def _parse_job(item: dict) -> RawJob:
        """Map one JSearch ``data[]`` entry to a RawJob."""
        location_parts = [
            item.get("job_city"),
            item.get("job_state"),
            item.get("job_country"),
        ]
        location = ", ".join(part for part in location_parts if part) or None
        return RawJob(
            source_ref=str(item["job_id"]),
            company=item.get("employer_name") or "Unknown company",
            position=item.get("job_title") or "Unknown position",
            description=item.get("job_description"),
            url=item.get("job_apply_link"),
            location=location,
            salary_min=item.get("job_min_salary"),
            salary_max=item.get("job_max_salary"),
        )


def build_provider() -> JSearchProvider:
    """The provider seam: reads the key from settings, or fails clearly.

    ``recommend.py`` calls this by module attribute so tests can monkeypatch
    it with a fake provider.
    """
    settings = get_settings()
    if not settings.jsearch_api_key:
        raise ProviderUnavailableError(
            "No JSearch API key is configured. Add JSEARCH_API_KEY to "
            "backend/.env (get one from RapidAPI's JSearch page) to enable "
            "job recommendations."
        )
    return JSearchProvider(settings.jsearch_api_key)
