# Product contract

## Product
**eBookEngine** is a standalone, local-first Windows document improvement workbench for a user who wants better EPUBs and PDFs without having to learn Calibre, a developer dashboard or multiple external applications. It combines format detection, rendering, metadata/cover repair, structured OCR, document reconstruction, human review, manual correction and reliable export.

The app is not an ebook library manager and does not advertise itself as a fork, front-end or derivative of a different user-facing product.

## Primary workflow
1. **Open/drop:** PDF, EPUB and KEPUB-EPUB are recognized by content/signature, not just extension. Before opening, the empty state names supported input types. For mismatched suffixes, unsupported formats, password-protected/DRM-protected files, malformed and oversized files, explain why a file cannot be processed. Originals are never changed.
2. **Understand:** viewer loads the original with cover/title/author/format/page count when available. User sees valid output formats and any missing capabilities. Detect image/scan-heavy vs born-digital PDF, fixed-layout vs reflowable EPUB, source images, figures/tables and links.
3. **Improve:** easy one-action automatic analysis and safe default repairs; advanced OCR/layout processing selected automatically when justified or explicitly chosen. Processing has real stages, progress (or honest indeterminate state), time estimates only when grounded, cancel/retry and logs behind a disclosure.
4. **Review:** original and actual candidate side-by-side or toggle, synchronized section/page navigation where meaningful, zoom/search, thumbnail/TOC navigation, images/captions/tables and current metadata/cover. A small **Changes** inspector identifies what changed, where, why and whether confidence is low. The reviewer can accept/revert and correct supported text blocks, reading order, metadata, covers, TOC headings, OCR text and figure/caption association. Undo/Redo is functional.
5. **Save:** output dropdown only offers supported targets for that input; actual path/extension are shown. Rebuild and revalidate after edits; save to a different file atomically. Result preview always corresponds to the exact candidate. The user can inspect or open the saved result.

## Supported formats and outputs
| Input | Safe default | Other supported outputs |
| --- | --- | --- |
| .epub, .kepub.epub | Clean EPUB preserving source content/identity | Reviewed EPUB changes, validated Kobo derivative where useful |
| Born-digital .pdf | Preserve PDF page appearance, metadata/search when justified | Reflowable EPUB; optionally structured HTML/Markdown |
| Scanned or image-heavy .pdf | Searchable PDF with original page appearance retained | Reconstructed EPUB and structured export (review necessary) |
Other image-only formats are not silently promised until their ingestion/OCR is demonstrated.

Reconstruction of multi-column layouts, graphics, footnotes, equations and nested tables is **not inherently lossless**. Surface uncertainty instead of inventing or silently dropping material. A text/edit layer is not equivalent to unrestricted Acrobat-like page-layout editing.

## AI / OCR
Advanced local OCR and document reconstruction and on-device AI are **required product capabilities**, but must not slow down or block fast deterministic EPUB cleaning. Model/runtime download is requested when needed and handled inside the GUI with size, disk/RAM prerequisites, progress, cancel/retry, clear error guidance and offline functionality after installation. Local AI proposes changes rather than silently overwriting author content. Personal annotations or translated editions are **rare optional actions**, outside the default workflow, built as reversible derivatives of a clean master.

## Native-feeling UI contract
One calm document-first Windows window. Small toolbar: **Open**, contextual **Output** selector, **Improve**, **Save as**. Center viewer: Original | Compare | Result; search, zoom and chapter/page controls. Right contextual Changes inspector, not a full-time options dashboard. Bottom status/progress/cancel. Compact rectangular system-style controls; match light/dark Windows settings. Every visible enabled button must work; unavailable actions give concrete reasons. Hide model/runtime/engine options until relevant.

## Non-goals
No accounts, library database, forced cloud, mandatory AI, chat agent, Acrobat-style painting/signing/forms, file-sync platform, telemetry, silent background downloads, publisher identity rewriting, or automated personal health advice.

## Acceptance fixtures / regressions
- EPUB has actual book-cover image plus retailer placeholder; choose actual cover, preserve provenance, fill only grounded metadata/description.
- Multi-spine EPUB keeps **all** original text/images/links and chapters; fix orphaned headings (no title isolated at page end) and preserve reader controls/dark mode.
- Source/result previews show real current bytes; manual edit→Undo/Redo→revalidate→Save produces valid new artifact; no stale preview.
- Source PDF with two columns, multiple figures/tables/captions/footnotes has traceable reading order, no silently missing regions, and explicit unresolved cases.
- Scanned PDF retains visible page appearance in searchable-PDF mode; extracted OCR can be selected/searchable; corrections work and uncertainty is visible.
- Wrong extension, malformed ZIP, path traversal/ZIP bomb, encryption, remote content and embedded scripts fail safely without executing book-supplied code.
- Fresh Windows launch needs no user-installed Python, Calibre, Ollama, Ghostscript or shell commands. Optional model setup and offline rerun work in-app; no fake progress.
- Cancellation/crash preserves source and last valid candidate, cleans temporary files; saved output is validated independently.
