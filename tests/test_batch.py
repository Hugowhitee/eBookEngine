"""Batch queue and read-only EPUB classification regression tests."""
from pathlib import Path
import json
import shutil
from zipfile import ZipFile, ZIP_DEFLATED, ZIP_STORED

import pytest

from ebookengine.batch import BatchQueue
from ebookengine.core import DocumentError, EpubSource
from ebookengine.preflight import inspect_epub
from test_core import fixture_book, OPF


def test_inspection_does_not_modify_source(tmp_path):
    path = fixture_book(tmp_path)
    before = path.read_bytes()
    report = inspect_epub(path)
    assert report.title == "Test Title"
    assert report.workflow == "preserve"
    assert not report.safe_to_auto_reconstruct
    assert report.epub_version == "2.0"
    assert any(f.code == "missing-description" for f in report.findings)
    assert path.read_bytes() == before


def test_fixed_layout_requires_review_and_no_automatic_rewrite(tmp_path):
    path = fixture_book(tmp_path)
    fixed = OPF.replace(b"</metadata>", b'<meta property="rendition:layout">pre-paginated</meta></metadata>')
    alternate = tmp_path / "fixed.epub"
    with ZipFile(path) as source, ZipFile(alternate, "w") as destination:
        for info in source.infolist():
            data = fixed if info.filename == "content.opf" else source.read(info)
            destination.writestr(info.filename, data,
                                compress_type=ZIP_STORED if info.filename == "mimetype" else ZIP_DEFLATED)
    report = inspect_epub(alternate)
    assert report.workflow == "special-layout-review"
    assert report.requires_review
    assert not report.safe_to_auto_reconstruct


def test_multiple_books_are_durable_and_explicitly_approved(tmp_path):
    first = fixture_book(tmp_path)
    second = tmp_path / "second.epub"
    shutil.copyfile(first, second)
    queue_file = tmp_path / "state" / "queue.json"
    queue = BatchQueue(queue_file)
    jobs = queue.add([first, second, first])
    assert len(jobs) == 2
    assert all(j.status == "queued" for j in jobs)
    assert queue.run_next(tmp_path / "output") is None

    assert queue.inspect_next().status == "needs_review"
    assert queue.inspect_next().status == "needs_review"
    assert queue.inspect_next() is None
    assert queue.run_next(tmp_path / "output") is None
    queue.approve(jobs[0].id, edits={"description": "Reviewed by user"})
    queue.approve(jobs[1].id)
    assert BatchQueue(queue_file).jobs[0].status == "approved"

    processed = queue.run_next(tmp_path / "output")
    assert processed.status == "done"
    assert processed.output
    assert first.read_bytes() != Path(processed.output).read_bytes()
    assert EpubSource(processed.output).description == "Reviewed by user"
    unchanged = queue.run_next(tmp_path / "output")
    assert unchanged.status == "unchanged"
    assert unchanged.output is None
    assert queue.run_next(tmp_path / "output") is None
    assert BatchQueue(queue_file).jobs[0].status == "done"


def test_stale_input_fails_only_its_job(tmp_path):
    first = fixture_book(tmp_path)
    second = tmp_path / "copy.epub"
    shutil.copyfile(first, second)
    queue = BatchQueue(tmp_path / "state.json")
    a, b = queue.add([first, second])
    queue.inspect_next()
    queue.inspect_next()
    queue.approve(a.id, edits={"description": "One"})
    queue.approve(b.id, edits={"description": "Two"})
    first.write_bytes(first.read_bytes() + b"NEW")
    rejected = queue.run_next(tmp_path / "out")
    assert rejected.status == "error"
    assert rejected.output is None
    assert queue.retry(a.id).status == "queued"
    assert queue.inspect_next().status == "needs_review"
    completed = queue.run_next(tmp_path / "out")
    assert completed.id == b.id
    assert completed.status == "done"


def test_queue_recovers_interrupted_work_without_silent_restart(tmp_path):
    path = fixture_book(tmp_path)
    store = tmp_path / "queue.json"
    queue = BatchQueue(store)
    entry = queue.add([path])[0]
    queue.inspect_next()
    queue.approve(entry.id, edits={"author": "Reviewed Author"})
    raw = json.loads(store.read_text())
    raw["jobs"][0]["status"] = "running"
    store.write_text(json.dumps(raw))
    again = BatchQueue(store)
    assert again.jobs[0].status == "needs_review"
    assert again.jobs[0].error
    assert again.run_next(tmp_path / "out") is None


