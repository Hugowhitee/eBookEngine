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
| Navigation/TOC/footnotes/spine repair | Read and protect spine, no automatic repair | Working internal links, NCX/nav and note callbacks |
| CSS/reflow and typography | Narrow CSS repair; opt-in Libron backend in draft | E-reader render, dark mode, all font styles, glyph coverage |
| Watermark/OCR/conversion artifact removal | Not implemented in existing EPUB cleanup | Only verified non-book text removed |
| Metadata, privacy and covers | Partial metadata editing and cover proposals | Real bookstore/Calibre checks; source provenance |
| EPUB3/ZIP/link/font/reader validation | Partial self-check; no EPUBCheck integration | Independent EPUBCheck and content preservation |
| Kobo master/KEPUB decision | Not implemented | Master first; derivative only if requested |
| Several books in a queue | Persisted EPUB-only backend; no GUI, no PDF batch | restart/retry/cancel, bounded memory, batch UI QA |

Do not call a book clean merely because it passed archive inspection or its metadata changed.

## Required gates still open

- **Libron (feature branch):** Validate actual four-style v0.31 ZIP import, EPUBCheck 5.4.0 conformance, font/weight/italic rendering in Calibre and Kobo, license notice and a real Windows package; source-level implementation does not mean release proof.
- **Windows native packaged run:** manual Windows Action build, clean unzip/launch, several real interactive file-edit/save workflows; no false `PASS` until demonstrated.
- **UX:** selectable PDF OCR blocks/manual corrections and editable reading order, PDF-to-EPUB region mapping, richer faithful EPUB CSS viewer, accessibility/dark-theme and screen-size QA.
- **Advanced PDF:** in-app installation, speed/RAM/offline/diagram/table/figure completeness on representative illustrated sources, real Docling runtime + model tests.
- **Local AI:** real downloaded CPU runtime/model installation (size/checksum/retry/cancel), deterministic test of proposals and offline reuse, package/runtime tests.
- **Release:** sensible user installation/update path, precise notice bundle, Windows Defender/SmartScreen behavior, output validation on Kobo/Calibre, and privacy/security review.

No auto-costly CI. The manual build must be deliberately invoked; do not label source tests or an unexecuted workflow as a released product.
