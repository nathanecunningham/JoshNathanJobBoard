"""U6 tests: recommendations — config, fetch, dedup, score, refresh.

Both external seams are mocked at the module boundary:

- the provider via ``monkeypatch.setattr(job_source, "build_provider", ...)``
  (``recommend.py`` calls it by module attribute), and
- scoring via ``monkeypatch.setattr(ai, "score_job", ...)``.

One synthetic JSearch response fixture (``JSEARCH_RESPONSE``) locks the real
provider's parsing contract, exercised through ``JSearchProvider`` with an
``httpx.MockTransport`` — no network anywhere.

All companies, postings, and resume content are synthetic, per the plan's
fixture rule.
"""

import httpx
import pytest
from sqlmodel import Session, select

from app.config import Settings
from app.models import (
    ExperienceSource,
    ExperienceSourceType,
    Job,
    ResumeSection,
    compute_dedup_hash,
)
from app.services import ai, job_source, recommend
from app.services.job_source import (
    JSearchProvider,
    ProviderError,
    ProviderQuotaError,
    RawJob,
)

# ---------------------------------------------------------------------------
# Synthetic fixtures
# ---------------------------------------------------------------------------

PROFILE_SECTIONS = [
    ("Summary", "Pat Placeholder is an entirely fictional microscopist."),
    (
        "Experience - Acme Optics Institute",
        "Quantitative confocal image analysis in an imaginary lab.",
    ),
]


def make_raw_jobs() -> list[RawJob]:
    """Three fresh synthetic provider postings."""
    return [
        RawJob(
            source_ref="prov-1",
            company="Axon Biosciences, Inc.",
            position="Microscopy Image Analyst",
            description="Analyze fictional confocal images with Python.",
            url="https://careers.axonbio.example/jobs/1",
            location="San Francisco, CA, US",
        ),
        RawJob(
            source_ref="prov-2",
            company="Nimbus Imaging LLC",
            position="Research Scientist, Imaging",
            description="Pretend light-sheet microscopy pipeline work.",
            url="https://jobs.nimbusimaging.example/2",
            location="Boston, MA, US",
        ),
        RawJob(
            source_ref="prov-3",
            company="Placeholder Pharma",
            position="Image Analysis Engineer",
            description="Synthetic posting about image segmentation.",
            url="https://placeholderpharma.example/careers/3",
            location="Remote, US",
        ),
    ]


class FakeProvider:
    """In-memory JobSource: returns canned RawJobs, counts search calls."""

    def __init__(self, jobs: list[RawJob], remaining_quota: int | None = 150):
        self.jobs = jobs
        self.remaining_quota = remaining_quota
        self.calls = 0

    def search(
        self, query: str, location: str | None, pages: int
    ) -> list[RawJob]:
        self.calls += 1
        return list(self.jobs)


class ScorerStub:
    """Recording stand-in for ``ai.score_job``. ``fail_for`` raises for one
    company, simulating a per-job AI failure."""

    def __init__(self, fail_for: str | None = None):
        self.calls: list[dict] = []
        self.fail_for = fail_for

    def __call__(
        self, profile: str, company: str, position: str, description: str
    ) -> ai.MatchScore:
        self.calls.append(
            {
                "profile": profile,
                "company": company,
                "position": position,
                "description": description,
            }
        )
        if company == self.fail_for:
            raise ai.AIParseError("Synthetic scoring failure.")
        return ai.MatchScore(
            score=90, rationale=f"Synthetic rationale for {position}."
        )


def seed_profile(engine) -> None:
    with Session(engine) as session:
        session.add_all(
            ResumeSection(name=name, content=content, position=index)
            for index, (name, content) in enumerate(PROFILE_SECTIONS)
        )
        session.commit()


def recommended_jobs(engine) -> list[Job]:
    with Session(engine) as session:
        return session.exec(
            select(Job).where(Job.source == "recommended")
        ).all()


@pytest.fixture
def anthropic_key(monkeypatch):
    """Make the refresh's Anthropic-key pre-check pass without a real .env."""
    monkeypatch.setattr(
        recommend,
        "get_settings",
        lambda: Settings(
            anthropic_api_key="synthetic-key",
            jsearch_api_key="synthetic-key",
            _env_file=None,
        ),
    )


