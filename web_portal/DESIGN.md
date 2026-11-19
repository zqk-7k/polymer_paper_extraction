---
name: PolymerLit Portal
description: Screenshot-led blue-gray portal with pale layered surfaces and compact native controls.
colors:
  brand: "#2457ce"
  brand-dark: "#284780"
  brand-soft: "#e1e8fb"
  text: "#142037"
  muted: "#64728c"
  page: "#eef1f7"
  heading: "#080e18"
  card-border: "#ffffffa8"
  divider: "#e9edf5"
  input-surface: "#ffffffcf"
  input-border: "#e1e6f0"
  nav-active: "#dbe3f9"
  nav-active-text: "#2353cb"
  nav-hover: "#e6ebf7"
  nav-text: "#41516e"
  secondary-copy: "#5e6c84"
  pipeline-status-text: "#5c6a82"
  focus: "#356af0"
  white: "#fff"
  memory-surface: "#aeeacb"
  memory-text: "#235e4e"
typography:
  title:
    fontFamily: 'MiSans, "PingFang SC", -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif'
    fontSize: "18px"
    fontWeight: 750
    lineHeight: "24px"
  body:
    fontFamily: 'MiSans, "PingFang SC", -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif'
    fontSize: "14px"
  navigation:
    fontFamily: 'MiSans, "PingFang SC", -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif'
    fontSize: "14px"
    fontWeight: 650
  caption:
    fontFamily: 'MiSans, "PingFang SC", -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif'
    fontSize: "12px"
    lineHeight: "17px"
rounded:
  card: "17px"
  field: "12px"
  navigation: "13px"
  inset: "14px"
  dropzone: "15px"
  action: "21px"
  pill: "999px"
spacing:
  card-gap: "18px"
  card-inline: "24px"
  sidebar-inset: "16px"
  shell-top: "72px"
  shell-left: "22px"
  shell-right: "33px"
components:
  card:
    backgroundColor: "linear-gradient(125deg,#ffffffef,#fbfcfff0)"
    rounded: "{rounded.card}"
  upload-card:
    rounded: "{rounded.card}"
    padding: "14px 24px 20px"
    height: "625px"
  button-primary:
    backgroundColor: "linear-gradient(170deg,#405da5,#284681)"
    textColor: "{colors.white}"
  button-primary-hover:
    backgroundColor: "linear-gradient(170deg,#496db9,#233e78)"
  upload-action:
    rounded: "{rounded.action}"
    height: "40px"
  input:
    backgroundColor: "{colors.input-surface}"
    rounded: "{rounded.field}"
  navigation:
    textColor: "{colors.nav-text}"
    typography: "{typography.navigation}"
    rounded: "{rounded.navigation}"
    padding: "8px 11px"
    height: "36px"
  navigation-active:
    backgroundColor: "{colors.nav-active}"
    textColor: "{colors.nav-active-text}"
  memory-chip:
    backgroundColor: "{colors.memory-surface}"
    textColor: "{colors.memory-text}"
    rounded: "{rounded.pill}"
    padding: "1px 7px"
---

# Design System: PolymerLit Portal

## Overview

The user's pinned screenshot is the visual authority. The implemented portal uses a pale blue-gray canvas, softly raised white cards, rounded inset controls, dark blue gradient actions, and compact Chinese interface typography. This document records the current implementation; it introduces no product strategy or new brand metaphor.

The shared shell carries the same sidebar, background, card surfaces, and control treatments across portal routes. Native interactive UI remains the working interface; image crops supply the brand mark and decorative document detail, while large transparent PNG compositions supply the light icy-blue molecular artwork.

**Key Characteristics:**
- Cool, layered pale surfaces with restrained blue accents.
- Compact labels, strong card titles, and subtle structural dividers.
- Soft exterior shadows with white inset highlights.
- Shared navigation and background with route-specific content layouts.

Source of truth: `src/styles/portal-theme.css`, the final reference overrides in `src/pages/Upload/style.css`, `src/components/PortalSidebar.tsx`, and `src/components/PortalBackground.tsx`. `src/main.tsx` imports legacy `src/index.css` before `portal-theme.css`. The final theme deliberately overrides legacy rules with reference-scoped selectors and specificity guards. Page CSS still supplies structural rules and more specific component variants; evaluate the complete cascade rather than copying an earlier declaration.

## Colors

The palette combines blue accents with cool, nearly white surfaces. Frontmatter records reusable color values; gradients and shadows retain their exact CSS in the sidecar.

