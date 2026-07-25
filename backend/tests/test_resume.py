"""U4 tests: master resume import, read, edit, and snapshots.

The AI seam (``app/services/ai.py``) is mocked at the router boundary in
every endpoint test — no network. One narrow unit test at the bottom checks
the request-shaping of the real ``parse_resume`` by intercepting the SDK
client object.

All resume content here is synthetic (a fake person at fake employers) —
never real resume data, per the plan's fixture rule.
"""

from types import SimpleNamespace

import pytest
from sqlmodel import Session, select

from app.config import Settings
from app.models import (
    Job,
    MasterSnapshot,
    ResumeSection,
    TailoredResume,
    TailoredSection,
)
from app.routers.resume import MAX_PDF_BYTES
from app.services import ai
from app.services.ai import ParsedResume, ParsedSection

# ---------------------------------------------------------------------------
# Synthetic fixtures (obviously fake person)
# ---------------------------------------------------------------------------

FAKE_SECTIONS = [
    ParsedSection(
        name="Summary",
        content="Pat Placeholder is an entirely fictional microscopist.",
    ),
    ParsedSection(
        name="Experience - Acme Optics Institute",
        content="Imaged imaginary samples on a pretend confocal microscope.",
    ),
    ParsedSection(
        name="Education",
        content="PhD in Made-Up Studies, University of Nowhere.",
    ),
]

FAKE_SECTIONS_V2 = [
    ParsedSection(
        name="Summary",
        content="Pat Placeholder, still fictional, now with fresh wording.",
    ),
    ParsedSection(
        name="Experience - Widget Microscopy Labs",
        content="Counted make-believe cells for a nonexistent employer.",
    ),
]

FAKE_PDF = b"%PDF-1.4 totally synthetic resume bytes for Pat Placeholder"


@pytest.fixture
def mock_parse(monkeypatch):
    """Replace ai.parse_resume with a recording fake returning FAKE_SECTIONS."""
    calls = []

    def fake_parse(text=None, pdf_bytes=None):
        calls.append({"text": text, "pdf_bytes": pdf_bytes})
        return list(FAKE_SECTIONS)

    monkeypatch.setattr(ai, "parse_resume", fake_parse)
    return calls


def seed_master(engine, sections=None):
    """Insert master sections directly, bypassing the import endpoints."""
    sections = sections or FAKE_SECTIONS
    with Session(engine) as session:
        rows = [
            ResumeSection(name=p.name, content=p.content, position=i)
            for i, p in enumerate(sections)
        ]
        session.add_all(rows)
        session.commit()
        return [row.id for row in rows]


# ---------------------------------------------------------------------------
# First-run and read contract
# ---------------------------------------------------------------------------


def test_get_resume_before_any_import_is_200_with_empty_sections(client):
    response = client.get("/resume")
    assert response.status_code == 200
    assert response.json() == {"sections": []}


def test_snapshots_empty_on_first_run(client):
    response = client.get("/resume/snapshots")
    assert response.status_code == 200
    assert response.json() == []


# ---------------------------------------------------------------------------
# Import: pasted text
# ---------------------------------------------------------------------------


def test_import_text_stores_sections_in_order(client, mock_parse):
    response = client.post(
        "/resume/import/text", json={"text": "Pat Placeholder\nfake resume"}
    )
    assert response.status_code == 200

    # The mock received the pasted text (text path, no PDF).
    assert mock_parse == [
        {"text": "Pat Placeholder\nfake resume", "pdf_bytes": None}
    ]

    sections = client.get("/resume").json()["sections"]
    assert [s["name"] for s in sections] == [p.name for p in FAKE_SECTIONS]
    assert [s["position"] for s in sections] == [0, 1, 2]
    assert sections[0]["content"] == FAKE_SECTIONS[0].content


def test_import_text_rejects_empty_and_missing_text(client, mock_parse):
    assert client.post("/resume/import/text", json={"text": ""}).status_code == 422
    assert client.post("/resume/import/text", json={}).status_code == 422
    assert mock_parse == []  # no AI spend on invalid bodies


# ---------------------------------------------------------------------------
# Import: PDF upload — validation happens before any AI call
# ---------------------------------------------------------------------------


def test_import_pdf_happy_path(client, mock_parse):
    response = client.post(
        "/resume/import/pdf",
        files={"file": ("resume.pdf", FAKE_PDF, "application/pdf")},
    )
    assert response.status_code == 200
    assert mock_parse == [{"text": None, "pdf_bytes": FAKE_PDF}]

    sections = client.get("/resume").json()["sections"]
    assert [s["name"] for s in sections] == [p.name for p in FAKE_SECTIONS]