@pytest.fixture
def scorer(monkeypatch, anthropic_key):
    stub = ScorerStub()
    monkeypatch.setattr(ai, "score_job", stub)
    return stub


@pytest.fixture
def provider(monkeypatch):
    """Factory: install a FakeProvider as the build_provider seam."""

    def install(
        jobs: list[RawJob], remaining_quota: int | None = 150
    ) -> FakeProvider:
        fake = FakeProvider(jobs, remaining_quota)
        monkeypatch.setattr(job_source, "build_provider", lambda: fake)
        return fake

    return install


# ---------------------------------------------------------------------------
# Refresh happy paths
# ---------------------------------------------------------------------------


def test_refresh_inserts_new_jobs_with_scores(client, engine, provider, scorer):
    seed_profile(engine)
    fake = provider(make_raw_jobs(), remaining_quota=142)

    response = client.post("/recommendations/refresh")
    assert response.status_code == 200
    assert response.json() == {
        "inserted": 3,
        "skipped_duplicates": 0,
        "unscored": 0,
        "score_failures": 0,
        "remaining_quota": 142,
    }
    assert fake.calls == 1

    jobs = recommended_jobs(engine)
    assert len(jobs) == 3
    for job in jobs:
        assert job.source == "recommended"
        assert job.status == "not_started"
        assert job.match_score == 90
        assert job.match_rationale.startswith("Synthetic rationale")
        assert job.source_ref is not None


def test_second_refresh_dedups_before_any_ai_spend(
    client, engine, provider, scorer
):
    seed_profile(engine)
    provider(make_raw_jobs())
    assert client.post("/recommendations/refresh").status_code == 200
    calls_after_first = len(scorer.calls)
    assert calls_after_first == 3

    # Same three postings again: zero inserts, zero new scoring calls.
    provider(make_raw_jobs())
    response = client.post("/recommendations/refresh")
    assert response.status_code == 200
    body = response.json()
    assert body["inserted"] == 0
    assert body["skipped_duplicates"] == 3
    assert len(scorer.calls) == calls_after_first
    assert len(recommended_jobs(engine)) == 3


def test_refresh_scores_against_resume_and_manual_sources_only(
    client, engine, provider, scorer
):
    """case_study/webpage sources are stored but unused by the v1 engine."""
    seed_profile(engine)
    with Session(engine) as session:
        session.add_all(
            [
                ExperienceSource(
                    type=ExperienceSourceType.manual,
                    content="MANUAL-NOTE: pretend grant-writing experience.",
                ),
                ExperienceSource(
                    type=ExperienceSourceType.case_study,
                    content="CASE-STUDY-TEXT that must never reach scoring.",
                ),
                ExperienceSource(
                    type=ExperienceSourceType.webpage,
                    url="https://example.test/portfolio",
                    content="WEBPAGE-TEXT that must never reach scoring.",
                ),
            ]
        )
        session.commit()
    provider(make_raw_jobs()[:1])

    assert client.post("/recommendations/refresh").status_code == 200
    profile = scorer.calls[0]["profile"]
    assert "fictional microscopist" in profile  # resume section
    assert "MANUAL-NOTE" in profile  # manual source
    assert "CASE-STUDY-TEXT" not in profile
    assert "WEBPAGE-TEXT" not in profile


def test_refreshed_jobs_appear_alongside_manual_in_list(
    client, engine, provider, scorer
):
    seed_profile(engine)
    provider(make_raw_jobs()[:1])
    manual = client.post(
        "/jobs",
        json={"company": "Handmade Labs", "position": "Curator"},
    )
    assert manual.status_code == 201
    assert client.post("/recommendations/refresh").status_code == 200

    rows = client.get("/jobs").json()
    assert len(rows) == 2
    by_source = {row["source"]: row for row in rows}
    assert by_source["manual"]["company"] == "Handmade Labs"
    assert by_source["recommended"]["match_score"] == 90
    # And the removal path for recommended jobs stays dismiss, not delete.
    delete = client.delete(f"/jobs/{by_source['recommended']['id']}")
    assert delete.status_code == 409


# ---------------------------------------------------------------------------
# Dedup behavior
# ---------------------------------------------------------------------------


