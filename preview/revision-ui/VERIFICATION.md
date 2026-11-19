# UI correction verification

- Sidebar restored to 256px (collapsed64px). All seven routes use the shared shell.
- Removed two cropped molecular rasters; header and FAQ now share MoleculeIllustration.tsx and the sourced ethane JSON.
- NIST experimental coordinates: https://cccbdb.nist.gov/exp2x.asp?casno=74840&charge=0
- Geometry test:2 carbon+6 hydrogen atoms,7 unique bonds,carbon valence4/hydrogen valence1,C-C1.536Å and C-H1.091Å within coordinate rounding.
- Native browser assertions:both illustrations8 atoms/7 bonds, all sphere glyphs within SVG bounds, circular screen dimensions; mobile first card begins below full header illustration.
- Both credential fields36px; matched light-blue output icons; PDF upload corner mark absent.
- Hover computed styles:primary blue gradient rgb75,112,181→44,80,143;secondary pale blue with rgb35,79,157 text; native remove button pale blue rgb228,236,250.
- Production build PASS;3 node tests PASS; changed TSX lint PASS.
- Chromium desktop1672×941/mobile390×844: no horizontal overflow; PDF selection/removal,FAQ,credential entry,sample load and seven routes PASS; no uncaught page errors.
- Browser harness serves real production dist assets with mocked health and unavailable other APIs. It never submits an extraction task; backend extraction is outside this visual check.
- Design detector reports advisory palette/type documentation drift in the existing legacy CSS, not a clean detector result.

Screenshots: upload-desktop.png, upload-mobile.png, upload-hover.png, six other route desktop captures.
