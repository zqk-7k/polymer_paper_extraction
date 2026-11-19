# Raster background revision verification

- FAQ and submission module share the same .938fr/1fr tracks and18px gap; measured widths650.015625px each at1672px desktop.
- Portal PNG2560×1440; FAQ PNG1600×480. Transparent PNG sources contain embedded provenance metadata.
- Assets rendered from the NIST ethane coordinates and explicit connectivity using depth-tested3D sphere/cylinder surfaces. Portal composition7 independent molecules; FAQ5. No invented bonds between separate molecules; safe image bounds checked during generation.
- Glass-like material uses soft icy-blue lighting and translucent Fresnel rims. Both backgrounds use CSS automatic height for uniform scaling.
- Browser asserts PNG background URLs and zero molecular SVG elements in DOM.
- Production build PASS;3 existing node tests PASS; changed TSX lint PASS.
- Desktop1672×941 and mobile390×844 captures; no horizontal overflow. Seven route renders, credential/file/FAQ/sample controls, blue hover checks PASS with no uncaught browser errors.
- Browser health is mocked only for UI state verification; actual extraction is not exercised.

Final screenshots: upload-desktop.png, upload-mobile.png, upload-hover.png and six other route captures.