def test_manual_job_dedups_provider_posting_via_normalized_hash(
    client, engine, provider, scorer
):
    """"Genentech, Inc." from the provider matches manual "genentech"."""
    seed_profile(engine)
    manual = client.post(
        "/jobs",
        json={
            "company": "genentech",
            "position": "Senior Scientist",
            "url": "https://jobs.genentech.example/postings/111",
        },
    )
    assert manual.status_code == 201

    provider(
        [
            RawJob(
                source_ref="prov-gene-1",
                company="Genentech, Inc.",
                position="Senior Scientist",
                description="Synthetic duplicate posting.",
                url="https://jobs.genentech.example/postings/222",
            )
        ]
    )
    response = client.post("/recommendations/refresh")
    assert response.status_code == 200
    body = response.json()
    assert body["inserted"] == 0
    assert body["skipped_duplicates"] == 1
    assert scorer.calls == []  # dedup happens before scoring spend
    assert recommended_jobs(engine) == []


def test_same_company_and_title_at_two_hosts_both_insert(
    client, engine, provider, scorer
):
    """The hash folds in the URL host, so two real postings aren't collapsed."""
    seed_profile(engine)
    provider(
        [
            RawJob(
                source_ref="prov-a",
                company="Placeholder Pharma",
                position="Image Analysis Engineer",
                description="Posting via one job board.",
                url="https://boards.example-one.test/jobs/1",
            ),
            RawJob(
                source_ref="prov-b",
                company="Placeholder Pharma",
                position="Image Analysis Engineer",
                description="Same role via another job board.",
                url="https://boards.example-two.test/jobs/9",
            ),
        ]
    )
    response = client.post("/recommendations/refresh")
    assert response.status_code == 200
    assert response.json()["inserted"] == 2
    assert len(recommended_jobs(engine)) == 2


def test_null_description_inserts_unscored_with_no_ai_call(
    client, engine, provider, scorer
):
    seed_profile(engine)
    jobs = make_raw_jobs()
    jobs[2] = RawJob(
        source_ref="prov-3",
        company="Placeholder Pharma",
        position="Image Analysis Engineer",
        description=None,
        url="https://placeholderpharma.example/careers/3",
    )
    provider(jobs)

    response = client.post("/recommendations/refresh")
    assert response.status_code == 200
    body = response.json()
    assert body["inserted"] == 3
    assert body["unscored"] == 1
    assert len(scorer.calls) == 2  # never called for the null description
    unscored = [j for j in recommended_jobs(engine) if j.match_score is None]
    assert len(unscored) == 1
    assert unscored[0].source_ref == "prov-3"


def test_double_refresh_race_is_caught_by_db_constraint(
    client, engine, provider, anthropic_key, monkeypatch
):
    """A conflicting insert during the scoring phase (after the dedup
    snapshot) trips the unique source_ref index; the refresh recovers by
    re-filtering instead of failing."""
    seed_profile(engine)
    provider(make_raw_jobs())
    raced = make_raw_jobs()[0]

    def racing_scorer(profile, company, position, description):
        if company == raced.company:
            # Simulate the concurrent refresh landing first.
            with Session(engine) as other:
                if not other.exec(
                    select(Job).where(Job.source_ref == raced.source_ref)
                ).first():
                    other.add(
                        Job(
                            company=raced.company,
                            position=raced.position,
                            source="recommended",
                            source_ref=raced.source_ref,
                            dedup_hash=compute_dedup_hash(
                                raced.company, raced.position, raced.url
                            ),
                        )
                    )
                    other.commit()
        return ai.MatchScore(score=75, rationale="Race-test rationale.")

    monkeypatch.setattr(ai, "score_job", racing_scorer)

    response = client.post("/recommendations/refresh")
    assert response.status_code == 200
    body = response.json()
    assert body["inserted"] == 2
    assert body["skipped_duplicates"] == 1

    refs = [job.source_ref for job in recommended_jobs(engine)]
    assert sorted(refs) == ["prov-1", "prov-2", "prov-3"]  # no duplicates


def test_pre_inserted_source_ref_is_dedupped_not_duplicated(
    client, engine, provider, scorer
):
    seed_profile(engine)
    with Session(engine) as session:
        session.add(
            Job(
                company="Axon Biosciences, Inc.",
                position="Microscopy Image Analyst",
                source="recommended",
                source_ref="prov-1",
                dedup_hash="unrelated-hash",
            )
        )
        session.commit()
    provider(make_raw_jobs())

    response = client.post("/recommendations/refresh")
    assert response.status_code == 200
    assert response.json()["inserted"] == 2
    refs = [job.source_ref for job in recommended_jobs(engine)]
    assert sorted(refs) == ["prov-1", "prov-2", "prov-3"]


