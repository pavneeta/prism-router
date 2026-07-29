/**
 * Docs viewer — fetches markdown from GitHub docs/ (via jsDelivr) and renders it.
 * Stays in sync with main without redeploying the marketing site for every doc edit.
 */
(function () {
  "use strict";

  const REPO = "pavneeta/prism-router";
  const BRANCH = "main";
  /** Bundled copy (private repos cannot hit raw GitHub from the browser). */
  const LOCAL_BASE = "./docs-content/";
  const CDN_BASE = `https://cdn.jsdelivr.net/gh/${REPO}@${BRANCH}/docs/`;
  const RAW_BASE = `https://raw.githubusercontent.com/${REPO}/${BRANCH}/docs/`;
  const GITHUB_BLOB = `https://github.com/${REPO}/blob/${BRANCH}/docs/`;

  /** Curated nav (mirrors docs/README.md; excludes stress_runs internals). */
  const CATALOG = [
    { id: "README", title: "Index", file: "README.md" },
    { id: "USAGE", title: "Usage", file: "USAGE.md" },
    // Architecture hidden from docs UI nav (file kept in docs/)
    { id: "BENCHMARKS", title: "Benchmarks", file: "BENCHMARKS.md" },
    { id: "OPENCODE", title: "OpenCode", file: "OPENCODE.md" },
    { id: "HERMES", title: "Hermes", file: "HERMES.md" },
    { id: "HOLMESGPT", title: "HolmesGPT", file: "HOLMESGPT.md" },
    { id: "HARNESS_BENCH", title: "Harness bench", file: "HARNESS_BENCH.md" },
    { id: "STRESS_BENCH", title: "Stress bench", file: "STRESS_BENCH.md" },
    { id: "TROUBLESHOOTING", title: "Troubleshooting", file: "TROUBLESHOOTING.md" },
    { id: "SECURITY", title: "Security", file: "SECURITY.md" },
    { id: "CI", title: "CI / release", file: "CI.md" },
    { id: "RAILWAY", title: "Railway deploy", file: "RAILWAY.md" },
    { id: "AB_ANTHROPIC_VS_FIREWORKS", title: "A/B notes", file: "AB_ANTHROPIC_VS_FIREWORKS.md" },
  ];

  const navEl = document.getElementById("docs-nav");
  const articleEl = document.getElementById("doc-article");
  const pathEl = document.getElementById("docs-path");
  const githubEl = document.getElementById("docs-github");
  const refreshBtn = document.getElementById("docs-refresh");

  function docIdFromLocation() {
    const params = new URLSearchParams(window.location.search);
    const q = params.get("doc");
    if (q) return normalizeId(q);
    const hash = (window.location.hash || "").replace(/^#/, "");
    if (hash && !hash.includes("/")) return normalizeId(hash);
    return "USAGE";
  }

  function normalizeId(raw) {
    return String(raw)
      .replace(/\.md$/i, "")
      .replace(/^docs\//i, "")
      .trim();
  }

  function entryFor(id) {
    const upper = id.toUpperCase().replace(/-/g, "_");
    return (
      CATALOG.find((d) => d.id.toUpperCase() === upper) ||
      CATALOG.find((d) => d.file.toUpperCase() === `${upper}.MD`) ||
      CATALOG[1]
    );
  }

  function setUrl(id, replace) {
    const url = new URL(window.location.href);
    url.searchParams.set("doc", id);
    url.hash = "";
    const next = url.pathname + url.search;
    if (replace) history.replaceState({ doc: id }, "", next);
    else history.pushState({ doc: id }, "", next);
  }

  function renderNav(activeId) {
    navEl.innerHTML = "";
    for (const doc of CATALOG) {
      const a = document.createElement("a");
      a.href = `?doc=${encodeURIComponent(doc.id)}`;
      a.textContent = doc.title;
      a.dataset.doc = doc.id;
      if (doc.id === activeId) a.setAttribute("aria-current", "page");
      a.addEventListener("click", (e) => {
        e.preventDefault();
        loadDoc(doc.id, false);
      });
      navEl.appendChild(a);
    }
  }

  async function fetchMarkdown(file) {
    const urls = [`${LOCAL_BASE}${file}`, `${CDN_BASE}${file}`, `${RAW_BASE}${file}`];
    let lastErr = null;
    for (const url of urls) {
      try {
        const res = await fetch(url, { cache: "no-cache" });
        if (!res.ok) throw new Error(`${res.status} ${res.statusText}`);
        return await res.text();
      } catch (err) {
        lastErr = err;
      }
    }
    throw lastErr || new Error("fetch failed");
  }

  function rewriteDocLinks(root) {
    root.querySelectorAll("a[href]").forEach((a) => {
      const href = a.getAttribute("href") || "";
      if (/^https?:\/\//i.test(href) || href.startsWith("#") || href.startsWith("mailto:")) {
        return;
      }
      const match = href.match(/^(?:\.\/)?([\w.-]+)\.md(?:#(.*))?$/i);
      if (match) {
        const id = normalizeId(match[1]);
        const frag = match[2] ? `#${match[2]}` : "";
        a.setAttribute("href", `?doc=${encodeURIComponent(id)}${frag}`);
        a.addEventListener("click", (e) => {
          e.preventDefault();
          loadDoc(id, false).then(() => {
            if (match[2]) {
              const el = document.getElementById(match[2]) || document.getElementById(slugify(match[2]));
              el?.scrollIntoView({ behavior: "smooth", block: "start" });
            }
          });
        });
      }
    });
  }

  function slugify(text) {
    return String(text)
      .toLowerCase()
      .replace(/[^\w\s-]/g, "")
      .trim()
      .replace(/\s+/g, "-");
  }

  function addHeadingIds(root) {
    root.querySelectorAll("h1, h2, h3, h4, h5, h6").forEach((h) => {
      if (!h.id) h.id = slugify(h.textContent || "");
    });
  }

  async function loadDoc(id, replaceHistory) {
    const entry = entryFor(id);
    renderNav(entry.id);
    pathEl.textContent = `docs/${entry.file}`;
    githubEl.href = `${GITHUB_BLOB}${entry.file}`;
    document.title = `${entry.title} — Prism Router Docs`;
    setUrl(entry.id, replaceHistory);
    articleEl.innerHTML = `<p class="docs-loading">Loading <code>${entry.file}</code>…</p>`;
    refreshBtn.hidden = true;

    try {
      const md = await fetchMarkdown(entry.file);
      if (typeof marked === "undefined" || typeof DOMPurify === "undefined") {
        throw new Error("Markdown renderer not loaded");
      }
      marked.setOptions({ gfm: true, breaks: false });
      const dirty = marked.parse(md);
      const clean = DOMPurify.sanitize(dirty, { USE_PROFILES: { html: true } });
      articleEl.innerHTML = clean;
      addHeadingIds(articleEl);
      rewriteDocLinks(articleEl);
      articleEl.querySelectorAll("pre").forEach((pre) => pre.classList.add("docs-code"));
      window.scrollTo({ top: 0 });
    } catch (err) {
      articleEl.innerHTML = `
        <div class="docs-error">
          <h1>Couldn’t load <code>${entry.file}</code></h1>
          <p>${String(err && err.message ? err.message : err)}</p>
          <p>
            <a href="${GITHUB_BLOB}${entry.file}" target="_blank" rel="noopener">Open on GitHub →</a>
          </p>
        </div>`;
      refreshBtn.hidden = false;
    }
  }

  function boot() {
    refreshBtn.addEventListener("click", () => loadDoc(docIdFromLocation(), true));
    window.addEventListener("popstate", () => loadDoc(docIdFromLocation(), true));

    const start = () => loadDoc(docIdFromLocation(), true);
    if (typeof marked !== "undefined" && typeof DOMPurify !== "undefined") {
      start();
      return;
    }
    let tries = 0;
    const t = setInterval(() => {
      tries += 1;
      if (typeof marked !== "undefined" && typeof DOMPurify !== "undefined") {
        clearInterval(t);
        start();
      } else if (tries > 50) {
        clearInterval(t);
        articleEl.innerHTML =
          '<p class="docs-error">Markdown libraries failed to load. Check your network, then retry.</p>';
        refreshBtn.hidden = false;
      }
    }, 100);
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", boot);
  } else {
    boot();
  }
})();
