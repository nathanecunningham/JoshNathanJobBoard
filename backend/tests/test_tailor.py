"""U5 tests: the tailoring flow — create, edit, submit, delete.

The AI seam (``app/services/ai.py``) is mocked at the router boundary via
``monkeypatch.setattr(ai, "tailor_sections", ...)`` — no network. Narrow unit
tests at the bottom check the real ``tailor_sections``'s request-shaping by
stubbing the SDK client object, same pattern as test_resume.py.

All resume and job-posting content here is synthetic (a fake person, fake
employers, a fake posting) — never real data, per the plan's fixture rule.
"""

from types import SimpleNamespace

import pytest
from sqlmodel import Session, select

from app.config import Settings
from app.models import ResumeSection, TailoredResume, TailoredSection
from app.services import ai
from app.services.ai import SectionToTailor, TailoredContent, TailoringResult

# ---------------------------------------------------------------------------
# Synthetic fixtures (obviously fake person, employer, and posting)
# ---------------------------------------------------------------------------

MASTER_SECTIONS = [
    ("Summary", "Pat Placeholder is an entirely fictional microscopist."),
    (
        "Experience - Acme Optics Institute",
        "Imaged imaginary samples on a pretend confocal microscope.",
    ),
    ("Education", "PhD in Made-Up Studies, University of Nowhere."),
]

JOB_DESCRIPTION = (
    "Fictional Imaging Corp seeks a make-believe microscopist fluent in "
    "confocal imaging and quantitative image analysis. Synthetic posting "
    "written only for these tests."
)


def rewritten(name: str) -> str:
    """What the mocked AI 'writes' for a section — recognizably rewritten."""
    return f"Rewritten to match the posting: {name}"


def seed_master(engine) -> list[int]:
    """Insert master sections directly; returns their ids in order."""
    with Session(engine) as session:
        rows = [
            ResumeSection(name=name, content=content, position=index)
            for index, (name, content) in enumerate(MASTER_SECTIONS)
        ]
        session.add_all(rows)
        session.commit()
        return [row.id for row in rows]


def make_job(client, description: str | None = JOB_DESCRIPTION) -> int:
    response = client.post(
        "/jobs",
        json={
            "company": "Fictional Imaging Corp",
            "position": "Imaginary Microscopist",
            "description": description,
        },
    )
    assert response.status_code == 201
    return response.json()["id"]


def tailored_row_counts(engine) -> tuple[int, int]:
    """(TailoredResume rows, TailoredSection rows) — for no-partial asserts."""
    with Session(engine) as session:
        resumes = session.exec(select(TailoredResume)).all()
        sections = session.exec(select(TailoredSection)).all()
        return len(resumes), len(sections)


@pytest.fixture
def mock_tailor(monkeypatch):
    """Replace ai.tailor_sections with a recording fake."""
    calls = []

    def fake_tailor(job_description, sections):
        calls.append(
            {"job_description": job_description, "sections": list(sections)}
        )
        return [
            TailoredContent(section_id=s.id, content=rewritten(s.name))
            for s in sections
        ]

    monkeypatch.setattr(ai, "tailor_sections", fake_tailor)
    return calls


# ---------------------------------------------------------------------------
# Creating a tailored copy
# ---------------------------------------------------------------------------


