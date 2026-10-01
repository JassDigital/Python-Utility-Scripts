const fs = require("fs");
const path = require("path");

const ROOT = __dirname;
const OUTPUT = path.join(ROOT, "index.html");

const TITLE = "JASS Python Utility Scripts";
const SUBTITLE =
  "A practical collection of Python tools for files, media, data, automation, system utilities, and developer workflows.";

const GITHUB =
  "https://github.com/Fanu2/Python-Utility-Scripts";

const SITE =
  "https://python-utility-scripts.vercel.app";

const EXCLUDE = new Set([
  ".git",
  "node_modules",
  "index.html",
  "generate-index.js",
  ".DS_Store",
  "Thumbs.db"
]);

function esc(value) {
  return String(value)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

function humanSize(bytes) {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024)
    return `${(bytes / 1024).toFixed(1)} KB`;
  if (bytes < 1024 * 1024 * 1024)
    return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
  return `${(bytes / (1024 * 1024 * 1024)).toFixed(1)} GB`;
}

function iconFor(file) {
  const name = file.toLowerCase();

  if (name.endsWith(".py")) return "🐍";
  if (name.endsWith(".html")) return "🌐";
  if (name.endsWith(".css")) return "🎨";
  if (name.endsWith(".md")) return "📝";
  if (name.endsWith(".json")) return "🔧";
  if (name.endsWith(".csv")) return "📊";
  if (name.endsWith(".xml")) return "🧩";
  if (name.endsWith(".txt")) return "📄";
  if (/\.(png|jpg|jpeg|webp|gif)$/i.test(name)) return "🖼️";

  return "📦";
}

function category(name) {
  const n = name.toLowerCase();

  if (
    /file|folder|directory|rename|extract|compress|unzip|snapshot|consolidator|watcher/.test(
      n
    )
  )
    return "Files & Folders";

  if (
    /image|photo|collage|thumbnail|watermark|grayscale|blur|contrast|sepia|crop|resize|rotate/.test(
      n
    )
  )
    return "Image Tools";

  if (
    /video|audio|subtitle|slideshow|transition|media|movie|gif|frames|overlay/.test(
      n
    )
  )
    return "Media Tools";

  if (
    /pdf|epub|book|document|text|html_report|cataloger/.test(n)
  )
    return "Documents & Text";

  if (
    /csv|json|xml|excel|data|regex|visualization|formatter|merger/.test(
      n
    )
  )
    return "Data & Formats";

  if (
    /sqlite|database|backup|sql/.test(n)
  )
    return "Database";

  if (
    /system|cpu|memory|disk|network|windows|startup|power|usage|inspector/.test(
      n
    )
  )
    return "System Utilities";

  if (
    /api|web|url|scraper|browser|ftp|ssh|email|smtp|rss|weather|stock|youtube|downloader/.test(
      n
    )
  )
    return "Web & Automation";

  if (
    /landsoft|land|punjabi|mizo|literature|romance|dictionary|translit|corpus|facebook|portable/.test(
      n
    )
  )
    return "JASS Applications";

  return "Python Utilities";
}

function description(name) {
  const clean = name
    .replace(/\.py$/i, "")
    .replace(/[_-]+/g, " ")
    .replace(/\bJASS\b/gi, "JASS");

  return clean.charAt(0).toUpperCase() + clean.slice(1);
}

function scan(dir, relative = "") {
  const results = [];

  for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
    if (EXCLUDE.has(entry.name)) continue;

    const full = path.join(dir, entry.name);
    const rel = path.join(relative, entry.name);

    if (entry.isDirectory()) {
      results.push(...scan(full, rel));
      continue;
    }

    if (!entry.isFile()) continue;

    const stat = fs.statSync(full);

    results.push({
      name: entry.name,
      path: rel.replace(/\\/g, "/"),
      size: stat.size,
      category: category(entry.name),
      icon: iconFor(entry.name),
      description: description(entry.name)
    });
  }

  return results;
}

const files = scan(ROOT);

files.sort((a, b) =>
  a.name.localeCompare(b.name, undefined, { sensitivity: "base" })
);

const pythonFiles = files.filter(f => f.name.toLowerCase().endsWith(".py"));
const categories = [...new Set(files.map(f => f.category))].sort();

const totalSize = files.reduce((sum, f) => sum + f.size, 0);

