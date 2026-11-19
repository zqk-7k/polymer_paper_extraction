# Reference UI verification

Reference: user-supplied upload-page screenshot, 1672 × 941.

- Production build: PASS (`npm run build`). Existing bundle-size advisory remains.
- Existing tests: PASS (2/2). Sidebar source assertions now follow the extracted component.
- Changed TSX lint: PASS (App, main, PortalSidebar, PortalBackground, Upload).
- Design detector: PASS (no findings).
- Browser: Chromium headless; desktop 1672 × 941, mobile 390 × 844.
- Main desktop bounds: x225/y72, width1414; upper cards height613; lower section y703/height209.
- Mobile: document width390, no horizontal overflow; stacked upload cards and bottom navigation.
- Interactions: FAQ expansion, credential entry, PDF selection/removal, built-in sample navigation PASS.
- Routes: upload, results, polymer, sample, history, batch, polyinfo render with shared background and sidebar; no uncaught browser errors.
- Independent visual review: ship after helper-copy contrast corrections; waiting badges 4.57:1, corrected helper text ≥4.77:1.

Browser requests were fulfilled from the actual production dist files to avoid the environment's localhost network restriction. API requests returned 503 to exercise the real offline state. Actual PDF extraction/backend connectivity was not tested. The offline warning below the upload panels is intentional, and is absent when the backend is healthy.

Full `tsc --noEmit` is still blocked by existing errors outside the changed files, including the missing data import in src/types.ts and GraphNodePayload references in Results. These errors were not hidden or relaxed.

Screenshots: upload-desktop.png, upload-mobile.png, and six *-desktop.png route captures in this directory.
