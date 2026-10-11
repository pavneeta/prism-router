/**
 * Docs viewer — fetches markdown from GitHub docs/ (via jsDelivr) and renders it.
 * Stays in sync with main without redeploying the marketing site for every doc edit.
 */
(function () {
  "use strict";

  const REPO = "pavneeta/prism-router";
  const BRANCH = "main";
  /** Bundled copy used first; jsDelivr / raw GitHub are public fallbacks. */
  const LOCAL_BASE = "./docs-content/";
  const CDN_BASE = `https://cdn.jsdelivr.net/gh/${REPO}@${BRANCH}/docs/`;
  const RAW_BASE = `https://raw.githubusercontent.com/${REPO}/${BRANCH}/docs/`;
  const GITHUB_BLOB = `https://github.com/${REPO}/blob/${BRANCH}/docs/`;

  /** Curated nav — user/operator docs only (mirrors docs/README.md; excludes docs/internal/). */
  const CATALOG = [
    { id: "README", title: "Index", file: "README.md" },
    { id: "USAGE", title: "Usage", file: "USAGE.md" },
    { id: "BENCHMARKS", title: "Benchmarks", file: "BENCHMARKS.md" },
    { id: "OPENCODE", title: "OpenCode", file: "OPENCODE.md" },
    { id: "CURSOR", title: "Cursor", file: "CURSOR.md" },
    { id: "HERMES", title: "Hermes", file: "HERMES.md" },
    { id: "HOLMESGPT", title: "HolmesGPT", file: "HOLMESGPT.md" },
    { id: "TOGETHER", title: "Together.ai", file: "TOGETHER.md" },
    { id: "TROUBLESHOOTING", title: "Troubleshooting", file: "TROUBLESHOOTING.md" },
    { id: "SECURITY", title: "Security", file: "SECURITY.md" },
    { id: "RAILWAY", title: "Railway deploy", file: "RAILWAY.md" },
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
      // Internal eng docs stay on GitHub; rewrite relative paths to blob URLs.
      const internalMatch = href.match(/^(?:\.\/)?internal\/(.+?)(?:#(.*))?$/i);
      if (internalMatch) {
        const frag = internalMatch[2] ? `#${internalMatch[2]}` : "";
        a.setAttribute(
          "href",
          `${GITHUB_BLOB}internal/${internalMatch[1]}${frag}`
        );
        a.setAttribute("target", "_blank");
        a.setAttribute("rel", "noopener");
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

  /** Public docs UI: drop eng-facing sections from rendered HTML (files stay in docs/). */
  const HIDDEN_SECTIONS = {
    BENCHMARKS: ["normalization", "task-accuracy-derivation"],
  };

  function removeHiddenSections(root, docId) {
    const ids = HIDDEN_SECTIONS[docId];
    if (!ids || !ids.length) return;
    for (const id of ids) {
      const heading = root.querySelector(`#${CSS.escape(id)}`);
      if (!heading) continue;
      const level = parseInt(heading.tagName.slice(1), 10);
      const toRemove = [heading];
      let el = heading.nextElementSibling;
      while (el) {
        const next = el.nextElementSibling;
        if (/^H[1-6]$/.test(el.tagName) && parseInt(el.tagName.slice(1), 10) <= level) {
          break;
        }
        toRemove.push(el);
        el = next;
      }
      toRemove.forEach((node) => node.remove());
    }
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
      removeHiddenSections(articleEl, entry.id);
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