# ---------------------------------------------------------------------------
# Dismiss / restore
# ---------------------------------------------------------------------------


def test_dismiss_and_restore_endpoints(client, engine, provider, scorer):
    seed_profile(engine)
    provider(make_raw_jobs()[:1])
    assert client.post("/recommendations/refresh").status_code == 200
    job_id = recommended_jobs(engine)[0].id

    dismissed = client.post(f"/jobs/{job_id}/dismiss")
    assert dismissed.status_code == 200
    first_stamp = dismissed.json()["dismissed_at"]
    assert first_stamp is not None
    assert client.get("/jobs").json() == []
    assert len(client.get("/jobs", params={"include_dismissed": True}).json()) == 1

    # Idempotent: a second dismiss keeps the original timestamp.
    again = client.post(f"/jobs/{job_id}/dismiss")
    assert again.status_code == 200
    assert again.json()["dismissed_at"] == first_stamp

    restored = client.post(f"/jobs/{job_id}/restore")
    assert restored.status_code == 200
    assert restored.json()["dismissed_at"] is None
    assert len(client.get("/jobs").json()) == 1

    assert client.post("/jobs/9999/dismiss").status_code == 404
    assert client.post("/jobs/9999/restore").status_code == 404


def test_dismissed_job_is_not_reimported_and_restore_keeps_dedup(
    client, engine, provider, scorer
):
    seed_profile(engine)
    provider(make_raw_jobs())
    assert client.post("/recommendations/refresh").status_code == 200
    job_id = recommended_jobs(engine)[0].id
    assert client.post(f"/jobs/{job_id}/dismiss").status_code == 200

    # The provider returns the same postings; the dismissed row still dedups.
    provider(make_raw_jobs())
    response = client.post("/recommendations/refresh")
    assert response.json() == {
        "inserted": 0,
        "skipped_duplicates": 3,
        "unscored": 0,
        "score_failures": 0,
        "remaining_quota": 150,
    }
    assert len(client.get("/jobs").json()) == 2  # dismissed one hidden

    # Restored job reappears — and stays in the dedup set on a third refresh.
    assert client.post(f"/jobs/{job_id}/restore").status_code == 200
    assert len(client.get("/jobs").json()) == 3
    provider(make_raw_jobs())
    assert client.post("/recommendations/refresh").json()["inserted"] == 0


# ---------------------------------------------------------------------------
# Error paths
# ---------------------------------------------------------------------------


def test_refresh_with_empty_profile_is_409(client, provider, scorer):
    provider(make_raw_jobs())
    response = client.post("/recommendations/refresh")
    assert response.status_code == 409
    assert "import a resume" in response.json()["detail"]


def test_provider_http_failure_is_502_with_no_partial_inserts(
    client, engine, provider, scorer, monkeypatch
):
    seed_profile(engine)

    class FailingProvider:
        remaining_quota = None

        def search(self, query, location, pages):
            raise ProviderError("JSearch request failed: connection reset")

    monkeypatch.setattr(job_source, "build_provider", FailingProvider)
    response = client.post("/recommendations/refresh")
    assert response.status_code == 502
    assert recommended_jobs(engine) == []


def test_missing_jsearch_key_is_503(client, engine, scorer, monkeypatch):
    seed_profile(engine)
    # Real build_provider with keyless settings — no monkeypatched provider.
    monkeypatch.setattr(
        job_source,
        "get_settings",
        lambda: Settings(
            anthropic_api_key=None, jsearch_api_key=None, _env_file=None
        ),
    )
    response = client.post("/recommendations/refresh")
    assert response.status_code == 503
    assert "JSEARCH_API_KEY" in response.json()["detail"]


def test_missing_anthropic_key_is_503_before_provider_spend(
    client, engine, provider, monkeypatch
):
    seed_profile(engine)
    fake = provider(make_raw_jobs())
    monkeypatch.setattr(
        recommend,
        "get_settings",
        lambda: Settings(
            anthropic_api_key=None, jsearch_api_key=None, _env_file=None
        ),
    )
    response = client.post("/recommendations/refresh")
    assert response.status_code == 503
    assert "ANTHROPIC_API_KEY" in response.json()["detail"]
    assert fake.calls == 0  # no JSearch quota spent on an unscoreable refresh