const cards = files
  .map(
    f => `
      <article class="card" data-search="${esc(
        `${f.name} ${f.category} ${f.description}`
      ).toLowerCase()}">
        <div class="icon">${f.icon}</div>

        <div class="card-body">
          <div class="category">${esc(f.category)}</div>

          <h3>${esc(f.name)}</h3>

          <p>${esc(f.description)}</p>

          <div class="meta">
            <span>${humanSize(f.size)}</span>
            <span>${esc(path.extname(f.name) || "file")}</span>
          </div>

          <div class="actions">
            <a href="${esc(f.path)}" target="_blank">Open</a>
            <a
              href="${GITHUB}/blob/main/${encodeURI(f.path)}"
              target="_blank"
            >GitHub</a>
          </div>
        </div>
      </article>
    `
  )
  .join("");

const categoryChips = categories
  .map(
    c =>
      `<button class="chip" data-category="${esc(
        c
      )}">${esc(c)}</button>`
  )
  .join("");

const html = `<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">

<title>${TITLE}</title>

<meta
  name="description"
  content="${esc(SUBTITLE)}"
/>

<style>
:root {
  --bg: #07111f;
  --panel: #0d1b2e;
  --panel2: #10243b;
  --border: rgba(255,255,255,.10);
  --text: #eef5ff;
  --muted: #9fb1c7;
  --accent: #66d9ef;
  --accent2: #9b8cff;
  --shadow: 0 20px 50px rgba(0,0,0,.30);
}

* {
  box-sizing: border-box;
}

body {
  margin: 0;
  font-family:
    Inter, ui-sans-serif, system-ui, -apple-system,
    BlinkMacSystemFont, "Segoe UI", sans-serif;
  background:
    radial-gradient(circle at top left, #142b48 0, transparent 35%),
    radial-gradient(circle at top right, #20204d 0, transparent 30%),
    var(--bg);
  color: var(--text);
}

a {
  color: inherit;
  text-decoration: none;
}

.hero {
  min-height: 460px;
  padding: 55px 24px;
  display: flex;
  align-items: center;
  justify-content: center;
  position: relative;
  overflow: hidden;
  border-bottom: 1px solid var(--border);
}

.hero::before {
  content: "";
  position: absolute;
  inset: 0;
  background:
    linear-gradient(
      90deg,
      rgba(7,17,31,.95),
      rgba(7,17,31,.72),
      rgba(7,17,31,.92)
    ),
    url("hero.png") center/cover no-repeat;
  opacity: .65;
}

.hero-content {
  position: relative;
  max-width: 1050px;
  width: 100%;
  z-index: 2;
}

.eyebrow {
  display: inline-block;
  padding: 8px 13px;
  border: 1px solid rgba(102,217,239,.35);
  border-radius: 999px;
  color: var(--accent);
  font-size: 13px;
  letter-spacing: .12em;
  text-transform: uppercase;
  margin-bottom: 20px;
}

h1 {
  font-size: clamp(42px, 7vw, 78px);
  line-height: .98;
  margin: 0 0 22px;
  max-width: 850px;
  letter-spacing: -.04em;
}

.hero p {
  max-width: 760px;
  color: #c5d2e2;
  font-size: 19px;
  line-height: 1.7;
}

.hero-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 12px;
  margin-top: 28px;
}

.button {
  padding: 12px 18px;
  border-radius: 10px;
  border: 1px solid var(--border);
  background: rgba(255,255,255,.07);
  font-weight: 700;
}

.button.primary {
  background: var(--accent);
  color: #06111d;
}

.container {
  max-width: 1250px;
  margin: auto;
  padding: 35px 22px 70px;
}

.stats {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 14px;
  margin-bottom: 32px;
}

.stat {
  background: rgba(13,27,46,.82);
  border: 1px solid var(--border);
  border-radius: 16px;
  padding: 20px;
  box-shadow: var(--shadow);
}

.stat strong {
  display: block;
  font-size: 28px;
}

.stat span {
  color: var(--muted);
  font-size: 13px;
}

.controls {
  position: sticky;
  top: 0;
  z-index: 10;
  padding: 15px 0;
  background: rgba(7,17,31,.88);
  backdrop-filter: blur(14px);
}

.search {
  width: 100%;
  padding: 15px 17px;
  border-radius: 12px;
  border: 1px solid var(--border);
  background: var(--panel);
  color: white;
  outline: none;
  font-size: 16px;
}

.chips {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
  margin: 13px 0 25px;
}

.chip {
  cursor: pointer;
  padding: 8px 12px;
  border-radius: 999px;
  border: 1px solid var(--border);
  background: var(--panel);
  color: var(--muted);
}

.chip.active,
.chip:hover {
  color: var(--text);
  border-color: rgba(102,217,239,.5);
}

.grid {
  display: grid;
  grid-template-columns:
    repeat(auto-fill, minmax(280px, 1fr));
  gap: 16px;
}

.card {
  display: flex;
  gap: 15px;
  padding: 19px;
  background:
    linear-gradient(
      145deg,
      rgba(16,36,59,.96),
      rgba(13,27,46,.96)
    );
  border: 1px solid var(--border);
  border-radius: 16px;
  min-height: 205px;
  transition: transform .18s ease, border-color .18s ease;
}

.card:hover {
  transform: translateY(-3px);
  border-color: rgba(102,217,239,.35);
}

.icon {
  font-size: 29px;
  flex: 0 0 auto;
}

.card-body {
  min-width: 0;
  flex: 1;
}

.category {
  color: var(--accent);
  font-size: 11px;
  font-weight: 800;
  letter-spacing: .08em;
  text-transform: uppercase;
}

h3 {
  margin: 7px 0;
  font-size: 17px;
  overflow-wrap: anywhere;
}

.card p {
  color: var(--muted);
  line-height: 1.5;
  font-size: 13px;
}

.meta {
  display: flex;
  gap: 10px;
  color: #778ca4;
  font-size: 11px;
  margin: 12px 0;
}

.actions {
  display: flex;
  gap: 8px;
}

.actions a {
  font-size: 12px;
  padding: 7px 10px;
  border-radius: 7px;
  background: rgba(255,255,255,.07);
}

.actions a:hover {
  background: rgba(102,217,239,.15);
}

.empty {
  display: none;
  padding: 50px;
  text-align: center;
  color: var(--muted);
}

footer {
  border-top: 1px solid var(--border);
  padding: 30px 22px;
  text-align: center;
  color: var(--muted);
  font-size: 13px;
}

@media (max-width: 750px) {
  .stats {
    grid-template-columns: repeat(2, 1fr);
  }

  .hero {
    min-height: 500px;
  }
}

@media (max-width: 450px) {
  .stats {
    grid-template-columns: 1fr 1fr;
  }

  .grid {
    grid-template-columns: 1fr;
  }
}
</style>
</head>

<body>

<section class="hero">
  <div class="hero-content">

    <div class="eyebrow">JASS Digital Lab · Python Collection</div>

    <h1>${TITLE}</h1>

    <p>${esc(SUBTITLE)}</p>

    <div class="hero-actions">
      <a class="button primary" href="#utilities">
        Explore Utilities
      </a>

      <a
        class="button"
        href="${GITHUB}"
        target="_blank"
      >
        View GitHub Repository
      </a>
    </div>

  </div>
</section>

<main class="container" id="utilities">

  <section class="stats">
    <div class="stat">
      <strong>${files.length}</strong>
      <span>Total files</span>
    </div>

    <div class="stat">
      <strong>${pythonFiles.length}</strong>
      <span>Python scripts</span>
    </div>

    <div class="stat">
      <strong>${categories.length}</strong>
      <span>Categories</span>
    </div>

    <div class="stat">
      <strong>${humanSize(totalSize)}</strong>
      <span>Collection size</span>
    </div>
  </section>

  <section class="controls">

    <input
      id="search"
      class="search"
      type="search"
      placeholder="Search scripts, tools, categories..."
      autocomplete="off"
    >

    <div class="chips">
      <button class="chip active" data-category="All">
        All
      </button>
      ${categoryChips}
    </div>

  </section>

  <section class="grid" id="grid">
    ${cards}
  </section>

  <div class="empty" id="empty">
    No utilities match your search.
  </div>

</main>

<footer>
  <strong>JASS Python Utility Scripts</strong><br>
  Built and maintained as part of the JASS Digital Lab.
</footer>

<script>
const search = document.getElementById("search");
const cards = [...document.querySelectorAll(".card")];
const chips = [...document.querySelectorAll(".chip")];
const empty = document.getElementById("empty");

let activeCategory = "All";

function filter() {
  const query = search.value.trim().toLowerCase();
  let visible = 0;

  cards.forEach(card => {
    const matchesSearch =
      !query ||
      card.dataset.search.includes(query);

    const cardCategory =
      card.querySelector(".category")?.textContent || "";

    const matchesCategory =
      activeCategory === "All" ||
      cardCategory === activeCategory;

    const show =
      matchesSearch && matchesCategory;

    card.style.display = show ? "" : "flex";

    if (show) visible++;
  });

  empty.style.display =
    visible === 0 ? "block" : "none";
}

search.addEventListener("input", filter);

chips.forEach(chip => {
  chip.addEventListener("click", () => {

    chips.forEach(c =>
      c.classList.remove("active")
    );

    chip.classList.add("active");

    activeCategory =
      chip.dataset.category;

    filter();
  });
});
</script>

</body>
</html>`;

fs.writeFileSync(OUTPUT, html, "utf8");

console.log(
  `Generated ${OUTPUT} with ${files.length} files, ${pythonFiles.length} Python scripts and ${categories.length} categories.`
);