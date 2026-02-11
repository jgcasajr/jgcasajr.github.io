# CLAUDE.md

## Repository Overview

This is **jgcasajr.github.io**, a GitHub Pages personal site. The repository is currently empty (all prior content was removed in March 2018). It is deployed automatically via GitHub Pages from the `master` branch.

## History

The site originally contained a single-page startup landing page built with:
- Plain HTML (`index.html`)
- Custom CSS (`style.css`)
- Bootstrap 4.0.0-alpha.6 (via CDN)
- Google Fonts (Montserrat)
- MailChimp email signup form integration
- A hero header background image (`header.jpg`)

All files were deleted in commit `6d045e8` (March 2018).

## Project Type

Static HTML/CSS site — no static site generator (Jekyll, Hugo, etc.), no build system, no package manager, no dependencies.

## Directory Structure

```
/
├── CLAUDE.md          # This file
└── .git/              # Git metadata
```

## Development Workflow

### Local Development
No build step required. Open HTML files directly in a browser or use any local HTTP server:
```bash
python3 -m http.server 8000
```

### Deployment
The site is served by GitHub Pages. Pushing to `master` automatically deploys the site to `https://jgcasajr.github.io/`.

### Branching
- `master` — production branch, deployed by GitHub Pages
- Feature branches should be prefixed appropriately (e.g., `claude/...`)

## Conventions

- No build tools or package managers are used; keep the project as plain HTML/CSS/JS.
- External libraries should be loaded via CDN, not vendored.
- Keep the site lightweight — this is a simple personal/landing page.

## Key Files to Know

| File | Purpose |
|------|---------|
| `index.html` | Main (and typically only) HTML page |
| `style.css` | Custom styles |
| `CLAUDE.md` | AI assistant reference (this file) |
