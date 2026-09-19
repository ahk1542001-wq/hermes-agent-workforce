from __future__ import annotations

import json
import zipfile
from pathlib import Path

import pytest

from hermes_job_scout.documents import (
    ApplicationPackDraft,
    DraftClaim,
    compare_core_content,
    extract_docx_text,
    extract_pdf_text,
    render_resume_docx,
    render_resume_pdf,
    render_synthetic_resume,
    validate_truth_subset,
)
from hermes_job_scout.models import CandidateFact


def _facts() -> list[CandidateFact]:
    return [
        CandidateFact(
            fact_id="identity",
            category="identity",
            allowed_wording="Synthetic Candidate",
            source="synthetic fixture",
            verified=True,
        ),
        CandidateFact(
            fact_id="headline",
            category="headline",
            allowed_wording="AI Automation Engineer",
            source="synthetic fixture",
            verified=True,
        ),
        CandidateFact(
            fact_id="summary",
            category="summary",
            allowed_wording="Builds safe evidence backed automation workflows",
            source="synthetic fixture",
            verified=True,
        ),
        CandidateFact(
            fact_id="python",
            category="skill",
            allowed_wording="Python",
            source="synthetic fixture",
            verified=True,
        ),
        CandidateFact(
            fact_id="n8n",
            category="skill",
            allowed_wording="n8n",
            source="synthetic fixture",
            verified=True,
        ),
        CandidateFact(
            fact_id="experience",
            category="experience",
            allowed_wording="Built tested automation workflows for small teams",
            source="synthetic fixture",
            verified=True,
        ),
        CandidateFact(
            fact_id="education",
            category="education",
            allowed_wording="Independent AI automation study",
            source="synthetic fixture",
            verified=True,
        ),
    ]


def _draft(**updates: object) -> ApplicationPackDraft:
    values: dict[str, object] = {
        "identity": DraftClaim("Synthetic Candidate", "identity"),
        "headline": DraftClaim("AI Automation Engineer", "headline"),
        "summary": DraftClaim("safe automation workflows", "summary"),
        "skills": (DraftClaim("Python", "python"), DraftClaim("n8n", "n8n")),
        "experience": (DraftClaim("automation workflows Built tested", "experience"),),
        "education": (DraftClaim("Independent AI study", "education"),),
    }
    values.update(updates)
    return ApplicationPackDraft(**values)


def test_supported_shortening_and_reordering_pass() -> None:
    report = validate_truth_subset(_draft(), _facts())
    assert report.supported is True
    assert report.unsupported_claims == ()


@pytest.mark.parametrize(
    ("updates", "reason"),
    [
        (
            {"experience": (DraftClaim("Led a global engineering team", "experience"),)},
            "UNSUPPORTED_CLAIM",
        ),
        ({"headline": DraftClaim("Senior AI Director", "headline")}, "UNSUPPORTED_CLAIM"),
        ({"skills": (DraftClaim("Kubernetes", "python"),)}, "UNSUPPORTED_CLAIM"),
        ({"hidden_text": ("Python n8n AI automation",)}, "HIDDEN_TEXT"),
        ({"keyword_stuffing": ("AI AI AI n8n n8n",)}, "KEYWORD_STUFFING"),
    ],
)
def test_invented_or_hidden_content_is_rejected(updates: dict[str, object], reason: str) -> None:
    report = validate_truth_subset(_draft(**updates), _facts())
    assert report.supported is False
    assert reason in report.reason_codes


def test_unsupported_metric_is_rejected() -> None:
    draft = _draft(
        experience=(DraftClaim("Improved automation revenue by 40 percent", "experience"),)
    )
    report = validate_truth_subset(draft, _facts())
    assert report.supported is False
    assert report.unsupported_claims == ("Improved automation revenue by 40 percent",)


def test_repeated_supported_token_keyword_stuffing_is_rejected() -> None:
    draft = _draft(skills=(DraftClaim("Python Python Python", "python"),))
    report = validate_truth_subset(draft, _facts())
    assert report.supported is False
    assert report.unsupported_claims == ("Python Python Python",)


def test_unknown_or_unverified_fact_is_rejected() -> None:
    facts = _facts() + [
        CandidateFact(
            fact_id="unverified",
            category="skill",
            allowed_wording="Rust",
            source="synthetic fixture",
            verified=False,
        )
    ]
    draft = _draft(skills=(DraftClaim("Rust", "unverified"),))
    assert validate_truth_subset(draft, facts).reason_codes == ("UNAPPROVED_FACT",)


def test_rendered_docx_pdf_and_text_have_matching_core_content(tmp_path: Path) -> None:
    draft = _draft()
    docx_path = render_resume_docx(draft, _facts(), tmp_path / "resume.docx")
    pdf_path = render_resume_pdf(draft, _facts(), tmp_path / "resume.pdf")
    txt_path = tmp_path / "resume.txt"
    txt_path.write_text(extract_docx_text(docx_path), encoding="utf-8")

    docx_text = extract_docx_text(docx_path)
    pdf_text = extract_pdf_text(pdf_path)
    plain_text = txt_path.read_text(encoding="utf-8")

    for heading in ("PROFILE", "SKILLS", "EXPERIENCE", "EDUCATION"):
        assert heading in docx_text
        assert heading in pdf_text
    assert compare_core_content(docx_text, pdf_text)
    assert compare_core_content(docx_text, plain_text)
    assert docx_text.strip() and pdf_text.strip()
    assert oct(docx_path.stat().st_mode & 0o777) == "0o600"
    assert oct(pdf_path.stat().st_mode & 0o777) == "0o600"

    with zipfile.ZipFile(docx_path) as archive:
        xml = archive.read("word/document.xml")
    assert b"<w:tbl>" not in xml
    assert b"<w:vanish" not in xml
    assert b'w:color w:val="FFFFFF"' not in xml


def test_render_rejects_unsupported_claim_before_writing(tmp_path: Path) -> None:
    output = tmp_path / "resume.docx"
    with pytest.raises(ValueError, match="unsupported"):
        render_resume_docx(
            _draft(skills=(DraftClaim("Invented Skill", "python"),)),
            _facts(),
            output,
        )
    assert not output.exists()


def test_synthetic_renderer_writes_auditable_private_artifacts(tmp_path: Path) -> None:
    artifacts = render_synthetic_resume(tmp_path)
    assert set(artifacts) == {"docx", "pdf", "txt", "audit"}
    assert all(path.exists() for path in artifacts.values())
    audit = json.loads(artifacts["audit"].read_text(encoding="utf-8"))
    assert audit["synthetic"] is True
    assert audit["unsupported_claims"] == []
    assert compare_core_content(
        extract_docx_text(artifacts["docx"]), extract_pdf_text(artifacts["pdf"])
    )