def test_queue_rejects_unreviewed_actions(tmp_path):
    path = fixture_book(tmp_path)
    q = BatchQueue(tmp_path / "q.json")
    j = q.add([path])[0]
    with pytest.raises(DocumentError):
        q.approve(j.id)
    q.inspect_next()
    with pytest.raises(DocumentError):
        q.approve(j.id, edits={"made_up_field": "value"})
    assert not q.get(j.id).output


def test_add_is_atomic_when_later_input_is_invalid(tmp_path):
    book = fixture_book(tmp_path)
    q = BatchQueue(tmp_path / "queue.json")
    with pytest.raises(FileNotFoundError):
        q.add([book, tmp_path / "missing.epub"])
    assert not q.jobs
    assert not (tmp_path / "queue.json").exists()



def test_signed_epub_is_inspected_but_not_approved_or_modified(tmp_path):
    source = fixture_book(tmp_path, {
        "META-INF/signatures.xml": b'<signatures xmlns="urn:oasis:names:tc:opendocument:xmlns:digitalsignature:1.0"/>'
    })
    before = source.read_bytes()
    queue = BatchQueue(tmp_path / "queue.json")
    book = queue.add([source])[0]
    inspected = queue.inspect_next()
    assert inspected.id == book.id
    assert inspected.status == "needs_review"
    assert any(item["severity"] == "blocker" for item in inspected.findings)
    with pytest.raises(DocumentError, match="blockers"):
        queue.approve(book.id, edits={"description": "Change"})
    assert queue.run_next(tmp_path / "output") is None
    assert source.read_bytes() == before
    from ebookengine.core import ChangeSession
    changes = ChangeSession(EpubSource(source))
    changes.assign("description", "Would invalidate signature")
    with pytest.raises(DocumentError, match="signatures"):
        changes.build()


def test_dont_repack_unchanged_epub(tmp_path):
    path = fixture_book(tmp_path)
    from ebookengine.core import ChangeSession
    session = ChangeSession(EpubSource(path))
    for field, change in list(session.changes.items()):
        if change.enabled:
            session.toggle(field)
    result = session.build()
    assert result == path.read_bytes()
    assert session.verify_candidate(result)


def test_batch_does_not_apply_proposed_repairs_without_per_item_approval(tmp_path):
    from ebookengine.core import ChangeSession
    from io import BytesIO
    from zipfile import ZipFile
    path = fixture_book(tmp_path, {"Thumbs.db": b"cache"})
    assert "archive_hygiene" in ChangeSession(EpubSource(path)).changes
    queue = BatchQueue(tmp_path / "queue.json")
    job = queue.add([path])[0]
    queue.inspect_next()
    queue.approve(job.id)
    result = queue.run_next(tmp_path / "out")
    assert result.status == "unchanged"
    assert result.output is None
    assert "Thumbs.db" in ZipFile(path).namelist()

    # The identical book can be requeued and its specific cleanup proposal
    # approved, without automatically approving other unrelated proposals.
    queue.cancel(job.id) if job.status in ("queued", "approved") else None
    followup = BatchQueue(tmp_path / "second-queue.json")
    new_job = followup.add([path])[0]
    followup.inspect_next()
    followup.approve(new_job.id, approved_proposals=["archive_hygiene"])
    saved = followup.run_next(tmp_path / "out")
    assert saved.status == "done"
    with ZipFile(saved.output) as archive:
        assert "Thumbs.db" not in archive.namelist()
        assert b"Last chapter 2" in archive.read("chapter2.xhtml")


def test_batch_rejects_unknown_proposal_or_duplicate_approval(tmp_path):
    path = fixture_book(tmp_path)
    queue = BatchQueue(tmp_path / "queue.json")
    job = queue.add([path])[0]
    queue.inspect_next()
    with pytest.raises(DocumentError, match="Unknown"):
        queue.approve(job.id, approved_proposals=["rewrite_author_text"])
    with pytest.raises(DocumentError, match="Duplicate"):
        queue.approve(job.id, approved_proposals=["archive_hygiene", "archive_hygiene"])
    assert queue.get(job.id).status == "needs_review"
