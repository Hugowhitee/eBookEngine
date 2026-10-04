# Architecture and engineering decisions

**Status:** candidate design; dependency/engine and Windows performance are **not yet verified**. Confirm with fixtures, real Windows GUI tests and a packaged build rather than treating this document as proof.

## Boundaries and state
- **SourceDocument**: immutable bytes, detected type, verified metadata and provenance. ZIP/XML/HTML/PDF inputs are untrusted: bound expansion sizes, local paths, images, scripts, external references and parser execution.
- **StructuredDocument**: source-linked sections/pages/blocks, figures, tables, text, order, captions and confidence/provenance.
- **ChangeSet**: typed machine/manual proposals; accept/revert/edit and undo/redo, keeping user decisions independent from the extraction engine.
- **Candidate**: regenerated and validated bytes, corresponding to result preview; never pretend an unrendered partial proposal is export-ready.
- **CleanMaster**: nonpersonal repairs only. Optional personal/language edition is a separate versioned derivative with reversible overlay/sidecar, never an implicit default.

## Application shell and viewer
Use a straightforward native Windows UI (provisional: Python 3.12+ with PySide6/Qt) distributed as self-contained installer/portable build, not a script and not a background browser server. PDF pages: PDFium/pypdfium2 candidate, lazy rendering, search and coordinates. EPUB pages: an embedded isolated web viewer/EPUB renderer, no document-origin scripts or uncontrolled remote network access. Compare mode links source regions/sections to candidate, never falsely promises exact page-to-page pairing for reflow.

Workers must avoid freezing UI. Pipeline is queued → inspect → extract/OCR (if needed) → propose repair → validate → review → export; exceptions/cancellation are recoverable. Progress may display genuine stages and page counts; never fabricated percentages or extra main windows.

## Engines (investigate, don't lock in blindly)
- **Fast path:** EPUB ZIP/OCF, XHTML/XML, CSS, NCX/nav and metadata inspection; safe transformations with original-content checks. For digital PDF, prefer faithful page preservation.
- **Advanced PDF/OCR/layout:** local document extraction pipeline with figures, reading order, tables and captions. Benchmark Docling and Datalab Marker (including their Windows/CPU requirements, accuracy, model size, speed, redistribution constraints) against the **same real test fixtures**. Choose one owner in the product, not multiple identical engines bundled by default.
- **Local AI:** embedded optional managed inference backend, compatible pinned model, in-app first-use setup/storage checks and offline reuse. Confirm whether Intel integrated GPU/CPU meets acceptable speed before advertising acceleration. AI should propose bounded changes; never silently rewrite an author's content or fabricate missing OCR.
- **Output builders:** safe PDF/searchable-layer processing and structured reflowable EPUB assembler, links/media/TOC/cover/metadata, validation. Do not rely on opaque one-pass conversion when fidelity cannot be measured.

## Validation and safety
Use format validators plus original-vs-result text/image/page/asset completeness checks, anchors, manifest/spine, cover, metadata, reader/reflow/heading check, image and figure association; validate exact exported bytes. Atomic save with crash-safe temp files and no source overwrite. Local files remain local by default; model downloads are explicit.

## External software and rights
eBookEngine is a distinct independent product with its own code, data model, UI and branding. Researching how another app behaves or adopting noncopyrightable workflows does **not** make this a branded fork. Evaluate code/dependency reuse when it genuinely saves engineering effort; prefer compatible libraries and honor their actual license/redistribution requirements in third-party notices or distribution material as applicable. Never strip legally required notices or imply copied code is independent. No upstream-product names or promotional credits in ordinary UX/marketing unless actually required. Don't bulk-copy application code to avoid due diligence. Verify actual terms for Qt, PDF renderers, OCR models and weights before packaging.

No automatic GitHub Actions costs, cloud dependence or separate admin consoles.
