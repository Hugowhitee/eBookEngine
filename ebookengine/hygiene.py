"""Conservative EPUB archive-hygiene repair.

Only discard clearly identified operating-system debris that is not part of the
publication manifest or referenced by book content. Originals are immutable;
the caller must approve this as a typed change and validate the exact output.
"""
from __future__ import annotations

from copy import copy
from io import BytesIO
from shutil import copyfileobj
from pathlib import PurePosixPath
from zipfile import ZipFile, ZIP_STORED
from .core import DocumentError, verify_archive

_SYSTEM_NAMES = frozenset({".DS_Store", "Thumbs.db", "desktop.ini"})


def _is_os_debris(name: str) -> bool:
    parts = PurePosixPath(name.rstrip("/")).parts
    if not parts:
        return False
    if parts[0] == "__MACOSX":
        return True
    leaf = parts[-1]
    if leaf in _SYSTEM_NAMES or leaf.startswith("._"):
        return True
    # Office lock files and ordinary hidden files are not automatically junk:
    # the latter can be meaningful publisher-provided assets.
    return False


def removable_entries(source) -> tuple[str, ...]:
    """Return only manifest-unlisted system files with no source references.

    Fail closed if a text-containing resource could reference the candidate;
    this is not a generic 'delete unused files' operation.
    """
    protected = set(source.paths.values())
    protected.update({"mimetype", "META-INF/container.xml"})
    with ZipFile(BytesIO(source.raw)) as archive:
        entries = archive.namelist()
        candidates = [
            name for name in entries
            if _is_os_debris(name)
            and name not in protected
            and not any(name == x or x.startswith(name.rstrip("/") + "/")
                        for x in protected)
        ]
        if not candidates:
            return ()
        # Checking conservatively for raw path and basename mentions also
        # catches CSS/XML references that are not declared in the OPF.
        eligible = {
            name for name in candidates
            if not name.endswith("/")
            or not any(x != name and x.startswith(name) for x in entries)
        }
        # Scan one content file at a time, not an in-memory list of all text
        # resources. False-positive reference matches are intentionally safe.
        for path in entries:
            if not eligible:
                break
            if not path.lower().endswith(
                (".xhtml", ".html", ".htm", ".xml", ".ncx", ".css", ".svg", ".opf")
            ):
                continue
            try:
                with archive.open(path) as stream:
                    carry = b""
                    max_pattern = max(
                        max(len(name.encode("utf-8")), len(PurePosixPath(name.rstrip("/")).name.encode("utf-8")))
                        for name in eligible
                    )
                    while chunk := stream.read(64 * 1024):
                        data = carry + chunk
                        for name in tuple(eligible):
                            base = PurePosixPath(name.rstrip("/")).name
                            if name.encode("utf-8") in data or base.encode("utf-8") in data:
                                eligible.remove(name)
                        carry = data[-(max_pattern - 1):] if max_pattern > 1 else b""
                        if not eligible:
                            break
            except (KeyError, OSError) as exc:
                raise DocumentError(f"Cannot inspect referenced source: {path}") from exc
        return tuple(name for name in candidates if name in eligible)


def remove_os_debris(source, candidate: bytes, selected: tuple[str, ...]) -> bytes:
    """Rebuild only the container list; preserve every retained entry's data."""
    if not selected:
        return candidate
    allowed = set(removable_entries(source))
    if not set(selected) <= allowed or len(selected) != len(set(selected)):
        raise DocumentError("Unapproved or no longer safe EPUB cleanup selection")
    with ZipFile(BytesIO(candidate)) as original:
        verify_archive(original)
        if not set(selected) <= set(original.namelist()):
            raise DocumentError("Debris selected for removal no longer exists")
        output = BytesIO()
        with ZipFile(output, "w") as destination:
            for info in original.infolist():
                if info.filename in selected:
                    continue
                output_info = copy(info)
                if info.filename == "mimetype":
                    # OCF needs the first mimetype entry uncompressed, without
                    # streaming data-descriptor flags.
                    output_info.compress_type = ZIP_STORED
                    destination.writestr(output_info, original.read(info.filename),
                                         compress_type=ZIP_STORED)
                    continue
                if info.is_dir():
                    destination.writestr(output_info, b"")
                    continue
                with original.open(info) as reader, destination.open(output_info, "w") as writer:
                    copyfileobj(reader, writer, length=64 * 1024)
    result = output.getvalue()
    with ZipFile(BytesIO(candidate)) as before, ZipFile(BytesIO(result)) as after:
        verify_archive(after)
        if set(after.namelist()) != set(before.namelist()) - set(selected):
            raise DocumentError("Unexpected ZIP entry changes")
        if after.testzip() is not None:
            raise DocumentError("Corrupt EPUB after archive cleanup")
        for path in after.namelist():
            if path.endswith("/"):
                continue
            with before.open(path) as left, after.open(path) as right:
                while True:
                    chunk = left.read(64 * 1024)
                    if chunk != right.read(64 * 1024):
                        raise DocumentError(f"Unapproved archive payload change: {path}")
                    if not chunk:
                        break
    return result