def test_provider_quota_exhaustion_is_429(
    client, engine, provider, scorer, monkeypatch
):
    seed_profile(engine)

    class ExhaustedProvider:
        remaining_quota = 0

        def search(self, query, location, pages):
            raise ProviderQuotaError(
                "JSearch monthly request quota is exhausted (HTTP 429)."
            )

    monkeypatch.setattr(job_source, "build_provider", ExhaustedProvider)
    response = client.post("/recommendations/refresh")
    assert response.status_code == 429
    assert "quota" in response.json()["detail"]


def test_ai_failure_for_one_job_leaves_it_unscored(
    client, engine, provider, anthropic_key, monkeypatch
):
    seed_profile(engine)
    provider(make_raw_jobs())
    stub = ScorerStub(fail_for="Nimbus Imaging LLC")
    monkeypatch.setattr(ai, "score_job", stub)

    response = client.post("/recommendations/refresh")
    assert response.status_code == 200
    body = response.json()
    assert body["inserted"] == 3
    assert body["unscored"] == 1
    assert body["score_failures"] == 1

    jobs = {job.company: job for job in recommended_jobs(engine)}
    assert jobs["Nimbus Imaging LLC"].match_score is None
    assert jobs["Axon Biosciences, Inc."].match_score == 90
    assert jobs["Placeholder Pharma"].match_score == 90


def test_all_scoring_failures_still_insert_and_are_counted(
    client, engine, provider, anthropic_key, monkeypatch
):
    """A completely broken scorer never fails the refresh: every job lands
    unscored. ``unscored`` is the total without a score (failures AND
    no-description jobs); ``score_failures`` counts only the raised calls."""
    seed_profile(engine)
    jobs = make_raw_jobs()
    jobs[2] = RawJob(
        source_ref="prov-3",
        company="Placeholder Pharma",
        position="Image Analysis Engineer",
        description=None,  # never scored — no AI call, so no failure
        url="https://placeholderpharma.example/careers/3",
    )
    provider(jobs)

    def always_raises(profile, company, position, description):
        raise ai.AIParseError("Synthetic total scoring outage.")

    monkeypatch.setattr(ai, "score_job", always_raises)

    response = client.post("/recommendations/refresh")
    assert response.status_code == 200
    body = response.json()
    assert body["inserted"] == 3
    assert body["unscored"] == 3  # nothing got a score
    assert body["score_failures"] == 2  # only the two scoring attempts raised
    assert all(job.match_score is None for job in recommended_jobs(engine))


# ---------------------------------------------------------------------------
# Settings: profile + experience sources
# ---------------------------------------------------------------------------


def test_profile_first_read_returns_defaults(client):
    response = client.get("/settings/profile")
    assert response.status_code == 200
    assert response.json() == {
        "experience": None,
        "location": None,
        "pay_min": None,
    }


def test_profile_put_replaces_all_fields(client):
    body = {
        "experience": "microscopy image analysis",
        "location": "Boston, MA",
        "pay_min": 90000,
    }
    response = client.put("/settings/profile", json=body)
    assert response.status_code == 200
    assert response.json() == body
    assert client.get("/settings/profile").json() == body

    # PUT semantics: omitted fields are cleared, not preserved.
    response = client.put(
        "/settings/profile", json={"experience": "ux research"}
    )
    assert response.json() == {
        "experience": "ux research",
        "location": None,
        "pay_min": None,
    }


def test_experience_sources_crud_all_four_types(client):
    assert client.get("/settings/sources").json() == []

    bodies = [
        {"type": "resume", "content": "Synthetic resume notes."},
        {"type": "manual", "content": "Synthetic manual notes."},
        {"type": "case_study", "content": "Synthetic case study."},
        {"type": "webpage", "url": "https://example.test/portfolio"},
    ]
    created = []
    for body in bodies:
        response = client.post("/settings/sources", json=body)
        assert response.status_code == 201
        created.append(response.json())

    listed = client.get("/settings/sources").json()
    assert {row["type"] for row in listed} == {
        "resume",
        "manual",
        "case_study",
        "webpage",
    }

    assert client.post(
        "/settings/sources", json={"type": "telepathy"}
    ).status_code == 422

    delete = client.delete(f"/settings/sources/{created[0]['id']}")
    assert delete.status_code == 204
    assert len(client.get("/settings/sources").json()) == 3
    assert client.delete("/settings/sources/9999").status_code == 404


