"""External jobs-API seam: the JSearch provider.

JSearch (via RapidAPI) is the primary provider because it is the only free
general aggregator returning full ``job_description`` text, which match
scoring needs. ``RawJob`` treats ``description`` as possibly absent so
degraded or supplemental providers (Adzuna, Remotive, USAJobs) can slot in
later without redesign. This module exports ``JSearchProvider`` only — a
provider interface can be reintroduced when a second provider actually
exists.

Quota rules (see the plan's Key Technical Decisions): JSearch's free tier is
200 requests/month, hard cap. Each ``search`` page costs one request. The
provider reads the remaining monthly quota from RapidAPI's rate-limit
response headers and refuses to spend a request that would drop the quota
below ``QUOTA_FLOOR`` — so the feature degrades loudly instead of going dead
for half the month. The last-seen remaining quota is remembered at module
level, so the floor check also holds across refresh presses (each of which
builds a fresh provider).

Callers (``services/recommend.py``) obtain a provider via
:func:`build_provider` and mock this module at that boundary in tests.
"""

from datetime import UTC, datetime

import httpx
from pydantic import BaseModel, ValidationError

from app.config import get_settings

SEARCH_URL = "https://jsearch.p.rapidapi.com/search"
RAPIDAPI_HOST = "jsearch.p.rapidapi.com"
QUOTA_REMAINING_HEADER = "x-ratelimit-requests-remaining"

# Refuse to spend a request once doing so would leave the remaining monthly
# quota below this, keeping headroom for extra refresh presses late in the
# month.
QUOTA_FLOOR = 20

# Last remaining-quota value reported by any response header, remembered
# across provider instances (module-level, process lifetime) and tagged with
# the calendar month it was observed in. build_provider seeds each new
# provider from it so the floor check survives refreshes — but a value from
# a previous month is discarded, because the quota resets monthly and a
# stale low reading would otherwise refuse forever (no request would ever
# run to refresh it). Tests reset these via the autouse conftest fixture.
_last_known_remaining: int | None = None
_last_known_month: str | None = None


def _current_month() -> str:
    return datetime.now(UTC).strftime("%Y-%m")


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
        the rate-limit header; once spending another request would drop it
        below ``QUOTA_FLOOR``, no further requests are made.

        Failure policy: page 1 failures raise (nothing was fetched, the
        caller should see the error); failures on a later page keep what
        this refresh already paid for — break and return the partial
        results, mirroring the quota-floor branch.
        """
        full_query = f"{query} in {location}" if location else query
        jobs: list[RawJob] = []

        for page in range(1, pages + 1):
            if (
                self.remaining_quota is not None
                and self.remaining_quota <= QUOTA_FLOOR
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
                if jobs:
                    break
                raise ProviderError(f"JSearch request failed: {exc}") from exc

            # Read the quota header before the status checks: RapidAPI sends
            # it on 429s too, and a mid-pagination 429 must not leave the
            # cache stale-high for the next refresh.
            remaining = response.headers.get(QUOTA_REMAINING_HEADER)
            if remaining is not None and remaining.isdigit():
                self.remaining_quota = int(remaining)
                global _last_known_remaining, _last_known_month
                _last_known_remaining = self.remaining_quota
                _last_known_month = _current_month()

            if response.status_code == 429:
                if jobs:
                    break
                raise ProviderQuotaError(
                    "JSearch monthly request quota is exhausted (HTTP 429). "
                    "It resets at the start of the next month; until then, "
                    "recommendation refreshes are unavailable."
                )
            if response.status_code != 200:
                if jobs:
                    break
                raise ProviderError(
                    f"JSearch returned HTTP {response.status_code}."
                )

            try:
                payload = response.json()
                items = payload.get("data", [])
                if not isinstance(items, list):
                    raise TypeError("'data' is not a list")
            except (ValueError, TypeError, KeyError, AttributeError) as exc:
                if jobs:
                    break
                raise ProviderError(
                    f"JSearch returned a malformed response: {exc}"
                ) from exc

            for item in items:
                try:
                    jobs.append(self._parse_job(item))
                except (KeyError, TypeError, ValidationError):
                    continue  # skip the one bad item, keep the rest

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
    it with a fake provider. The new instance is seeded with the last-seen
    remaining quota, so a refresh that already knows the quota is at the
    floor refuses before spending any request.
    """
    settings = get_settings()
    if not settings.jsearch_api_key:
        raise ProviderUnavailableError(
            "No JSearch API key is configured. Add JSEARCH_API_KEY to "
            "backend/.env (get one from RapidAPI's JSearch page) to enable "
            "job recommendations."
        )
    provider = JSearchProvider(settings.jsearch_api_key)
    if _last_known_month == _current_month():
        provider.remaining_quota = _last_known_remaining
    # A reading from a previous month is stale — the quota has reset, so
    # leave remaining_quota at None and let the next search re-learn it.
    return provider
