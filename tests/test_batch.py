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
