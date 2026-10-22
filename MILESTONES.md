# Milestones and exit gates

## Implemented and tested locally

- EPUB signature/container inspection, full manifest/spine preservation, metadata and cover proposals, source-linked NCX navigation, Undo/Redo, valid output checks and source-safe atomic save.
- PDF digital/scanned recognition, visual rendering, Tesseract searchable layer without repainting, cancellation and preservation of page count.
- Document-first ttk GUI initialized and opened in virtual display with real EPUB source/result cover comparison and change review. A custom user-supplied EPUB containing an actual cover versus ASIN/EBOK placeholder was checked privately (never commit book data).

## EPUB cleanup skill parity

This is a requirement map, not a passing score. The current Drive EPUB cleanup skill remains the behavior reference.

| Skill capability | Current implementation | Proof needed |
| --- | --- | --- |
| Detect EPUB/KEPUB, fixed/roll/reflow, encryption and structural risks | Partial read-only preflight, new and untested | Mixed-layout fixtures and independent validation |
| Preserve vs reconstruct vs mixed strategy | Flags evidence; cannot yet reconstruct existing EPUBs | Real poorly converted books with original-text comparisons |
| Navigation/TOC/footnotes/spine repair | Reviewable EPUB2 NCX generation only when every linear spine item has a reliable XHTML heading; read-only broken-link and duplicate-ID audit | EPUBCheck, reader render, hierarchical TOC/EPUB3 nav, footnote and complex-source repair |
| CSS/reflow and typography | Narrow CSS repair; opt-in Libron backend in draft | E-reader render, dark mode, all font styles, glyph coverage |
| Watermark/OCR/conversion artifact removal | Source-preserving removal of clearly unreferenced OS ZIP debris only; watermarks/OCR/content cleanup not implemented | Proven author-content preservation and explicit repair scope |
| Metadata, privacy and covers | Partial metadata editing and cover proposals | Real bookstore/Calibre checks; source provenance |
| EPUB3/ZIP/link/font/reader validation | Partial self-check and conservative offline internal-reference audit; no EPUBCheck integration | Independent EPUBCheck and content preservation |
| Kobo master/KEPUB decision | Not implemented | Master first; derivative only if requested |
| Several books in a queue | Persisted EPUB-only backend; no GUI, no PDF batch | restart/retry/cancel, bounded memory, batch UI QA |

Do not call a book clean merely because it passed archive inspection or its metadata changed.

## Current development-branch evidence (not a release)

- Proposed OS debris removal is integrated with ChangeSession, undo/redo and selective archive verification. Retained files are compared byte-for-byte, with bounded streaming in the new cleanup layer; this does not fix the larger EpubSource whole-book memory model.
- Preflight checks broken local links and anchors, duplicate XHTML IDs and unverified XML bases. A separate strict EPUB2-only NCX generator attaches a missing navigation document from trusted XHTML headings without changing chapter bytes. It distinguishes standard IDPF font obfuscation from unknown encryption and refuses edits to signed EPUBs.
- Python regression tests and a synthetic repaired EPUB2's EPUBCheck were successfully executed (see measured verification above). A real Libron ZIP, Windows packaging and reader rendering have **not** been tested. The work remains DRAFT.

## Measured verification — 2026-10-22

- Python 3.12 hosted CI: **45 passed, 1 skipped** on the draft branch (run: https://github.com/Hugowhitee/eBookEngine/actions/runs/39855503087).
- One synthetic, corrected EPUB 2 publication with reconstructed NCX independently passed **EPUBCheck 5.4.0**, with 0 fatals/errors/warnings/infos. This proves that sample, **not** arbitrary real books or EPUB 3 navigation.
- Regression coverage includes source-safe OS debris removal, local-link detection, font-obfuscation classification, explicitly approved queue proposals, restart/error recovery and no-overwrite batch publication.
- Still unverified: real-book render quality, real Libron v0.31 styles and glyphs, Windows packaged runtime, memory benchmarks on large EPUBs, EPUB3 nav reconstruction, TOC hierarchy/footnotes and full ebook-cleanup skill parity.

## Required gates still open

- **Libron (feature branch):** Validate actual four-style v0.31 ZIP import, EPUBCheck 5.4.0 conformance, font/weight/italic rendering in Calibre and Kobo, license notice and a real Windows package; source-level implementation does not mean release proof.
- **Windows native packaged run:** manual Windows Action build, clean unzip/launch, several real interactive file-edit/save workflows; no false `PASS` until demonstrated.
- **UX:** selectable PDF OCR blocks/manual corrections and editable reading order, PDF-to-EPUB region mapping, richer faithful EPUB CSS viewer, accessibility/dark-theme and screen-size QA.
- **Advanced PDF:** in-app installation, speed/RAM/offline/diagram/table/figure completeness on representative illustrated sources, real Docling runtime + model tests.
- **Local AI:** real downloaded CPU runtime/model installation (size/checksum/retry/cancel), deterministic test of proposals and offline reuse, package/runtime tests.
- **Release:** sensible user installation/update path, precise notice bundle, Windows Defender/SmartScreen behavior, output validation on Kobo/Calibre, and privacy/security review.

No auto-costly CI. The manual build must be deliberately invoked; do not label source tests or an unexecuted workflow as a released product.
