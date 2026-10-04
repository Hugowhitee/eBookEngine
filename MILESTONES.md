# Milestones and exit gates

## Implemented and tested locally

- EPUB signature/container inspection, full manifest/spine preservation, metadata and cover proposals, source-linked NCX navigation, Undo/Redo, valid output checks and source-safe atomic save.
- PDF digital/scanned recognition, visual rendering, Tesseract searchable layer without repainting, cancellation and preservation of page count.
- Document-first ttk GUI initialized and opened in virtual display with real EPUB source/result cover comparison and change review. A custom user-supplied EPUB containing an actual cover versus ASIN/EBOK placeholder was checked privately (never commit book data).

## Required gates still open

- **Windows native packaged run:** manual Windows Action build, clean unzip/launch, several real interactive file-edit/save workflows; no false `PASS` until demonstrated.
- **UX:** selectable PDF OCR blocks/manual corrections and editable reading order, PDF-to-EPUB region mapping, richer faithful EPUB CSS viewer, accessibility/dark-theme and screen-size QA.
- **Advanced PDF:** in-app installation, speed/RAM/offline/diagram/table/figure completeness on representative illustrated sources, real Docling runtime + model tests.
- **Local AI:** real downloaded CPU runtime/model installation (size/checksum/retry/cancel), deterministic test of proposals and offline reuse, package/runtime tests.
- **Release:** sensible user installation/update path, precise notice bundle, Windows Defender/SmartScreen behavior, output validation on Kobo/Calibre, and privacy/security review.

No auto-costly CI. The manual build must be deliberately invoked; do not label source tests or an unexecuted workflow as a released product.