def test_tailor_two_sections_rewrites_them_and_snapshots_the_rest(
    client, engine, mock_tailor
):
    ids = seed_master(engine)
    job_id = make_job(client)

    response = client.post(
        f"/jobs/{job_id}/tailor",
        json={"section_ids": [ids[0], ids[2]]},
    )
    assert response.status_code == 201
    data = response.json()
    assert data["job_id"] == job_id
    assert data["is_submitted"] is False

    # Every master section appears, in order, provenance recorded.
    sections = data["sections"]
    assert [s["name"] for s in sections] == [n for n, _ in MASTER_SECTIONS]
    assert [s["position"] for s in sections] == [0, 1, 2]
    assert [s["base_section_id"] for s in sections] == ids

    # Selected sections carry rewritten content and changed=True; the
    # unselected one is a verbatim snapshot.
    assert [s["changed"] for s in sections] == [True, False, True]
    assert sections[0]["content"] == rewritten(MASTER_SECTIONS[0][0])
    assert sections[2]["content"] == rewritten(MASTER_SECTIONS[2][0])
    assert sections[1]["content"] == MASTER_SECTIONS[1][1]

    # The AI seam got the stored description and ONLY the selected sections.
    (call,) = mock_tailor
    assert call["job_description"] == JOB_DESCRIPTION
    assert [s.id for s in call["sections"]] == [ids[0], ids[2]]
    assert [s.content for s in call["sections"]] == [
        MASTER_SECTIONS[0][1],
        MASTER_SECTIONS[2][1],
    ]


def test_description_override_used_when_job_has_none(
    client, engine, mock_tailor
):
    ids = seed_master(engine)
    job_id = make_job(client, description=None)

    response = client.post(
        f"/jobs/{job_id}/tailor",
        json={
            "section_ids": [ids[1]],
            "description_override": "Pasted fictional posting text.",
        },
    )
    assert response.status_code == 201
    (call,) = mock_tailor
    assert call["job_description"] == "Pasted fictional posting text."


def test_no_stored_description_and_no_override_is_422(
    client, engine, mock_tailor
):
    ids = seed_master(engine)
    job_id = make_job(client, description=None)

    response = client.post(
        f"/jobs/{job_id}/tailor", json={"section_ids": [ids[0]]}
    )
    assert response.status_code == 422
    assert "description_override" in response.json()["detail"]
    assert mock_tailor == []  # no AI spend
    assert tailored_row_counts(engine) == (0, 0)


def test_empty_section_ids_is_422(client, engine, mock_tailor):
    seed_master(engine)
    job_id = make_job(client)

    response = client.post(f"/jobs/{job_id}/tailor", json={"section_ids": []})
    assert response.status_code == 422
    assert mock_tailor == []


def test_unknown_section_id_is_422(client, engine, mock_tailor):
    ids = seed_master(engine)
    job_id = make_job(client)

    response = client.post(
        f"/jobs/{job_id}/tailor", json={"section_ids": [ids[0], 999]}
    )
    assert response.status_code == 422
    assert "999" in response.json()["detail"]
    assert mock_tailor == []
    assert tailored_row_counts(engine) == (0, 0)


def test_tailor_unknown_job_is_404(client, engine, mock_tailor):
    seed_master(engine)
    response = client.post("/jobs/999/tailor", json={"section_ids": [1]})
    assert response.status_code == 404
    assert mock_tailor == []


# ---------------------------------------------------------------------------
# Reading tailored copies
# ---------------------------------------------------------------------------


def test_list_tailored_with_no_copies_is_200_empty(client):
    job_id = make_job(client)
    response = client.get(f"/jobs/{job_id}/tailored")
    assert response.status_code == 200
    assert response.json() == []


def test_list_tailored_unknown_job_is_404(client):
    assert client.get("/jobs/999/tailored").status_code == 404


def test_read_tailored_by_id_and_list(client, engine, mock_tailor):
    ids = seed_master(engine)
    job_id = make_job(client)
    tailored_id = client.post(
        f"/jobs/{job_id}/tailor", json={"section_ids": [ids[0]]}
    ).json()["id"]

    detail = client.get(f"/tailored/{tailored_id}")
    assert detail.status_code == 200
    assert detail.json()["id"] == tailored_id
    assert len(detail.json()["sections"]) == len(MASTER_SECTIONS)

    listing = client.get(f"/jobs/{job_id}/tailored").json()
    assert [t["id"] for t in listing] == [tailored_id]


