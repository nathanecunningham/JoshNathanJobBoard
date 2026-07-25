"""U3 tracker API tests: jobs CRUD, list derivations, and sub-resources.

Recommended and dismissed jobs are created directly in the DB here — the
refresh/dismiss endpoints that produce them arrive in U6; this unit only has
to behave correctly once such rows exist.
"""

from datetime import datetime

from sqlmodel import Session, select

from app.models import (
    Comment,
    Job,
    JobSource,
    TailoredResume,
    compute_dedup_hash,
    utcnow,
)

# Every field Nathan's board row needs — and nothing internal.
LIST_ROW_FIELDS = {
    "id",
    "company",
    "position",
    "description",
    "url",
    "status",
    "source",
    "applied_at",
    "denied_at",
    "accepted_at",
    "dismissed_at",
    "match_score",
    "match_rationale",
    "created_at",
    "updated_at",
    "last_activity_at",
    "comment_count",
    "contact_count",
    "link_count",
}


def create_job(client, **overrides) -> dict:
    payload = {
        "company": "Genentech",
        "position": "Senior Scientist",
        "description": "Imaging role focused on quantitative microscopy.",
    }
    payload.update(overrides)
    response = client.post("/jobs", json=payload)
    assert response.status_code == 201, response.text
    return response.json()


def add_db_job(engine, **overrides) -> int:
    """Insert a job directly (for shapes POST can't produce, e.g. recommended
    or dismissed rows) and return its id."""
    fields = dict(
        company="Roche",
        position="Imaging Scientist",
        dedup_hash=compute_dedup_hash("Roche", "Imaging Scientist"),
    )
    fields.update(overrides)
    with Session(engine) as session:
        job = Job(**fields)
        session.add(job)
        session.commit()
        return job.id


# ---------------------------------------------------------------------------
# Create + list
# ---------------------------------------------------------------------------


def test_created_job_appears_in_list(client):
    job = create_job(client)
    rows = client.get("/jobs").json()
    assert [row["id"] for row in rows] == [job["id"]]
    assert rows[0]["company"] == "Genentech"
    assert rows[0]["source"] == "manual"
    assert rows[0]["status"] == "not_started"


def test_list_row_has_full_landing_page_shape(client):
    """One GET /jobs call serves the whole board row — no follow-up requests,
    and no internal fields (dedup_hash, source_ref) leaking."""
    create_job(client)
    row = client.get("/jobs").json()[0]
    assert set(row) == LIST_ROW_FIELDS


def test_empty_list_returns_200_empty_array(client):
    response = client.get("/jobs")
    assert response.status_code == 200
    assert response.json() == []


def test_list_counts_reflect_sub_resources(client):
    job = create_job(client)
    job_id = job["id"]
    assert client.post(f"/jobs/{job_id}/comments", json={"body": "Called back"}).status_code == 201
    assert client.post(f"/jobs/{job_id}/contacts", json={"name": "Priya Shah"}).status_code == 201
    assert client.post(
        f"/jobs/{job_id}/links", json={"url": "https://example.com/posting"}
    ).status_code == 201

    row = client.get("/jobs").json()[0]
    assert row["comment_count"] == 1
    assert row["contact_count"] == 1
    assert row["link_count"] == 1


def test_list_sorted_by_last_activity_descending(client):
    first = create_job(client, company="Older Co")
    second = create_job(client, company="Newer Co")

    # Default order: the more recently created job leads...
    rows = client.get("/jobs").json()
    assert [row["id"] for row in rows] == [second["id"], first["id"]]

    # ...until a new comment on the older job makes it the latest activity.
    client.post(f"/jobs/{first['id']}/comments", json={"body": "Recruiter email"})
    rows = client.get("/jobs").json()
    assert [row["id"] for row in rows] == [first["id"], second["id"]]
    assert rows[0]["last_activity_at"] >= rows[0]["updated_at"]


# ---------------------------------------------------------------------------
# Filtering and search
# ---------------------------------------------------------------------------


def test_filter_by_status(client):
    applied = create_job(client, company="Applied Co", status="applied")
    create_job(client, company="Untouched Co")

    rows = client.get("/jobs", params={"status": "applied"}).json()
    assert [row["id"] for row in rows] == [applied["id"]]


def test_q_searches_company_position_description_case_insensitively(client):
    match = create_job(client)  # description mentions "microscopy"
    create_job(client, company="Acme", description="Sales role")

    rows = client.get("/jobs", params={"q": "Microscopy"}).json()
    assert [row["id"] for row in rows] == [match["id"]]

    by_company = client.get("/jobs", params={"q": "genen"}).json()
    assert [row["id"] for row in by_company] == [match["id"]]


