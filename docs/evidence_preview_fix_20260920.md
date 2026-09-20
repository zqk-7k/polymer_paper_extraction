# Evidence preview repair (2026-09-20)

## Cause and changes

Batch PDF URLs include `?collection=...`. The old frontend appended
`/pages/6` after this query instead of adding it to the pathname. A live request
for `reference_no_0020284` in `demo30_preview_20260824` returned HTTP 404 using
the old URL, while the corrected endpoint returned HTTP 200, `image/png`.

- Preserve collection and other query parameters when addressing PDF pages.
- Keep the API's zero-based page convention and the UI's one-based labels.
- Do not substitute the demonstration PDF when a batch PDF is unavailable.
- Scope image failures to their URL and provide an explicit retry button.
- Keep existing bbox coordinates (MinerU normalized 0–1000) unchanged.

No Stage, schema, prompt, model call, retry budget, result collection or PDF
was changed. No additional model API costs are introduced.

## Verification

- Python extraction/OCR/publishing/API tests: 734 passed.
- Published collection validation passed (existing legacy/review warnings remain).
- Frontend lint, production build and six frontend tests passed.
- Live old and corrected endpoint probes reproduced 404 versus 200/image/png.
- Interactive browser QA could not run: the browser service rejected the
  connection with `Browser use requires a trusted Node REPL browser service`.
  An API probe and server render are not a substitute for interactive screenshots.

## Deployment and acceptance

Merge through a reviewed PR after CI passes; existing main-branch CI/CD handles
container builds and deployment. No direct push to main is needed. After release,
open a batch property, inspect its evidence image, red bbox and PDF page link.
Also check a task upload result and a missing-source batch. Missing PDFs must
remain unavailable, never resolve to another paper. Check narrow and wide screens.

Rollback is a revert PR for this change. The immutable historical outputs and
local uncommitted evolution work are untouched.
