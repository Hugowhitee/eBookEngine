# Architecture

## State and ownership

`EpubSource` loads immutable ZIP bytes, validates OCF, manifest/spine, media and path safety. `ChangeSession` holds typed proposals and snapshot-based Undo/Redo, reconstructing every candidate from the original. `core.atomic_save` protects original files and writes atomically. PDFium renders source pages. `pdf_engine.searchable_pdf` layers invisible selectable Tesseract text on missing-text PDF pages without repainting source page graphics, then reopens and verifies the output. `conversion` builds reflowable EPUB from structured Docling HTML while carrying a visual page-reference appendix. `local_ai` proposes description text only on explicit request. Its output is never silently applied.

## Windows UI

The actual implementation uses Python 3.12 `tkinter/ttk` for native system buttons and fewer moving parts; the earlier PySide6 choice was provisional. One document-first main window, split source/result viewer, context-specific output selector, TOC/page navigation, editable EPUB cover/metadata, change toggle and Undo/Redo, worker progress/cancel, Save as. EPUB text preview is sanitized and does **not** claim identical pagination/rendering to a Kobo/Calibre renderer. Windows onedir distribution bundles Python, PDFium and Tesseract. No forced login or cloud conversion.

## Optional local engines

- OCR: Tesseract bundled with the manual Windows package. It adds an invisible text overlay only for scanned pages. A real unsupported scan is rejected rather than returning invented text.
- Complex PDF: an in-app setup uses checksum-verified `uv` to create a dedicated Python+Docling environment with predownloaded layout/OCR/table models, without requiring user-entered shell commands. This is a large 12+ GB optional operation and is unverified on Windows. Docling runs out of process; extracted figures can be embedded while all original page renders remain accessible for visual validation.
- Text AI: optional managed Windows CPU llama.cpp binary and checksum-verified Qwen2.5-1.5B GGUF. A bounded local subprocess returns a proposal, not canonical text. No VLM figure-editing is claimed. Models require explicit user download and internet only for that setup.

## Security/quality

Documents never run embedded JavaScript or user macros. EPUB input is size-capped and path-normalized, rejects symlinks/traversal/ambiguous duplicate items, and never resolves external entities. Source content remains byte-preserved except explicit metadata/CSS edits; EPUB output verifies the full original spine/manifest and digests. PDF OCR result reopens with unchanged page count, selectable text layer and rendering-comparison tests. No DRM bypass. External library licenses and model weights are evaluated before shipping; there is no third-party branding in normal UI.

## Current risks

Real Windows packaging, binary redistribution notices, Tesseract DLL/tessdata inclusion, Docling model setup and offline reuse, local-LLM inference, cancellation of heavy child processes, complex PDF table/figure fidelity, manual correction of OCR text/reading order, and accurate rich EPUB CSS rendering are not yet release-proven. Do not elevate the M1 functional prototype to complete product status.
