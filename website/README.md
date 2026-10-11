# Prism Router — marketing site

Static landing page for [Prism Router](https://github.com/pavneeta/prism-router) (Model-Router).

## Design

Built with [Nutlope Hallmark](https://github.com/Nutlope/hallmark) conventions:

- **Genre:** modern-minimal
- **Macrostructure:** Narrative Workflow
- **Theme:** custom *Prism Spectra* (dark cool slate · Syne + IBM Plex Sans + JetBrains Mono · cyan spectral accent)
- **Nav:** N8 Terminal command
- **Footer:** Ft5 Statement
- **Enrichment:** hand-built SVG prism apparatus (refraction)

## Local preview

```bash
cd website
python3 -m http.server 5173
# open http://127.0.0.1:5173
# docs UI: http://127.0.0.1:5173/docs.html  (or /docs with a static server that maps clean URLs)
```

### Docs page

`/docs` (`docs.html` + `docs.js`) renders **user/operator** markdown from the repo’s `docs/` folder (not `docs/internal/`).

Markdown is **copied into** `website/docs-content/` by `sync-docs.sh` (also the Vercel `buildCommand`). Edit user docs under `docs/`, run `./website/sync-docs.sh` (or deploy), and the site stays in sync. Engineering docs stay under `docs/internal/` (GitHub only). The public docs viewer also falls back to jsDelivr / raw GitHub on `main`.

## Deploy (Vercel)

Production: [https://prism-router-ten.vercel.app](https://prism-router-ten.vercel.app)

```bash
cd website
npx vercel --prod
```

Root Directory for the Vercel project is `website`. `vercel.json` configures a static deploy from this directory.

Optional GitHub Pages: `.github/workflows/deploy-website.yml` (enable Pages → GitHub Actions in repo settings).
