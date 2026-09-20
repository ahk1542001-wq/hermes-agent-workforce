"""Truth-subset validation and ATS-readable DOCX/PDF/TXT rendering."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path

from docx import Document
from pypdf import PdfReader
from reportlab.lib.pagesizes import A4  # type: ignore[import-untyped]
from reportlab.pdfgen.canvas import Canvas  # type: ignore[import-untyped]

from .models import CandidateFact

_HEADINGS = ("PROFILE", "SKILLS", "EXPERIENCE", "EDUCATION")


@dataclass(frozen=True)
class DraftClaim:
    text: str
    fact_id: str


@dataclass(frozen=True)
class ApplicationPackDraft:
    identity: DraftClaim
    headline: DraftClaim
    summary: DraftClaim
    skills: tuple[DraftClaim, ...]
    experience: tuple[DraftClaim, ...]
    education: tuple[DraftClaim, ...]
    hidden_text: tuple[str, ...] = ()
    keyword_stuffing: tuple[str, ...] = ()


@dataclass(frozen=True)
class TruthReport:
    supported: bool
    unsupported_claims: tuple[str, ...]
    reason_codes: tuple[str, ...]


def _claims(draft: ApplicationPackDraft) -> tuple[DraftClaim, ...]:
    return (
        draft.identity,
        draft.headline,
        draft.summary,
        *draft.skills,
        *draft.experience,
        *draft.education,
    )


def validate_truth_subset(
    draft: ApplicationPackDraft,
    facts: list[CandidateFact],
) -> TruthReport:
    """Require exact owner-approved wording after whitespace/case normalization."""

    approved = {fact.fact_id: fact for fact in facts if fact.verified}
    unsupported: list[str] = []
    reasons: list[str] = []
    seen_text: set[str] = set()
    if any(value.strip() for value in draft.hidden_text):
        reasons.append("HIDDEN_TEXT")
    if any(value.strip() for value in draft.keyword_stuffing):
        reasons.append("KEYWORD_STUFFING")

    for claim in _claims(draft):
        normalized = " ".join(claim.text.split()).casefold()
        fact = approved.get(claim.fact_id)
        if fact is None:
            unsupported.append(claim.text)
            if "UNAPPROVED_FACT" not in reasons:
                reasons.append("UNAPPROVED_FACT")
            continue
        allowed_normalized = " ".join(fact.allowed_wording.split()).casefold()
        if not normalized or normalized != allowed_normalized:
            unsupported.append(claim.text)
            if "UNSUPPORTED_CLAIM" not in reasons:
                reasons.append("UNSUPPORTED_CLAIM")
        if normalized in seen_text:
            if "KEYWORD_STUFFING" not in reasons:
                reasons.append("KEYWORD_STUFFING")
        seen_text.add(normalized)

    return TruthReport(
        supported=not unsupported and not reasons,
        unsupported_claims=tuple(unsupported),
        reason_codes=tuple(reasons),
    )


def _validated_lines(
    draft: ApplicationPackDraft,
    facts: list[CandidateFact],
) -> list[str]:
    report = validate_truth_subset(draft, facts)
    if not report.supported:
        raise ValueError(f"draft contains unsupported content: {','.join(report.reason_codes)}")
    return [
        draft.identity.text,
        draft.headline.text,
        "PROFILE",
        draft.summary.text,
        "SKILLS",
        *(claim.text for claim in draft.skills),
        "EXPERIENCE",
        *(claim.text for claim in draft.experience),
        "EDUCATION",
        *(claim.text for claim in draft.education),
    ]


def _prepare_output(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() and (path.is_symlink() or not path.is_file()):
        raise ValueError("document output must be a regular non-symlink file")


def _secure_file(path: Path) -> None:
    os.chmod(path, 0o600)


def render_resume_docx(
    draft: ApplicationPackDraft,
    facts: list[CandidateFact],
    output: Path,
) -> Path:
    lines = _validated_lines(draft, facts)
    _prepare_output(output)
    document = Document()
    core = document.core_properties
    core.title = "ATS Resume"
    core.author = ""
    document.add_heading(lines[0], level=0)
    document.add_paragraph(lines[1])
    cursor = 2
    while cursor < len(lines):
        line = lines[cursor]
        if line in _HEADINGS:
            document.add_heading(line, level=1)
        else:
            document.add_paragraph(line)
        cursor += 1
    document.save(str(output))
    _secure_file(output)
    return output


def render_resume_pdf(
    draft: ApplicationPackDraft,
    facts: list[CandidateFact],
    output: Path,
) -> Path:
    lines = _validated_lines(draft, facts)
    _prepare_output(output)
    canvas = Canvas(str(output), pagesize=A4, pageCompression=1)
    canvas.setTitle("ATS Resume")
    width, height = A4
    y = height - 54
    for index, line in enumerate(lines):
        if y < 54:
            canvas.showPage()
            y = height - 54
        if index == 0:
            canvas.setFont("Helvetica-Bold", 18)
        elif line in _HEADINGS:
            canvas.setFont("Helvetica-Bold", 12)
        else:
            canvas.setFont("Helvetica", 10)
        canvas.drawString(54, y, line)
        y -= 22 if index == 0 else 16
    canvas.save()
    _secure_file(output)
    return output


def extract_docx_text(path: Path) -> str:
    document = Document(str(path))
    return "\n".join(paragraph.text for paragraph in document.paragraphs if paragraph.text.strip())


def extract_pdf_text(path: Path) -> str:
    reader = PdfReader(path)
    return "\n".join((page.extract_text() or "").strip() for page in reader.pages).strip()


def _normalize_core(value: str) -> tuple[str, ...]:
    return tuple(" ".join(line.split()).casefold() for line in value.splitlines() if line.strip())


def compare_core_content(left: str, right: str) -> bool:
    return _normalize_core(left) == _normalize_core(right)


def _synthetic_material() -> tuple[list[CandidateFact], ApplicationPackDraft]:
    values = {
        "identity": "Synthetic Candidate",
        "headline": "AI Automation Engineer",
        "summary": "Builds safe evidence backed automation workflows",
        "python": "Python",
        "n8n": "n8n",
        "experience": "Built tested automation workflows for small teams",
        "education": "Independent AI automation study",
    }
    facts = [
        CandidateFact(
            fact_id=fact_id,
            category="synthetic",
            allowed_wording=text,
            source="synthetic fixture",
            verified=True,
        )
        for fact_id, text in values.items()
    ]
    draft = ApplicationPackDraft(
        identity=DraftClaim(values["identity"], "identity"),
        headline=DraftClaim(values["headline"], "headline"),
        summary=DraftClaim(values["summary"], "summary"),
        skills=(DraftClaim(values["python"], "python"), DraftClaim(values["n8n"], "n8n")),
        experience=(DraftClaim(values["experience"], "experience"),),
        education=(DraftClaim(values["education"], "education"),),
    )
    return facts, draft


def render_synthetic_resume(output: Path) -> dict[str, Path]:
    created = not output.exists()
    output.mkdir(parents=True, exist_ok=True)
    if output.is_symlink() or not output.is_dir():
        raise ValueError("synthetic output must be a non-symlink directory")
    if created:
        os.chmod(output, 0o700)
    facts, draft = _synthetic_material()
    report = validate_truth_subset(draft, facts)
    docx_path = render_resume_docx(draft, facts, output / "resume.docx")
    pdf_path = render_resume_pdf(draft, facts, output / "resume.pdf")
    txt_path = output / "resume.txt"
    txt_path.write_text(extract_docx_text(docx_path), encoding="utf-8")
    _secure_file(txt_path)
    audit_path = output / "resume.audit.json"
    audit_path.write_text(
        json.dumps(
            {
                "synthetic": True,
                "fact_ids": [claim.fact_id for claim in _claims(draft)],
                "unsupported_claims": list(report.unsupported_claims),
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    _secure_file(audit_path)
    return {"docx": docx_path, "pdf": pdf_path, "txt": txt_path, "audit": audit_path}


__all__ = [
    "ApplicationPackDraft",
    "DraftClaim",
    "TruthReport",
    "compare_core_content",
    "extract_docx_text",
    "extract_pdf_text",
    "render_resume_docx",
    "render_resume_pdf",
    "render_synthetic_resume",
    "validate_truth_subset",
]