### Primary
- **Brand blue:** links and shared accent identity.
- **Dark blue:** anchor tone for primary actions, reinforced with the implemented gradient.
- **Soft blue:** supporting accent surface.
- **Active navigation blue:** selected-route text and a pale blue selection surface.

### Secondary
- **Memory green:** the small memory/status pill; keep it contextual to that indicator.

### Neutral
- **Page blue-gray:** body fallback beneath the layered shared background.
- **Text ink / heading ink:** body copy and emphasized card headings.
- **Muted blue-gray / secondary copy:** supporting information, hints, and empty states. Upload's final readability override uses the secondary-copy token for credential placeholders, file-empty text, and idle text; pipeline status pills use the separate pipeline-status-text token.
- **Translucent white:** inputs and raised cards, with cool fine dividers.

**The Layered Surface Rule.** Use the implemented pale gradients and white highlights together; a flat white replacement loses the reference's material depth.

## Typography

**Body and interface font:** MiSans with PingFang SC and system sans-serif fallbacks. The inherited stack also applies to labels and code badges; pipeline codes are deliberately not a separate monospace identity.

The interface is dense and functional. Card titles are bold; support copy is smaller and quieter. There is no separate display-font system.

### Hierarchy
- **Title:** the frontmatter title role defines shared card headings.
- **Body:** the base role defines body and action-label sizing.
- **Navigation:** the navigation role applies to sidebar links.
- **Caption:** the caption role applies to card subtitles.
- **Upload details:** step labels and pipeline names use strong body-sized text (750 weight); credential labels use smaller text (12px, 650 weight). Microcopy uses smaller sizes (10–11px), and progress numerals use larger tabular figures (22px).

## Layout

At the pinned desktop reference size (1672 × 941px), the expanded sidebar occupies (256px). The content origin is (x278px, y22px): sidebar plus the content left inset. Content has asymmetric desktop padding (22px 33px 28px 22px), fills available width, and has no extra enclosing card, max-width, border, or shadow. Collapsed navigation occupies (64px), with the background and shell shifting together.

Cards use a vertical glass gradient: the top edge is translucent so the fixed molecular artwork reads through the upper part of the right-hand card on every route, and the surface fades to its opaque white body by 300px. The card border, inner top highlight and body copy remain unchanged, so content below the decorative band keeps its original contrast. The top-right card on each route is the one that overlaps the artwork; no per-page markup is required because the gradient is part of the shared `.ucard` surface.

The upload page uses two grids with identical proportional tracks (.938fr / 1fr) and an inter-card gap (18px), keeping the FAQ card exactly as wide as the submit card above it. Upper cards have height (665px) and internal padding (14px 24px 20px). Lower cards have minimum height (248px) and padding (20px 24px 20px), with a 56px header so titles clear the top edge. These dimensions describe Upload's reference composition, not a fixed height requirement for every route.

At widths up to (1250px), Upload reduces card inline padding and compacts pipeline text. At widths up to (1100px), both Upload grids stack; upper cards become auto-height with a minimum (600px), and shell padding becomes (40px 20px 28px). At widths up to (767px), the sidebar is hidden, shell/background left offset is removed, and bottom navigation replaces it; content padding becomes (80px 14px 90px). At widths up to (560px), credential fields, upload actions, and output items stack, with compact type and card insets (16px). Earlier legacy breakpoints remain in source; these reference overrides govern the refreshed composition.

## Elevation & Depth

Depth combines layered background gradients, gentle blue-gray exterior shadows, and white inset highlights. Card boundaries are translucent white rather than heavy outlines. Inputs and inset panels use smaller shadows; primary actions have a darker shadow and a top highlight. Exact shadow values are maintained in `.impeccable/design.json`.

**The Shared Depth Rule.** Keep the same ambient card treatment across routes; reserve smaller inset highlights for controls and nested status panels.

## Shapes

Cards use gently curved corners; fields and FAQ rows are tighter, navigation slightly softer, and upload actions are pill-like. The frontmatter records each observed radius. Upload's dropzone has its own rounded contour and clips decorative art. Numeric step markers remain circular; memory and status indicators remain pills. Do not replace all shapes with one universal radius.

## Components

### Buttons

Primary actions use a dark blue gradient, white labels, fine blue borders, a soft outer shadow, and an inset highlight. Hover changes the gradient; disabled primary controls normally reduce opacity, while Upload's start action has an explicit opaque disabled treatment. Upload actions use the frontmatter action height and radius. The secondary upload action uses a pale gradient and blue text. Preserve semantic disabled behavior independently of visual styling.

