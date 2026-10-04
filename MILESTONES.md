# Milestones and release gates

This project is **not released** until verified in real packaged Windows runtime. Milestone progression does not remove required product scope.

## M0 — Foundation and engine probe
- Define exact source/change/candidate contracts and UI behavior; choose runnable Windows packaging approach.
- Benchmark 3–5 representative redistributable EPUB/PDF documents, including broken cover, split TOC and real scan/complex figures.
- Compare PDF/OCR extraction engine candidates on quality, local speed/memory, licensing of actual binaries/weights and Windows install friction.
- Exit: an executable test can detect file signatures and report real document metadata/sections without network or data loss. Owner and engine decisions updated from results.

## M1 — Real viewer and fast processing
- One usable Windows main window, drag/drop/open, type recognition and allowed outputs.
- Real PDF/EPUB original preview, chapters/pages/zoom/search, metadata/cover review.
- Safe EPUB cleanup and basic PDF preservation; Changes inspector, manual edit for proven supported fields, Undo/Redo, candidate preview, save with validation.
- Honest phases/cancel/error and output-file readback; zero placeholder controls.
- Exit: run and test on target Windows system, including packaged clean install. This is not the final product.

## M2 — Complex PDF/OCR and editing
- Integrate selected local OCR/layout engine through in-app first-use installation. Handle scanned pages, figures, tables, caption ordering, two columns, footnotes where possible.
- OCR searchable-PDF output preserving imagery and PDF→EPUB/structured export with reviewable uncertainties.
- Per-region corrections, source-linked comparison, cancellation/recovery, CPU slow/memory cases and asset/text completeness.
- Exit: benchmark fixtures and manual visual review; no silent loss.

## M3 — Managed local AI and finish
- AI model/runtime in-app install/update/remove, disk/RAM checks, download progress/resume/cancel, offline inference, explicit proposal review and normal non-AI fallback.
- Optional separately triggered language/personal derivative; clean master never polluted.
- UI/accessibility polish, usability on normal/laptop display, dark/light, installer/release smoke tests.
- Exit: no missing advertised capabilities, complete content preservation tests, real fresh Windows installer and documented model performance/limitations.

Do not enable automatic expensive CI/reviews, ship developer interfaces, or label partial work as completed. Keep one coherent mainline and avoid branch/release clutter.