# ---------------------------------------------------------------------------
# JSearchProvider: the synthetic fixture locks the parsing contract
# ---------------------------------------------------------------------------

JSEARCH_RESPONSE = {
    "status": "OK",
    "request_id": "synthetic-request-id",
    "data": [
        {
            "job_id": "jsearch-abc123",
            "employer_name": "Axon Biosciences, Inc.",
            "job_title": "Microscopy Image Analyst",
            "job_description": "Analyze fictional confocal images with Python.",
            "job_apply_link": "https://careers.axonbio.example/jobs/1",
            "job_city": "San Francisco",
            "job_state": "CA",
            "job_country": "US",
            "job_employment_type": "FULLTIME",
            "job_min_salary": 90000,
            "job_max_salary": 120000,
        },
        {
            "job_id": "jsearch-def456",
            "employer_name": "Nimbus Imaging LLC",
            "job_title": "Research Scientist, Imaging",
            "job_description": None,
            "job_apply_link": "https://jobs.nimbusimaging.example/2",
            "job_city": None,
            "job_state": None,
            "job_country": "US",
            "job_employment_type": "CONTRACTOR",
            "job_min_salary": None,
            "job_max_salary": None,
        },
    ],
}


def mock_provider(handler) -> JSearchProvider:
    transport = httpx.MockTransport(handler)
    return JSearchProvider(
        "synthetic-rapidapi-key", http_client=httpx.Client(transport=transport)
    )


def test_jsearch_provider_parses_fixture_response():
    seen_requests = []

    def handler(request):
        seen_requests.append(request)
        return httpx.Response(
            200,
            json=JSEARCH_RESPONSE,
            headers={"x-ratelimit-requests-remaining": "137"},
        )

    provider = mock_provider(handler)
    jobs = provider.search("microscopy analyst", "San Francisco", pages=1)

    request = seen_requests[0]
    assert request.headers["X-RapidAPI-Key"] == "synthetic-rapidapi-key"
    assert request.headers["X-RapidAPI-Host"] == "jsearch.p.rapidapi.com"
    assert "microscopy+analyst+in+San+Francisco" in str(request.url)

    assert provider.remaining_quota == 137
    assert len(jobs) == 2
    first, second = jobs
    assert first.source_ref == "jsearch-abc123"
    assert first.company == "Axon Biosciences, Inc."
    assert first.position == "Microscopy Image Analyst"
    assert first.description.startswith("Analyze fictional")
    assert first.url == "https://careers.axonbio.example/jobs/1"
    assert first.location == "San Francisco, CA, US"
    assert first.salary_min == 90000
    assert first.salary_max == 120000
    assert second.description is None  # degraded posting supported by design
    assert second.location == "US"


def test_jsearch_provider_maps_429_to_quota_error():
    provider = mock_provider(lambda request: httpx.Response(429))
    with pytest.raises(ProviderQuotaError, match="quota"):
        provider.search("anything", None, pages=1)


def test_jsearch_provider_maps_other_failures_to_provider_error():
    provider = mock_provider(lambda request: httpx.Response(500))
    with pytest.raises(ProviderError, match="HTTP 500"):
        provider.search("anything", None, pages=1)

    def network_error(request):
        raise httpx.ConnectError("synthetic connection failure")

    with pytest.raises(ProviderError, match="request failed"):
        mock_provider(network_error).search("anything", None, pages=1)


def test_jsearch_provider_stops_paging_at_quota_floor():
    """Header says 18 requests remain (< floor 20): after page 1 the
    provider keeps its results but refuses to spend more requests."""
    request_count = 0

    def handler(request):
        nonlocal request_count
        request_count += 1
        return httpx.Response(
            200,
            json=JSEARCH_RESPONSE,
            headers={"x-ratelimit-requests-remaining": "18"},
        )

    provider = mock_provider(handler)
    jobs = provider.search("anything", None, pages=3)
    assert request_count == 1
    assert len(jobs) == 2
    assert provider.remaining_quota == 18