def test_read_unknown_tailored_is_404(client):
    assert client.get("/tailored/999").status_code == 404
    assert client.patch(
        "/tailored/999", json={"is_submitted": True}
    ).status_code == 404
    assert client.patch(
        "/tailored/999/sections/1", json={"content": "x"}
    ).status_code == 404
    assert client.delete("/tailored/999").status_code == 404


# ---------------------------------------------------------------------------
# Editing a tailored section — master stays canonical
# ---------------------------------------------------------------------------


def test_edit_tailored_section_leaves_master_unchanged(
    client, engine, mock_tailor
):
    ids = seed_master(engine)
    job_id = make_job(client)
    created = client.post(
        f"/jobs/{job_id}/tailor", json={"section_ids": [ids[0]]}
    ).json()
    tailored_id = created["id"]
    section_id = created["sections"][0]["id"]

    response = client.patch(
        f"/tailored/{tailored_id}/sections/{section_id}",
        json={"content": "Hand-polished fictional summary."},
    )
    assert response.status_code == 200
    assert response.json()["content"] == "Hand-polished fictional summary."

    # Persisted on the tailored copy...
    stored = client.get(f"/tailored/{tailored_id}").json()["sections"][0]
    assert stored["content"] == "Hand-polished fictional summary."

    # ...and the master section is explicitly untouched.
    master = client.get("/resume").json()["sections"]
    assert master[0]["content"] == MASTER_SECTIONS[0][1]
    assert [s["content"] for s in master] == [c for _, c in MASTER_SECTIONS]


def test_edit_section_of_wrong_tailored_resume_is_404(
    client, engine, mock_tailor
):
    ids = seed_master(engine)
    job_id = make_job(client)
    copy_a = client.post(
        f"/jobs/{job_id}/tailor", json={"section_ids": [ids[0]]}
    ).json()
    copy_b = client.post(
        f"/jobs/{job_id}/tailor", json={"section_ids": [ids[0]]}
    ).json()

    # A section id from copy B, addressed through copy A's URL → 404.
    response = client.patch(
        f"/tailored/{copy_a['id']}/sections/{copy_b['sections'][0]['id']}",
        json={"content": "x"},
    )
    assert response.status_code == 404


# ---------------------------------------------------------------------------
# Submitted flag — at most one submitted copy per job
# ---------------------------------------------------------------------------


def test_submitting_copy_b_clears_copy_a(client, engine, mock_tailor):
    ids = seed_master(engine)
    job_id = make_job(client)
    copy_a = client.post(
        f"/jobs/{job_id}/tailor", json={"section_ids": [ids[0]]}
    ).json()["id"]
    copy_b = client.post(
        f"/jobs/{job_id}/tailor", json={"section_ids": [ids[1]]}
    ).json()["id"]

    assert client.patch(
        f"/tailored/{copy_a}", json={"is_submitted": True}
    ).json()["is_submitted"] is True

    # Submitting B clears A in the same request.
    assert client.patch(
        f"/tailored/{copy_b}", json={"is_submitted": True}
    ).json()["is_submitted"] is True
    assert client.get(f"/tailored/{copy_a}").json()["is_submitted"] is False


def test_submitted_flag_scoped_per_job(client, engine, mock_tailor):
    ids = seed_master(engine)
    job_1 = make_job(client)
    job_2 = make_job(client)
    copy_1 = client.post(
        f"/jobs/{job_1}/tailor", json={"section_ids": [ids[0]]}
    ).json()["id"]
    copy_2 = client.post(
        f"/jobs/{job_2}/tailor", json={"section_ids": [ids[0]]}
    ).json()["id"]

    client.patch(f"/tailored/{copy_1}", json={"is_submitted": True})
    client.patch(f"/tailored/{copy_2}", json={"is_submitted": True})

    # Different jobs — submitting one never clears the other's copy.
    assert client.get(f"/tailored/{copy_1}").json()["is_submitted"] is True