def test_invalid_status_value_returns_422(client):
    assert client.get("/jobs", params={"status": "ghosted"}).status_code == 422
    job = create_job(client)
    assert (
        client.patch(f"/jobs/{job['id']}", json={"status": "ghosted"}).status_code
        == 422
    )


# ---------------------------------------------------------------------------
# Dismissed jobs in the list
# ---------------------------------------------------------------------------


def test_list_excludes_dismissed_by_default(client, engine):
    visible = create_job(client)
    dismissed_id = add_db_job(engine, dismissed_at=utcnow())

    default_rows = client.get("/jobs").json()
    assert [row["id"] for row in default_rows] == [visible["id"]]

    all_rows = client.get("/jobs", params={"include_dismissed": True}).json()
    assert {row["id"] for row in all_rows} == {visible["id"], dismissed_id}


def test_patching_status_on_dismissed_job_clears_dismissed_at(client, engine):
    """Any pipeline transition is a 'keep' — an applied job must never sit
    invisible on the default board (the dismiss endpoint itself is U6)."""
    job_id = add_db_job(engine, dismissed_at=utcnow())

    response = client.patch(f"/jobs/{job_id}", json={"status": "applied"})
    assert response.status_code == 200
    assert response.json()["dismissed_at"] is None
    assert response.json()["applied_at"] is not None

    assert job_id in [row["id"] for row in client.get("/jobs").json()]


# ---------------------------------------------------------------------------
# Status dates: auto-set, backfill, re-application
# ---------------------------------------------------------------------------


def test_patch_to_applied_auto_sets_applied_at(client):
    job = create_job(client)
    assert job["applied_at"] is None

    updated = client.patch(f"/jobs/{job['id']}", json={"status": "applied"}).json()
    assert updated["status"] == "applied"
    assert updated["applied_at"] is not None
    assert updated["denied_at"] is None


def test_explicit_date_in_same_patch_wins_over_auto_set(client):
    job = create_job(client)
    updated = client.patch(
        f"/jobs/{job['id']}",
        json={"status": "applied", "applied_at": "2026-06-01T09:30:00"},
    ).json()
    assert updated["applied_at"] == "2026-06-01T09:30:00"


def test_create_with_status_and_explicit_date_preserves_backfill(client):
    """Backfilling a pre-app application: last month's date must survive."""
    job = create_job(
        client, status="applied", applied_at="2026-06-25T10:00:00"
    )
    assert job["status"] == "applied"
    assert job["applied_at"] == "2026-06-25T10:00:00"


def test_create_with_status_but_no_date_auto_sets_now(client):
    before = utcnow()
    job = create_job(client, status="applied")
    assert job["applied_at"] is not None
    assert datetime.fromisoformat(job["applied_at"]) >= before


def test_reapplication_updates_applied_at_and_keeps_denied_at(client):
    job_id = create_job(client, status="applied")["id"]
    first_applied_at = client.get(f"/jobs/{job_id}").json()["applied_at"]

    denied = client.patch(f"/jobs/{job_id}", json={"status": "denied"}).json()
    assert denied["denied_at"] is not None

    reapplied = client.patch(f"/jobs/{job_id}", json={"status": "applied"}).json()
    assert reapplied["applied_at"] > first_applied_at  # latest wins
    assert reapplied["denied_at"] == denied["denied_at"]  # history retained


def test_full_lifecycle_leaves_correct_date_columns(client):
    """Integration: create → applied → denied → applied, checking every
    date column at each step (ISO strings compare chronologically)."""
    job = create_job(client)
    assert (job["applied_at"], job["denied_at"], job["accepted_at"]) == (
        None,
        None,
        None,
    )
    job_id = job["id"]

    applied = client.patch(f"/jobs/{job_id}", json={"status": "applied"}).json()
    assert applied["applied_at"] is not None
    assert applied["denied_at"] is None and applied["accepted_at"] is None

    denied = client.patch(f"/jobs/{job_id}", json={"status": "denied"}).json()
    assert denied["applied_at"] == applied["applied_at"]
    assert denied["denied_at"] > denied["applied_at"]
    assert denied["accepted_at"] is None

    reapplied = client.patch(f"/jobs/{job_id}", json={"status": "applied"}).json()
    assert reapplied["applied_at"] > denied["denied_at"]
    assert reapplied["denied_at"] == denied["denied_at"]
    assert reapplied["accepted_at"] is None


# ---------------------------------------------------------------------------
# Read, update, 404s
# ---------------------------------------------------------------------------


