"""Filesystem layout for the private Job Scout workspace."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class WorkspacePaths:
    """All paths used by Job Scout, rooted at one private directory."""

    root: Path
    master: Path
    evidence: Path
    education: Path
    certificates: Path
    project_metrics: Path
    applications: Path
    reports: Path
    pending_ai_os_updates: Path
    data: Path
    database: Path
    marker: Path
    lock: Path

    @classmethod
    def from_root(cls, root: Path) -> WorkspacePaths:
        """Build deterministic paths without creating or resolving anything."""
        absolute = root.expanduser().absolute()
        if absolute.exists() and not absolute.is_dir():
            raise ValueError("private workspace root must be a directory")
        evidence = absolute / "evidence"
        return cls(
            root=absolute,
            master=absolute / "master",
            evidence=evidence,
            education=evidence / "education",
            certificates=evidence / "certificates",
            project_metrics=evidence / "project-metrics",
            applications=absolute / "applications",
            reports=absolute / "reports",
            pending_ai_os_updates=absolute / "pending-ai-os-updates",
            data=absolute / "data",
            database=absolute / "data" / "jobs.sqlite",
            marker=absolute / ".job-scout-workspace.json",
            lock=absolute / ".workspace.lock",
        )