def test_unsubmitting_just_clears_the_flag(client, engine, mock_tailor):
    ids = seed_master(engine)
    job_id = make_job(client)
    copy = client.post(
        f"/jobs/{job_id}/tailor", json={"section_ids": [ids[0]]}
    ).json()["id"]

    client.patch(f"/tailored/{copy}", json={"is_submitted": True})
    response = client.patch(f"/tailored/{copy}", json={"is_submitted": False})
    assert response.status_code == 200
    assert response.json()["is_submitted"] is False


# ---------------------------------------------------------------------------
# Deletion rules
# ---------------------------------------------------------------------------


def test_delete_unsubmitted_copy_removes_it_and_its_sections(
    client, engine, mock_tailor
):
    ids = seed_master(engine)
    job_id = make_job(client)
    copy = client.post(
        f"/jobs/{job_id}/tailor", json={"section_ids": [ids[0]]}
    ).json()["id"]

    assert client.delete(f"/tailored/{copy}").status_code == 204
    assert client.get(f"/tailored/{copy}").status_code == 404
    assert client.get(f"/jobs/{job_id}/tailored").json() == []
    assert tailored_row_counts(engine) == (0, 0)  # sections cascaded


def test_delete_submitted_copy_is_409(client, engine, mock_tailor):
    ids = seed_master(engine)
    job_id = make_job(client)
    copy = client.post(
        f"/jobs/{job_id}/tailor", json={"section_ids": [ids[0]]}
    ).json()["id"]
    client.patch(f"/tailored/{copy}", json={"is_submitted": True})

    response = client.delete(f"/tailored/{copy}")
    assert response.status_code == 409
    assert "is_submitted" in response.json()["detail"]
    assert client.get(f"/tailored/{copy}").status_code == 200  # still there


def test_job_delete_succeeds_after_its_only_unsubmitted_copy_is_removed(
    client, engine, mock_tailor
):
    ids = seed_master(engine)
    job_id = make_job(client)
    copy = client.post(
        f"/jobs/{job_id}/tailor", json={"section_ids": [ids[0]]}
    ).json()["id"]

    assert client.delete(f"/tailored/{copy}").status_code == 204
    assert client.delete(f"/jobs/{job_id}").status_code == 204
    assert client.get(f"/jobs/{job_id}").status_code == 404


# ---------------------------------------------------------------------------
# AI errors: structured payloads, no partial rows
# ---------------------------------------------------------------------------


def test_ai_failure_mid_tailor_leaves_no_partial_rows(
    client, engine, monkeypatch
):
    ids = seed_master(engine)
    job_id = make_job(client)

    def broken_tailor(job_description, sections):
        raise ai.AIParseError("Claude returned malformed output")

    monkeypatch.setattr(ai, "tailor_sections", broken_tailor)

    response = client.post(
        f"/jobs/{job_id}/tailor", json={"section_ids": [ids[0], ids[1]]}
    )
    assert response.status_code == 502
    assert "malformed" in response.json()["detail"]
    # Transactional: no TailoredResume and no TailoredSection rows exist.
    assert tailored_row_counts(engine) == (0, 0)
    assert client.get(f"/jobs/{job_id}/tailored").json() == []


def test_tailor_without_api_key_is_503_and_no_rows(client, engine, monkeypatch):
    ids = seed_master(engine)
    job_id = make_job(client)
    # Real tailor_sections, but settings without a key (env not consulted).
    monkeypatch.setattr(
        ai,
        "get_settings",
        lambda: Settings(
            anthropic_api_key=None, jsearch_api_key=None, _env_file=None
        ),
    )

    response = client.post(
        f"/jobs/{job_id}/tailor", json={"section_ids": [ids[0]]}
    )
    assert response.status_code == 503
    assert "ANTHROPIC_API_KEY" in response.json()["detail"]
    assert tailored_row_counts(engine) == (0, 0)


