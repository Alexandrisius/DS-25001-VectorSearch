# web/ — KSR Vector Search frontend

The public search UI (index.html) and the admin panel (admin.html)
together form the entire web layer. No build step, no bundler:
plain HTML + ES modules + CSS. `make` is not involved here — the
files are volume-mounted into the api container
(`./web:/app/web:ro`) and changes are visible immediately.

## Layout

```
web/
├── index.html             — public search UI (no auth)
├── admin.html             — admin panel (JWT auth)
└── static/
    ├── favicon.svg
    ├── fonts/             — Font Awesome woff2 (6.4.0)
    ├── css/
    │   ├── font-awesome.min.css   — third-party, not touched
    │   ├── shared/                — used by BOTH pages
    │   │   ├── 00-tokens.css     ← single source of truth
    │   │   ├── 01-base.css       ← reset, body, focus-visible
    │   │   ├── 02-animations.css ← every @keyframes
    │   │   └── 03-utilities.css  ← .hidden, .spinner, .visually-hidden
    │   ├── app/                   — only loaded by index.html
    │   │   ├── 10-tokens.css
    │   │   ├── 20-layout.css
    │   │   ├── 30-components.css
    │   │   ├── 40-catalog.css
    │   │   ├── 50-toast.css
    │   │   └── 60-responsive.css
    │   └── admin/                 — only loaded by admin.html
    │       ├── 10-tokens.css
    │       ├── 20-layout.css
    │       ├── 30-components.css
    │       ├── 40-data-table.css
    │       ├── 50-import-wizard.css
    │       ├── 60-diff.css
    │       ├── 70-statuses.css
    │       ├── 80-openrouter.css
    │       ├── 85-settings-layout.css
    │       ├── 90-cleaning-rules.css
    │       ├── 95-jobs-and-config.css
    │       └── 99-utilities.css
    └── js/
        ├── shared/                — utilities used by both apps
        │   ├── api.js            ← authFetch (JWT, 401 reload)
        │   ├── constants.js      ← status labels, storage keys, intervals
        │   ├── dom.js            ← escapeHtml, formatDateTime
        │   ├── events.js         ← debounce, rafSchedule
        │   └── focus-trap.js     ← modal focus management (a11y)
        ├── app/                   — public UI
        │   ├── main.js           (bootstrap)
        │   ├── state.js          (appState, filterState, catalogState)
        │   ├── els.js            (DOM registry)
        │   ├── theme.js          (light/dark toggle)
        │   ├── database.js       (db list + active selection)
        │   ├── custom-select.js  (custom dropdown)
        │   ├── search.js         (/match)
        │   ├── results.js        (table render)
        │   ├── results-handlers.js (copy / dislike)
        │   ├── catalog-handlers.js  (db-card / result-category)
        │   ├── analytics.js      (feedback events)
        │   ├── filter.js         (multi-select filter)
        │   └── catalog/
        │       ├── sidebar.js           (composition root)
        │       ├── sidebar-toggle.js    (toggle + resize)
        │       ├── sidebar-controls.js  (refresh + collapse)
        │       ├── tree.js              (composition root)
        │       ├── tree-loader.js       (loadHierarchy / loadChildren)
        │       ├── tree-renderer.js     (renderTreeLazy / renderTreeNodesLazy)
        │       ├── tree-handlers.js     (per-node click / long-press)
        │       ├── breadcrumbs.js       (sticky breadcrumbs)
        │       ├── navigation.js        (expand / scroll-to-category)
        │       └── search.js            (semantic category search)
        └── admin/                 — admin panel
            ├── main.js           (bootstrap)
            ├── state.js          (state.token, collections, dataRows, ...)
            ├── els.js            (DOM registry)
            ├── auth.js           (login, JWT validation, logout)
            ├── navigation.js     (view switcher)
            ├── modals.js         (open/close, resize, focus-trap)
            ├── mobile.js         (mobile warning overlay)
            ├── collections/      (list / config / create / delete)
            ├── data-table/       (render-header / render-row / render /
            │                      sort / inline-edit / scroll / status /
            │                      delete-record / add-record / columns-resize)
            ├── import/           (wiring / state / paste / excel /
            │                      source-tabs / preview / mapping / diff/
            │                      tabs / load / analyze / render / render-tables /
            │                      run-analysis / run-upload / run-apply /
            │                      jobs-list / jobs-watch / jobs-poll)
            ├── cleaning-rules/  (list / form / targets / preview / templates /
            │                      events)
            └── settings/         (statuses-list / statuses-form /
                                   openrouter-state / openrouter-display /
                                   openrouter / openrouter-test)
```

## Architecture

- **No build step.** Each HTML file has `<link rel="stylesheet"">`
  tags for CSS and `<script type="module">` for JS. The browser
  fetches them all in parallel and dedupes. No webpack, no esbuild.
- **Module boundaries follow the page boundary.** Files in `app/`
  never import from `admin/`, and vice versa. Shared utilities live
  in `shared/`.
- **Tokens are cascading, not duplicated.** `shared/00-tokens.css`
  defines every design variable. The `app/10-tokens.css` and
  `admin/10-tokens.css` files just re-export marker files; the
  page-specific CSS layers re-use the same vars.
- **Dark theme = `[data-theme="dark"]` on `<html>`.** Default theme
  is `dark` if the user has no manual choice and the OS prefers
  dark, otherwise light. Implemented entirely in
  `shared/00-tokens.css`.
- **Reduced motion is respected.** `prefers-reduced-motion: reduce`
  kills all animations and transitions in one CSS rule.

## Naming

- **CSS classes** use kebab-case. Some legacy classes from the
  pre-refactor codebase remain (e.g. `.btn-primary`, `.card-header`,
  `.sidebar-footer`); the new code uses the same patterns. No
  BEM strictness is enforced, but elements that have variants use
  a modifier-like pattern (`.btn--success`, `.data-table-full`).
- **JS modules** use kebab-case file names. Each file has a JSDoc
  header explaining its single concern.
- **Tokens** use kebab-case with semantic prefixes: `--color-*`
  (not `--blue-500`), `--space-*` (4px base, 1-12), `--radius-*`,
  `--shadow-*`, `--z-*`, `--transition-*`. Legacy names
  (`--primary`, `--text-main`, `--adm-primary`) are kept as aliases
  in `shared/00-tokens.css` for zero-regression compatibility.

## Cache busting

Every CSS link uses `?v=N` where N is the current refactor version.
Bump N in BOTH HTML files when you change CSS. JS uses content-
addressed imports (no version needed — the browser caches
immutable ESM modules).

## Adding a new component

1. Pick the right layer:
   - If it's used by both pages → `shared/`
   - If it's only for the public UI → `app/`
   - If it's only for the admin panel → `admin/`
2. Add a token (color / spacing / radius) to `shared/00-tokens.css`
   if it's a new design value. Don't hardcode hex / px values.
3. Add the styles to the appropriate layer file
   (`30-components.css`, `40-data-table.css`, etc.). Match the
   existing patterns in that file.
4. Wire the JS in a module that owns that concern. Don't add
   listeners from main.js — make a sub-module that exports
   `init*` and call it from main.js.

## Smoke test

A Playwright smoke test lives at `C:\tmp\ksr-smoke\test_all.mjs`.
It logs into /admin, walks through every admin view, then loads
/ and exercises the public UI. Run after any change:

    cd C:\tmp\ksr-smoke
    node test_all.mjs

Pass criterion: `✓ NO ERRORS` in the summary, 21 green check-marks
total.