def test_oversized_pdf_is_413_and_never_reaches_ai(client, mock_parse):
    too_big = b"%PDF-" + b"0" * MAX_PDF_BYTES  # 10 MB + 5 bytes
    response = client.post(
        "/resume/import/pdf",
        files={"file": ("huge.pdf", too_big, "application/pdf")},
    )
    assert response.status_code == 413
    assert mock_parse == []  # the mock was never invoked
    assert client.get("/resume").json() == {"sections": []}


def test_non_pdf_bytes_is_415_and_never_reaches_ai(client, mock_parse):
    response = client.post(
        "/resume/import/pdf",
        files={"file": ("resume.pdf", b"plain text, not a pdf", "application/pdf")},
    )
    assert response.status_code == 415
    assert mock_parse == []
    assert client.get("/resume").json() == {"sections": []}


# ---------------------------------------------------------------------------
# AI errors: structured payloads, database untouched
# ---------------------------------------------------------------------------


def test_import_without_api_key_is_503_and_db_unchanged(
    client, engine, monkeypatch
):
    seed_master(engine)
    # Real parse_resume, but settings without a key (env/.env not consulted).
    monkeypatch.setattr(
        ai,
        "get_settings",
        lambda: Settings(
            anthropic_api_key=None, jsearch_api_key=None, _env_file=None
        ),
    )

    response = client.post("/resume/import/text", json={"text": "fake resume"})
    assert response.status_code == 503
    assert "ANTHROPIC_API_KEY" in response.json()["detail"]

    # Master untouched, no snapshot created.
    sections = client.get("/resume").json()["sections"]
    assert [s["name"] for s in sections] == [p.name for p in FAKE_SECTIONS]
    assert client.get("/resume/snapshots").json() == []


def test_failed_parse_is_502_and_db_unchanged(client, engine, monkeypatch):
    seed_master(engine)

    def broken_parse(text=None, pdf_bytes=None):
        raise ai.AIParseError("Claude returned malformed output")

    monkeypatch.setattr(ai, "parse_resume", broken_parse)

    response = client.post("/resume/import/text", json={"text": "fake resume"})
    assert response.status_code == 502
    assert "malformed" in response.json()["detail"]

    sections = client.get("/resume").json()["sections"]
    assert [s["name"] for s in sections] == [p.name for p in FAKE_SECTIONS]
    assert client.get("/resume/snapshots").json() == []


# ---------------------------------------------------------------------------
# Section editing
# ---------------------------------------------------------------------------


def test_patch_section_persists(client, mock_parse):
    client.post("/resume/import/text", json={"text": "fake resume"})
    section_id = client.get("/resume").json()["sections"][0]["id"]

    response = client.patch(
        f"/resume/sections/{section_id}",
        json={"content": "Hand-edited fictional summary.", "name": "Profile"},
    )
    assert response.status_code == 200
    assert response.json()["content"] == "Hand-edited fictional summary."
    assert response.json()["name"] == "Profile"

    # Persisted, and untouched fields (position) kept.
    stored = client.get("/resume").json()["sections"][0]
    assert stored["content"] == "Hand-edited fictional summary."
    assert stored["name"] == "Profile"
    assert stored["position"] == 0


def test_patch_unknown_section_is_404(client):
    response = client.patch("/resume/sections/999", json={"content": "x"})
    assert response.status_code == 404


def test_read_unknown_snapshot_is_404(client):
    assert client.get("/resume/snapshots/999").status_code == 404


# ---------------------------------------------------------------------------
# Integration: re-import replaces the master, keeps a snapshot, and leaves
# tailored copies fully renderable with their provenance nulled
# ---------------------------------------------------------------------------


