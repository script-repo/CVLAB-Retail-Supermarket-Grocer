# Retail-Supermarket-Grocery Computer Vision Use-Case Portal

A static, no-build portal that catalogues 20 grocery computer-vision use cases with footage plans, demo tools, and recording guidance. Styled with the **Retail-Supermarket-Grocery design language** (see `../Retail-Supermarket-Grocery-Style-Guide.md`).

## Run it

No build step. Just serve the folder:

```bash
# from cv-portal/
python -m http.server 8080
# open http://localhost:8080
```

Opening `index.html` directly works too, but a local server is recommended so videos load reliably.

## Structure

```
cv-portal/
├── index.html          # markup: header, hero, 3 tabbed views, modal
├── assets/
│   ├── theme.css       # Retail-Supermarket-Grocery design tokens (colors, type, radius, shadow)
│   ├── styles.css      # component styles (consumes theme.css)
│   ├── data.js         # CONTENT: patterns, 20 use cases, tools, recording guide
│   └── app.js          # logic: filtering, search, modal, video fallback
└── videos/             # drop footage here (see naming below)
```

## Adding footage

Each use case auto-loads a video by convention:

```
videos/NN-slug.mp4
```

where `NN` is the zero-padded id and `slug` is the use case slug from `data.js`. Examples:

```
videos/01-cashierless-checkout.mp4
videos/02-out-of-stock.mp4
videos/14-age-verification.mp4
```

If a file is missing, the card and modal show a **"Footage pending"** placeholder automatically — so you can ship the portal before all clips are recorded. To point at a custom path/URL, set `video: "..."` on that use case in `data.js`.

## Editing content

All content lives in `assets/data.js` — no code changes needed:

- `PATTERNS` — the 6 CV categories and their accent colors (used for filters and card accents).
- `USE_CASES` — title, camera angle, framing, action, CV overlay, loop goal.
- `TOOLS` — public demo tools (verify Space URLs before presenting).
- `RECORDING` — global capture settings and ground rules.

## Theming

Colors, fonts, radii, and shadows are CSS variables in `assets/theme.css`, derived from `../Retail-Supermarket-Grocery-Style-Guide.md` (primary green `#003D2A`, warm cream `#E9E3D2`, Poppins type, rounded/pill shapes). Change a token once and it applies everywhere.

## Notes / guardrails

- Use controlled mock-store footage, actors with consent, no real customer faces or payment cards, generic/blurred brand labels.
- Privacy use cases (age verification, signage) are intentionally framed as assisted/anonymous workflows, not biometric identification.
