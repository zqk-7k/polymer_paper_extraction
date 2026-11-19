# FAQ and brand verification

- FAQ image and base gradient use cover sizing; removed stale fixed-width card background declarations.
- Chromium checks PASS at1920/2560/3440px; FAQ width equals submit width at every size, artwork covers the entire inner card.
- Visually checked2560px capture: no vertical background seam.
- Sidebar and loading state reference assets/logo2.png; recolored to #2353cb palette without resampling or changing alpha (0 changed alpha pixels), preserving1254x1254 dimensions and image geometry.
- Public logo2 matches the asset byte-for-byte. Favicon32x32,192x192 and Apple180x180 generated from that same source.
- HTML selects PNG icons with the updated cache version; no SVG favicon link.
- Production build PASS;3 existing tests PASS; changed TSX lint PASS. API requests mocked for browser UI verification.
