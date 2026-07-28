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
```

## Deploy (Vercel)

```bash
cd website
npx vercel --prod
```

`vercel.json` configures a static deploy from this directory.
