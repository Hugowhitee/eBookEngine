# eBookEngine — agent entrypoint

Read [PRODUCT.md](PRODUCT.md), [ARCHITECTURE.md](ARCHITECTURE.md), and [MILESTONES.md](MILESTONES.md). This repository is the source of truth for project-specific requirements and implementation state. For general work methods, read the live Google Drive AI router `Digitaal/AI/AI werkinstructies/Overzicht.md` and its smallest applicable skill set.

## Invariants
- eBookEngine is its **own product and interface**, not a branded downstream fork. External apps may serve as behavior benchmarks. Evaluate actual library/code reuse separately; preserve required third-party notices without inserting promotional upstream branding into the interface or README.
- One compact, ordinary Windows GUI; real controls, real source/result previews, meaningful progress, cancellation, visible error recovery; no developer dashboards or placeholder buttons.
- Keep the original immutable. Detect actual file signatures, build typed proposed changes with accept/revert and Undo/Redo, preview the exact candidate bytes, then validate those **same output bytes** before atomic save.
- Ordinary PDF/EPUB processing runs offline without an AI model. OCR and on-device AI must be supported through guided in-app installation with storage/capability checks, measurable progress and cancellation; no user-facing CLI setup.
- Do not silently omit author text, images, figures, tables, pages, TOC links, source provenance or metadata. Show uncertain changes and retain original when unresolved.
- Never commit personal documents, copyrighted book excerpts, medical details, user files, external model weights, secrets, installer binaries or temporary caches.

## Proof before claims
Build/run the app; use real, **redistributable** fixture documents; test PDF/EPUB import, source/result viewer, edits and undo, export-file integrity, OCR/searchable PDF, complex PDF reflow, model setup, offline reuse, Windows packaged install and end-to-end interaction. Mark unsupported runtime tests **UNVERIFIED**, not passing. Document a successful operation only after readback from the generated file. Avoid excess branches/PRs and unnecessary GitHub Actions.