Keyboard focus uses the shared visible blue outline (2px) with offset (3px). Existing short CSS transitions handle state changes; reduced-motion preferences remove animations and transitions.

### Cards / Containers

The shared card treatment supplies the translucent white gradient, white border, rounded corners, and ambient shadow. Headings are separated with a cool fine rule. Upload adds its own geometry and header sizing; other routes retain their content structures under the same surface language.

### Inputs / Fields

Ant Design input-affix wrappers and select selectors share a translucent white surface, cool border, rounded field shape, and small shadow. Upload credentials compact affix wrappers to a control height (36px) with padding (3px 10px). Preserve existing Ant Design focus, validation, and disabled semantics beneath the shared focus outline.

### Navigation

`PortalSidebar` owns grouped navigation, current-route selection, collapsed labels, and footer controls. Links use compact rounded rows and stroke SVG icons (16px). Selection has a pale blue fill and inset highlight; hover has a lighter blue-gray fill. The sidebar footer's settings control has a dark gradient. Collapse is revealed on brand hover or keyboard focus; the compact logo expands the sidebar. Mobile uses the shared bottom navigation.

### Chips and pipeline rows

Upload's step chips use pale blue gradients, with a darker variant for the pipeline card. The memory indicator uses its contextual green surface and outlined dot. Pipeline rows combine circular step markers, strong names, small code badges, status pills, and quiet supporting copy. Preserve row separators and the progress inset panel.

### Decorative reference assets

`PortalBackground` is fixed, noninteractive, and hidden from assistive technology. It contains an empty decorative background div; CSS displays `public/upload-art/molecular-portal-large.png` (2560 × 1440px). The FAQ uses `public/upload-art/molecular-faq-large.png` (1600 × 480px) on a noninteractive `::before` layer. Both large transparent raster compositions follow the reference's pale icy-blue appearance and blend into the existing card and shell gradients. There is no `MoleculeIllustration` component.

`scripts/render-molecular-art.cjs` exports both PNGs deterministically from real small-molecule models in `src/data/molecules`: benzene (C6H6), ethane (C2H6), water (H2O), an eight-carbon all-trans oligomer for the portal and a six-carbon one for the FAQ, generated by `scripts/build-polyethylene-chain.cjs`. Per-pixel depth testing renders spherical atoms and cylindrical bonds. The portal scene spreads the motifs across the top band at varied scales and rigid rotations with a horizontal alpha falloff; the FAQ keeps a compact radial cluster. Both read as composed molecular groups rather than a chain strip. Only rigid rotations and uniform orthographic scaling are permitted; atoms remain spherical, and each complete molecule stays within the image bounds. Separate molecules have no bonds between them. Bond lengths, angles and ethane coordinates follow NIST CCCBDB experimental geometry; do not substitute generated molecular topology or stretched atom imagery. Ball-and-stick radii/colors are illustrative, not an electron-density model or an identification of the extracted polymer.

The shared image uses proportional CSS sizing (1280px auto) and opacity (.64), reduced to (800px auto) and (.44) at the mobile-navigation breakpoint. The FAQ image layer and underlying gradient both use proportional `cover` sizing to fill wide cards without a fixed-width seam; artwork opacity is (.36), reduced to (.3) on mobile. `PortalSidebar` and the boot view use `src/assets/logo2.png`, recolored to #2353cb with its original dimensions and alpha mask intact; tab icons are matching 32px/192px PNGs, with a 180px Apple icon; Upload uses `document-decoration.png` inside the dropzone.

## Do's and Don'ts

### Do:
- **Do** treat the pinned screenshot and the final reference cascade as the authority for this visual update.
- **Do** reuse the shared sidebar and decorative background across routes.
- **Do** preserve desktop geometry while applying the documented responsive behavior.
- **Do** retain visible keyboard focus, readable secondary copy, semantic controls, and reduced-motion handling.
- **Do** keep Upload's fixed desktop composition scoped to Upload.

### Don't:
- **Don't** restore earlier legacy sidebar dimensions or flat surface rules over the reference theme.
- **Don't** replace functional UI with a screenshot or decorative image.
- **Don't** introduce route-specific navigation shells or unrelated typography and card materials.
- **Don't** infer product positioning, new page content, or unsupported brand commitments from decorative imagery.