def test_jsearch_provider_refuses_outright_below_floor():
    provider = mock_provider(lambda request: httpx.Response(200, json={}))
    provider.remaining_quota = 5  # known from a previous search
    with pytest.raises(ProviderQuotaError, match="floor"):
        provider.search("anything", None, pages=1)


def test_jsearch_provider_refuses_at_exact_floor():
    """Spending a request AT the floor would drop the quota below it, so
    the provider refuses at <= QUOTA_FLOOR, not just strictly below."""
    provider = mock_provider(lambda request: httpx.Response(200, json={}))
    provider.remaining_quota = job_source.QUOTA_FLOOR
    with pytest.raises(ProviderQuotaError, match="floor"):
        provider.search("anything", None, pages=1)


def test_low_quota_survives_into_next_fresh_provider(monkeypatch):
    """A refresh whose headers reported low quota poisons the well for the
    NEXT refresh too: build_provider seeds the fresh instance from the
    module-level memory, and it refuses before any HTTP request."""
    # First search learns from the header that only 10 requests remain.
    first = mock_provider(
        lambda request: httpx.Response(
            200,
            json=JSEARCH_RESPONSE,
            headers={"x-ratelimit-requests-remaining": "10"},
        )
    )
    first.search("microscopy analyst", None, pages=1)
    assert first.remaining_quota == 10

    # The next refresh builds a brand-new provider from settings...
    monkeypatch.setattr(
        job_source,
        "get_settings",
        lambda: Settings(
            anthropic_api_key=None,
            jsearch_api_key="synthetic-key",
            _env_file=None,
        ),
    )
    fresh = job_source.build_provider()
    assert fresh.remaining_quota == 10  # seeded from the module memory

    # ...and refuses without spending a request: the client would fail the
    # test if any HTTP call were attempted.
    def no_http_allowed(request):
        raise AssertionError("no HTTP request should be made below the floor")

    fresh._client = httpx.Client(transport=httpx.MockTransport(no_http_allowed))
    with pytest.raises(ProviderQuotaError, match="floor"):
        fresh.search("anything", None, pages=1)


def test_jsearch_provider_keeps_partial_results_when_later_page_fails():
    """Page 1 succeeded (and was paid for); a 429 on page 2 returns the
    partial results instead of throwing them away."""
    request_count = 0

    def handler(request):
        nonlocal request_count
        request_count += 1
        if request_count == 1:
            return httpx.Response(
                200,
                json=JSEARCH_RESPONSE,
                headers={"x-ratelimit-requests-remaining": "100"},
            )
        return httpx.Response(429)

    provider = mock_provider(handler)
    jobs = provider.search("anything", None, pages=3)
    assert request_count == 2  # stopped after the failed second page
    assert len(jobs) == 2  # page 1's results kept


def test_jsearch_provider_partial_results_on_later_http_error():
    request_count = 0

    def handler(request):
        nonlocal request_count
        request_count += 1
        if request_count == 1:
            return httpx.Response(200, json=JSEARCH_RESPONSE)
        return httpx.Response(500)

    provider = mock_provider(handler)
    jobs = provider.search("anything", None, pages=2)
    assert len(jobs) == 2


def test_malformed_provider_response_is_502(client, engine, scorer, monkeypatch):
    """A 200 with a non-JSON body from JSearch is a provider failure (502),
    not an unhandled exception."""
    seed_profile(engine)
    provider = mock_provider(
        lambda request: httpx.Response(200, text="<html>not json</html>")
    )
    monkeypatch.setattr(job_source, "build_provider", lambda: provider)

    response = client.post("/recommendations/refresh")
    assert response.status_code == 502
    assert "malformed" in response.json()["detail"]
    assert recommended_jobs(engine) == []


def test_one_bad_provider_item_is_skipped_not_fatal(
    client, engine, scorer, monkeypatch
):
    """A single unparseable entry in ``data[]`` is skipped; the good ones
    still insert."""
    seed_profile(engine)
    payload = {
        "status": "OK",
        "data": [
            {"employer_name": "No Id Corp", "job_title": "Broken"},  # no job_id
            JSEARCH_RESPONSE["data"][0],  # a good posting
        ],
    }
    provider = mock_provider(lambda request: httpx.Response(200, json=payload))
    monkeypatch.setattr(job_source, "build_provider", lambda: provider)

    response = client.post("/recommendations/refresh")
    assert response.status_code == 200
    assert response.json()["inserted"] == 1
    (job,) = recommended_jobs(engine)
    assert job.source_ref == "jsearch-abc123"