# ---------------------------------------------------------------------------
# Integration: tailored copy survives a destructive master re-import
# ---------------------------------------------------------------------------


def test_tailored_copy_fully_renderable_after_master_reimport(
    client, engine, mock_tailor, monkeypatch
):
    ids = seed_master(engine)
    job_id = make_job(client)
    tailored_id = client.post(
        f"/jobs/{job_id}/tailor", json={"section_ids": [ids[1]]}
    ).json()["id"]

    # Destructive re-import (U4 path, parse mocked): master v2 replaces v1.
    monkeypatch.setattr(
        ai,
        "parse_resume",
        lambda text=None, pdf_bytes=None: [
            ai.ParsedSection(
                name="Summary",
                content="A completely new fictional master, v2.",
            )
        ],
    )
    assert (
        client.post(
            "/resume/import/text", json={"text": "fake resume v2"}
        ).status_code
        == 200
    )

    # The copy still renders completely from its own snapshots.
    data = client.get(f"/tailored/{tailored_id}").json()
    sections = data["sections"]
    assert [s["name"] for s in sections] == [n for n, _ in MASTER_SECTIONS]
    assert [s["position"] for s in sections] == [0, 1, 2]
    assert [s["changed"] for s in sections] == [False, True, False]
    assert sections[1]["content"] == rewritten(MASTER_SECTIONS[1][0])
    assert sections[0]["content"] == MASTER_SECTIONS[0][1]
    assert sections[2]["content"] == MASTER_SECTIONS[2][1]
    # Provenance nulled by the FK — self-containment did the real work.
    assert all(s["base_section_id"] is None for s in sections)


# ---------------------------------------------------------------------------
# Narrow unit tests of the real tailor_sections' request-shaping (no network:
# the SDK client object is replaced by a stub)
# ---------------------------------------------------------------------------


class _StubMessages:
    def __init__(self, result):
        self.kwargs = None
        self.result = result

    def parse(self, **kwargs):
        self.kwargs = kwargs
        return SimpleNamespace(parsed_output=self.result)


def stub_ai_client(monkeypatch, result) -> SimpleNamespace:
    stub = SimpleNamespace(messages=_StubMessages(result))
    monkeypatch.setattr(ai, "_build_client", lambda: stub)
    return stub


def test_tailor_sections_request_shape(monkeypatch):
    result = TailoringResult(
        sections=[TailoredContent(section_id=7, content="rewritten text")]
    )
    stub = stub_ai_client(monkeypatch, result)

    out = ai.tailor_sections(
        JOB_DESCRIPTION,
        [SectionToTailor(id=7, name="Summary", content="original text")],
    )
    assert out == result.sections

    kwargs = stub.messages.kwargs
    assert kwargs["model"] == "claude-sonnet-5"
    assert kwargs["output_format"] is TailoringResult

    (message,) = kwargs["messages"]
    assert message["role"] == "user"
    prompt = message["content"]
    # Untrusted-data framing for the open-web posting and the sections.
    assert "<job_description>" in prompt and JOB_DESCRIPTION in prompt
    assert "<resume_sections>" in prompt and "original text" in prompt
    assert "untrusted" in prompt
    # The prompt carries the plan's three tailoring rules.
    assert "ONLY" in prompt
    assert "truthful" in prompt and "invent" in prompt
    assert "voice" in prompt


def test_tailor_sections_id_mismatch_is_parse_error(monkeypatch):
    # Model answers for a section that was never requested.
    result = TailoringResult(
        sections=[TailoredContent(section_id=99, content="rewritten")]
    )
    stub_ai_client(monkeypatch, result)

    with pytest.raises(ai.AIParseError):
        ai.tailor_sections(
            JOB_DESCRIPTION,
            [SectionToTailor(id=7, name="Summary", content="original")],
        )


def test_tailor_sections_requires_sections():
    with pytest.raises(ValueError):
        ai.tailor_sections(JOB_DESCRIPTION, [])
