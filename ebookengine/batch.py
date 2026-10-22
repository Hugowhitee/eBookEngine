"""Persistent, UI-independent EPUB batch queue.

A queue is not an automatic cleanup claim. Each item is inspected and
explicitly approved before processing; errors never discard later books.
Only the currently supported EPUB pipeline is executable. GUI remains separate.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from hashlib import sha256
from pathlib import Path
from typing import Literal
import json
import os
import tempfile
import uuid

from .core import ChangeSession, DocumentError, EpubSource, atomic_save, sniff
from .preflight import inspect_epub

Status = Literal["queued", "needs_review", "approved", "running",
                 "done", "unchanged", "error", "cancelled"]
VERSION = 1
METADATA = frozenset({"title", "author", "description", "cover"})


@dataclass
class BookJob:
    id: str
    source: str
    status: Status = "queued"
    source_hash: str | None = None
    format: str = "EPUB"
    title: str = ""
    findings: list[dict] = field(default_factory=list)
    workflow: str = ""
    edits: dict[str, str] = field(default_factory=dict)
    approved_proposals: list[str] = field(default_factory=list)
    libron_zip: str | None = None
    output: str | None = None
    error: str | None = None


def _digest(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as stream:
        for part in iter(lambda: stream.read(1_048_576), b""):
            digest.update(part)
    return digest.hexdigest()


class BatchQueue:
    """Serial durable queue; callers own background threads and UI rendering.

    A single process owns the queue JSON. Multiple concurrent app processes
    must not write the same store, so multi-process locking is future work.
    """

    def __init__(self, store: str | Path):
        self.store = Path(store)
        self.jobs: list[BookJob] = []
        if self.store.exists():
            data = json.loads(self.store.read_text(encoding="utf-8"))
            if data.get("version") != VERSION:
                raise DocumentError("Unsupported batch queue version")
            for values in data.get("jobs", []):
                job = BookJob(**values)
                # A crash mid-export must never auto-retry and overwrite work.
                if job.status == "running":
                    job.status = "needs_review"
                    job.error = "Previous processing was interrupted; verify output and reapprove"
                self.jobs.append(job)
            self._save()

    def _save(self):
        self.store.parent.mkdir(parents=True, exist_ok=True)
        tmp = None
        try:
            with tempfile.NamedTemporaryFile(
                dir=self.store.parent, prefix=".ebookengine-queue-",
                suffix=".tmp", mode="w", encoding="utf-8", delete=False
            ) as stream:
                tmp = Path(stream.name)
                json.dump({"version": VERSION, "jobs": [asdict(j) for j in self.jobs]},
                          stream, ensure_ascii=False, indent=2)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(tmp, self.store)
        finally:
            if tmp is not None:
                tmp.unlink(missing_ok=True)

    def get(self, job_id: str) -> BookJob:
        for job in self.jobs:
            if job.id == job_id:
                return job
        raise KeyError(job_id)

    def add(self, paths) -> list[BookJob]:
        seen = {Path(j.source) for j in self.jobs if j.status != "cancelled"}
        added = []
        for supplied in paths:
            path = Path(supplied).expanduser().resolve(strict=True)
            if path in seen:
                continue
            if sniff(path) != "EPUB":
                raise DocumentError("Batch EPUB engine does not yet process PDF")
            job = BookJob(id=uuid.uuid4().hex, source=str(path))
            seen.add(path)
            added.append(job)
        if added:
            self.jobs.extend(added)
            self._save()
        return added

    def inspect_next(self) -> BookJob | None:
        job = next((j for j in self.jobs if j.status == "queued"), None)
        if job is None:
            return None
        try:
            source_path = Path(job.source)
            starting_hash = _digest(source_path)
            report = inspect_epub(source_path)
            ending_hash = _digest(source_path)
            if starting_hash != ending_hash:
                raise DocumentError("Source changed during inspection; retry preflight")
            job.source_hash = ending_hash
            job.findings = [asdict(item) for item in report.findings]
            job.workflow = report.workflow
            job.title = report.title
            job.status = "needs_review"
            job.error = None
        except Exception as exc:
            job.status = "error"
            job.error = str(exc)
        self._save()
        return job

    def approve(self, job_id: str, *, edits: dict[str, str] | None = None,
                libron_zip: str | Path | None = None,
                approved_proposals: list[str] | None = None) -> BookJob:
        job = self.get(job_id)
        if job.status != "needs_review":
            raise DocumentError("Inspect and review book before approving")
        if any(item.get("severity") == "blocker" for item in job.findings):
            raise DocumentError("This book has unresolved EPUB blockers; cannot approve export")
        changes = dict(edits or {})
        if set(changes) - METADATA or any(not isinstance(v, str) for v in changes.values()):
            raise DocumentError("Unsupported EPUB metadata edit")
        proposed = list(approved_proposals or [])
        if len(proposed) != len(set(proposed)):
            raise DocumentError("Duplicate proposal approval")
        available = set(ChangeSession(EpubSource(job.source)).changes)
        if set(proposed) - available:
            raise DocumentError("Unknown proposed changes; reinspect this book")
        job.edits = changes
        job.approved_proposals = proposed
        job.libron_zip = str(Path(libron_zip).expanduser().resolve(strict=True)) if libron_zip else None
        job.status = "approved"
        job.error = None
        self._save()
        return job

    def cancel(self, job_id: str):
        job = self.get(job_id)
        if job.status not in {"queued", "needs_review", "approved", "error"}:
            raise DocumentError("Only inactive queue items can be cancelled")
        job.status = "cancelled"
        self._save()

    def retry(self, job_id: str) -> BookJob:
        """Reinspect an errored book, never silently replay its last export."""
        job = self.get(job_id)
        if job.status != "error":
            raise DocumentError("Only failed items can be retried")
        job.status = "queued"
        job.error = None
        job.source_hash = None
        job.findings = []
        job.workflow = ""
        job.edits = {}
        job.approved_proposals = []
        job.libron_zip = None
        job.output = None
        self._save()
        return job

    def reorder(self, ordered_ids: list[str]):
        if len(ordered_ids) != len(self.jobs) or set(ordered_ids) != {j.id for j in self.jobs}:
            raise DocumentError("Order must include every queue item once")
        lookup = {j.id: j for j in self.jobs}
        self.jobs = [lookup[key] for key in ordered_ids]
        self._save()

    def run_next(self, output_dir: str | Path) -> BookJob | None:
        """Run precisely one reviewed, approved book; do not silently mutate."""
        job = next((j for j in self.jobs if j.status == "approved"), None)
        if job is None:
            return None
        job.status = "running"
        job.error = None
        self._save()
        try:
            src = Path(job.source)
            if not job.source_hash or _digest(src) != job.source_hash:
                raise DocumentError("Source changed since review; inspect again")
            source = EpubSource(src)
            if sha256(source.raw).hexdigest() != job.source_hash:
                raise DocumentError("Source changed while loading; inspect again")
            session = ChangeSession(source)
            if set(job.approved_proposals) - set(session.changes):
                raise DocumentError("Approved proposal no longer matches the source")
            for key in tuple(session.changes):
                if key not in job.approved_proposals:
                    session.toggle(key)
            for key, value in job.edits.items():
                session.assign(key, value)
            if job.libron_zip:
                session.set_libron_zip(job.libron_zip)
            if not any(c.enabled for c in session.changes.values()) and not session.extra_css:
                job.status = "unchanged"
            else:
                result = session.build()
                session.verify_candidate(result)
                folder = Path(output_dir).expanduser().resolve()
                folder.mkdir(parents=True, exist_ok=True)
                # Never overwrite an existing export or the original.
                base = src.stem + " - eBookEngine"
                chosen = None
                for counter in range(1000):
                    suffix = "" if not counter else f" ({counter + 1})"
                    path = folder / (base + suffix + ".epub")
                    if path.resolve() != src.resolve() and not path.exists():
                        chosen = path
                        break
                if chosen is None:
                    raise DocumentError("No unused output filename available")
                # Single-process queue owns the directory selection. A future
                # multi-process writer must use a filesystem-level reservation.
                atomic_save(chosen, result, original=src)
                job.output = str(chosen)
                job.status = "done"
        except Exception as exc:
            job.status = "error"
            job.error = str(exc)
        self._save()
        return job