def test_reimport_snapshots_master_and_preserves_tailored_copies(
    client, engine, monkeypatch
):
    # First import — master v1 (3 sections).
    monkeypatch.setattr(
        ai, "parse_resume", lambda text=None, pdf_bytes=None: list(FAKE_SECTIONS)
    )
    client.post("/resume/import/text", json={"text": "fake resume v1"})
    v1_ids = [s["id"] for s in client.get("/resume").json()["sections"]]

    # A tailored copy exists, self-contained but with provenance links to v1.
    with Session(engine) as session:
        job = Job(
            company="Acme Optics Institute",
            position="Imaginary Microscopist",
            dedup_hash="synthetic-test-hash",
        )
        session.add(job)
        session.flush()
        tailored = TailoredResume(job_id=job.id)
        session.add(tailored)
        session.flush()
        for position, (base_id, parsed) in enumerate(
            zip(v1_ids, FAKE_SECTIONS)
        ):
            session.add(
                TailoredSection(
                    tailored_resume_id=tailored.id,
                    base_section_id=base_id,
                    name=parsed.name,
                    position=position,
                    content=f"Tailored: {parsed.content}",
                    changed=(position == 1),
                )
            )
        session.commit()
        tailored_id = tailored.id

    # Re-import — master v2 (2 sections) replaces v1.
    monkeypatch.setattr(
        ai,
        "parse_resume",
        lambda text=None, pdf_bytes=None: list(FAKE_SECTIONS_V2),
    )
    response = client.post(
        "/resume/import/text", json={"text": "fake resume v2"}
    )
    assert response.status_code == 200

    # Master replaced entirely.
    sections = client.get("/resume").json()["sections"]
    assert [s["name"] for s in sections] == [p.name for p in FAKE_SECTIONS_V2]
    assert [s["position"] for s in sections] == [0, 1]

    # Prior master retained as one inspectable snapshot.
    snapshots = client.get("/resume/snapshots").json()
    assert len(snapshots) == 1
    assert snapshots[0]["section_count"] == 3
    detail = client.get(f"/resume/snapshots/{snapshots[0]['id']}").json()
    assert [s["name"] for s in detail["sections"]] == [
        p.name for p in FAKE_SECTIONS
    ]
    assert detail["sections"][0]["content"] == FAKE_SECTIONS[0].content

    # Tailored copy still renders completely; provenance nulled by the FK.
    with Session(engine) as session:
        tailored_sections = session.exec(
            select(TailoredSection)
            .where(TailoredSection.tailored_resume_id == tailored_id)
            .order_by(TailoredSection.position)
        ).all()
        assert [t.name for t in tailored_sections] == [
            p.name for p in FAKE_SECTIONS
        ]
        assert [t.position for t in tailored_sections] == [0, 1, 2]
        assert [t.content for t in tailored_sections] == [
            f"Tailored: {p.content}" for p in FAKE_SECTIONS
        ]
        assert [t.changed for t in tailored_sections] == [False, True, False]
        assert all(t.base_section_id is None for t in tailored_sections)


def test_second_reimport_adds_second_snapshot(client, mock_parse):
    client.post("/resume/import/text", json={"text": "fake v1"})
    client.post("/resume/import/text", json={"text": "fake v2"})
    client.post("/resume/import/text", json={"text": "fake v3"})
    assert len(client.get("/resume/snapshots").json()) == 2


# ---------------------------------------------------------------------------
# Narrow unit test of the real parse_resume's request-shaping (no network:
# the SDK client object is replaced by a stub)
# ---------------------------------------------------------------------------


class _StubMessages:
    def __init__(self):
        self.kwargs = None

    def parse(self, **kwargs):
        self.kwargs = kwargs
        return SimpleNamespace(
            parsed_output=ParsedResume(sections=list(FAKE_SECTIONS))
        )


@pytest.fixture
def stub_client(monkeypatch):
    stub = SimpleNamespace(messages=_StubMessages())
    monkeypatch.setattr(ai, "_build_client", lambda: stub)
    return stub


def test_parse_resume_text_request_shape(stub_client):
    sections = ai.parse_resume(text="Pat Placeholder fake resume text")
    assert sections == FAKE_SECTIONS

    kwargs = stub_client.messages.kwargs
    assert kwargs["model"] == "claude-sonnet-5"
    assert kwargs["output_format"] is ParsedResume

    (message,) = kwargs["messages"]
    assert message["role"] == "user"
    (block,) = message["content"]
    assert block["type"] == "text"
    # Untrusted-data framing: delimited tags + data-not-instructions notice.
    assert "<resume_text>" in block["text"]
    assert "Pat Placeholder fake resume text" in block["text"]
    assert "not" in block["text"] and "instructions" in block["text"]


def test_parse_resume_pdf_request_shape(stub_client):
    ai.parse_resume(pdf_bytes=FAKE_PDF)

    (message,) = stub_client.messages.kwargs["messages"]
    document_block, text_block = message["content"]
    # Document block comes before the text prompt, base64 PDF source.
    assert document_block["type"] == "document"
    assert document_block["source"]["type"] == "base64"
    assert document_block["source"]["media_type"] == "application/pdf"
    assert text_block["type"] == "text"


def test_parse_resume_requires_exactly_one_input():
    with pytest.raises(ValueError):
        ai.parse_resume()
    with pytest.raises(ValueError):
        ai.parse_resume(text="x", pdf_bytes=b"%PDF-")


def test_parse_resume_empty_sections_is_parse_error(stub_client, monkeypatch):
    monkeypatch.setattr(
        _StubMessages,
        "parse",
        lambda self, **kwargs: SimpleNamespace(
            parsed_output=ParsedResume(sections=[])
        ),
    )
    with pytest.raises(ai.AIParseError):
        ai.parse_resume(text="fake resume")