def test_detail_read_includes_nested_sub_resources(client):
    job_id = create_job(client)["id"]
    client.post(f"/jobs/{job_id}/comments", json={"body": "Phone screen Friday"})
    client.post(
        f"/jobs/{job_id}/contacts",
        json={"name": "Priya Shah", "role": "Hiring manager"},
    )
    client.post(
        f"/jobs/{job_id}/links",
        json={"url": "https://example.com/posting", "label": "Posting"},
    )

    detail = client.get(f"/jobs/{job_id}").json()
    assert [c["body"] for c in detail["comments"]] == ["Phone screen Friday"]
    assert [c["name"] for c in detail["contacts"]] == ["Priya Shah"]
    assert [link["label"] for link in detail["links"]] == ["Posting"]
    assert "dedup_hash" not in detail and "source_ref" not in detail


def test_patch_updates_fields_and_recomputes_dedup_hash(client, engine):
    job_id = create_job(client)["id"]
    response = client.patch(f"/jobs/{job_id}", json={"company": "Roche"})
    assert response.status_code == 200
    assert response.json()["company"] == "Roche"

    with Session(engine) as session:
        job = session.get(Job, job_id)
        assert job.dedup_hash == compute_dedup_hash(
            "Roche", "Senior Scientist", None
        )


def test_unknown_job_id_returns_404(client):
    assert client.get("/jobs/999").status_code == 404
    assert client.patch("/jobs/999", json={"company": "X"}).status_code == 404
    assert client.delete("/jobs/999").status_code == 404
    assert client.post("/jobs/999/comments", json={"body": "hi"}).status_code == 404
    detail = client.get("/jobs/999").json()["detail"]
    assert "999" in detail  # structured, actionable error payload


# ---------------------------------------------------------------------------
# Delete rules
# ---------------------------------------------------------------------------


def test_delete_manual_job_cascades_sub_resources_and_unsubmitted_copies(
    client, engine
):
    job_id = create_job(client)["id"]
    client.post(f"/jobs/{job_id}/comments", json={"body": "note"})
    with Session(engine) as session:
        session.add(TailoredResume(job_id=job_id, is_submitted=False))
        session.commit()

    assert client.delete(f"/jobs/{job_id}").status_code == 204
    assert client.get(f"/jobs/{job_id}").status_code == 404
    with Session(engine) as session:
        assert session.exec(select(Comment)).all() == []
        assert session.exec(select(TailoredResume)).all() == []


def test_delete_recommended_job_returns_409_pointing_at_dismiss(client, engine):
    job_id = add_db_job(engine, source=JobSource.recommended)
    response = client.delete(f"/jobs/{job_id}")
    assert response.status_code == 409
    assert "dismiss" in response.json()["detail"].lower()
    # Still there.
    assert client.get(f"/jobs/{job_id}").status_code == 200


def test_delete_job_with_submitted_tailored_resume_returns_409(client, engine):
    job_id = create_job(client)["id"]
    with Session(engine) as session:
        session.add(TailoredResume(job_id=job_id, is_submitted=True))
        session.commit()

    response = client.delete(f"/jobs/{job_id}")
    assert response.status_code == 409
    assert "submitted" in response.json()["detail"].lower()
    assert client.get(f"/jobs/{job_id}").status_code == 200


# ---------------------------------------------------------------------------
# Sub-resources: list and delete
# ---------------------------------------------------------------------------


def test_sub_resource_lists_and_deletes(client):
    job_id = create_job(client)["id"]
    comment = client.post(f"/jobs/{job_id}/comments", json={"body": "note"}).json()
    contact = client.post(f"/jobs/{job_id}/contacts", json={"name": "Priya"}).json()
    link = client.post(
        f"/jobs/{job_id}/links", json={"url": "https://example.com"}
    ).json()

    assert len(client.get(f"/jobs/{job_id}/comments").json()) == 1
    assert len(client.get(f"/jobs/{job_id}/contacts").json()) == 1
    assert len(client.get(f"/jobs/{job_id}/links").json()) == 1

    assert (
        client.delete(f"/jobs/{job_id}/comments/{comment['id']}").status_code == 204
    )
    assert (
        client.delete(f"/jobs/{job_id}/contacts/{contact['id']}").status_code == 204
    )
    assert client.delete(f"/jobs/{job_id}/links/{link['id']}").status_code == 204
    assert client.get(f"/jobs/{job_id}/comments").json() == []
    assert client.get(f"/jobs/{job_id}/contacts").json() == []
    assert client.get(f"/jobs/{job_id}/links").json() == []


def test_deleting_sub_resource_from_wrong_job_returns_404(client):
    job_a = create_job(client)["id"]
    job_b = create_job(client, company="Acme")["id"]
    comment = client.post(f"/jobs/{job_a}/comments", json={"body": "note"}).json()

    # Right id, wrong parent job — must not delete across jobs.
    assert (
        client.delete(f"/jobs/{job_b}/comments/{comment['id']}").status_code == 404
    )
    assert len(client.get(f"/jobs/{job_a}/comments").json()) == 1