def test_build_provider_requires_key(monkeypatch):
    monkeypatch.setattr(
        job_source,
        "get_settings",
        lambda: Settings(
            anthropic_api_key=None, jsearch_api_key=None, _env_file=None
        ),
    )
    with pytest.raises(job_source.ProviderUnavailableError):
        job_source.build_provider()
    monkeypatch.setattr(
        job_source,
        "get_settings",
        lambda: Settings(
            anthropic_api_key=None,
            jsearch_api_key="synthetic-key",
            _env_file=None,
        ),
    )
    assert isinstance(job_source.build_provider(), JSearchProvider)


# ---------------------------------------------------------------------------
# score_job request-shaping (narrow unit test, SDK client stubbed)
# ---------------------------------------------------------------------------


def test_score_job_request_shaping(monkeypatch):
    captured = {}

    class StubMessages:
        def parse(self, **kwargs):
            captured.update(kwargs)

            class Response:
                parsed_output = ai.MatchScore(
                    score=77, rationale="Synthetic rationale."
                )

            return Response()

    class StubClient:
        messages = StubMessages()

    monkeypatch.setattr(ai, "_build_client", lambda: StubClient())

    result = ai.score_job(
        "Synthetic profile text.",
        "Axon Biosciences, Inc.",
        "Microscopy Image Analyst",
        "Synthetic posting description.",
    )
    assert result.score == 77

    assert captured["model"] == ai.SCORE_MODEL
    assert captured["output_format"] is ai.MatchScore
    content = captured["messages"][0]["content"]
    # Profile block first (prompt-cached), posting block second.
    assert "experience_profile" in content[0]["text"]
    assert "Synthetic profile text." in content[0]["text"]
    assert content[0]["cache_control"] == {"type": "ephemeral"}
    assert "job_posting" in content[1]["text"]
    assert "Axon Biosciences, Inc." in content[1]["text"]
    # Untrusted-data framing wraps the open-web posting text.
    assert "untrusted data" in content[1]["text"]


def test_score_job_rejects_out_of_range_score(monkeypatch):
    """The strict output-validation pattern: an out-of-range score is a
    parse failure, not a stored value."""
    with pytest.raises(Exception):
        ai.MatchScore(score=150, rationale="Too enthusiastic.")

    class StubMessages:
        def parse(self, **kwargs):
            class Response:
                parsed_output = None

            return Response()

    class StubClient:
        messages = StubMessages()

    monkeypatch.setattr(ai, "_build_client", lambda: StubClient())
    with pytest.raises(ai.AIParseError, match="no match score"):
        ai.score_job("profile", "Company", "Role", "Description")


def test_quota_memory_expires_after_month_rollover(monkeypatch):
    """A low reading from a PREVIOUS month must not lock the feature out:
    the quota resets monthly, so build_provider discards stale cache and
    lets the next search re-learn the real value."""
    monkeypatch.setattr(job_source, "_last_known_remaining", 5)
    monkeypatch.setattr(job_source, "_last_known_month", "2020-01")
    monkeypatch.setattr(
        job_source,
        "get_settings",
        lambda: Settings(
            anthropic_api_key=None,
            jsearch_api_key="synthetic-key",
            _env_file=None,
        ),
    )
    fresh = job_source.build_provider()
    assert fresh.remaining_quota is None  # stale cache discarded → probe allowed


def test_mid_pagination_429_still_updates_quota_cache():
    """RapidAPI sends the remaining-quota header on 429s too; the cache
    must record it so the NEXT refresh refuses instead of retrying."""
    request_count = 0

    def handler(request):
        nonlocal request_count
        request_count += 1
        if request_count == 1:
            return httpx.Response(
                200,
                json=JSEARCH_RESPONSE,
                headers={"x-ratelimit-requests-remaining": "100"},
            )
        return httpx.Response(
            429, headers={"x-ratelimit-requests-remaining": "0"}
        )

    provider = mock_provider(handler)
    results = provider.search("microscopy analyst", None, pages=2)
    assert results  # page-1 partials kept
    assert job_source._last_known_remaining == 0  # 429's header recorded
