# eBookEngine

eBookEngine is a self-contained Windows desktop app for opening, inspecting, cleaning, correcting, OCR-processing and exporting EPUB and PDF documents. Its everyday workflow is **Open → Review → Improve → Compare → Save as…**.

## Current development status

**Work in progress, not a released application.** The core EPUB repair, native viewer and scanned-PDF searchable-layer OCR have local automated coverage, but a Windows release and optional downloaded layout/AI engines have **not** been validated on an end-user device. Do not mistake the foundation documents for a finished product.

**Available source functions:** actual file-signature validation; EPUB cover/metadata review (including an unusually clear ASIN-placeholder detection), immutable source, inspectable typed changes with Undo/Redo, full spine and ZIP preservation checks; EPUB TOC navigation; PDF raster preview, scanned-PDF OCR with selectable text over original page imagery; original/result comparison; atomic export validation; optional managed installation paths for local AI and structured PDF layout extraction.

**Limitations:** EPUB preview shows sanitized reading text rather than an exact e-reader CSS layout. PDF OCR editing at arbitrary text-box level is not implemented; image-heavy PDF-to-EPUB reflow must be reviewed and needs the separately installed layout engine. Model installation, extraction speed, setup and packaging on Windows still need real-device validation. Nothing is silently uploaded to a server.

## Running from source (development only)

Python 3.12 with tkinter; `pip install -e .[dev]`, then `python -m ebookengine`.

`python -m pytest -q` runs the core regression suite. The GitHub Actions **Package Windows (manual)** workflow is manual-only and produces a portable ZIP when deliberately launched. A portable Windows build should ultimately launch by double-clicking `eBookEngine.exe` without separately installing Python or Calibre.

See `PRODUCT.md`, `ARCHITECTURE.md` and `MILESTONES.md` for product requirements and honest release gates.
