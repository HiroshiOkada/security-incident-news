(() => {
  "use strict";

  const DATA_URL = "data/news.json";
  const DAYS_JA = ["日", "月", "火", "水", "木", "金", "土"];
  const TAG_CLASS = {
    "ランサムウェア": "t-ransomware",
    "脆弱性": "t-vuln",
    "情報漏えい": "t-leak",
    "注意喚起": "t-advisory",
  };

  const state = { region: "all", period: "all", tag: null, q: "" };
  let allItems = [];

  const $ = (sel) => document.querySelector(sel);
  const listEl = $("#list");
  const emptyEl = $("#empty");
  const chipsEl = $("#tag-chips");
  const resultEl = $("#result-count");

  const esc = (s) =>
    String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

  const jstDate = (iso) => {
    const d = new Date(iso);
    return Number.isNaN(d.getTime()) ? null : d;
  };
  const dayKey = (d) =>
    `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
  const timeFmt = new Intl.DateTimeFormat("ja-JP", { hour: "2-digit", minute: "2-digit", hour12: false, timeZone: "Asia/Tokyo" });
  const dateFmt = new Intl.DateTimeFormat("ja-JP", { year: "numeric", month: "2-digit", day: "2-digit", timeZone: "Asia/Tokyo" });
  const stampFmt = new Intl.DateTimeFormat("ja-JP", {
    year: "numeric", month: "2-digit", day: "2-digit",
    hour: "2-digit", minute: "2-digit", hour12: false, timeZone: "Asia/Tokyo",
  });

  function readUrl() {
    const p = new URLSearchParams(location.search);
    if (["all", "jp", "world"].includes(p.get("region"))) state.region = p.get("region");
    if (["all", "1", "7", "30"].includes(p.get("period"))) state.period = p.get("period");
    if (p.get("tag")) state.tag = p.get("tag");
    if (p.get("q")) state.q = p.get("q");
  }

  function writeUrl() {
    const p = new URLSearchParams();
    if (state.region !== "all") p.set("region", state.region);
    if (state.period !== "all") p.set("period", state.period);
    if (state.tag) p.set("tag", state.tag);
    if (state.q) p.set("q", state.q);
    const qs = p.toString();
    history.replaceState(null, "", qs ? `?${qs}` : location.pathname);
  }

  function syncControls() {
    document.querySelectorAll(".seg").forEach((b) => {
      const active = b.dataset.region === state.region;
      b.classList.toggle("is-active", active);
      b.setAttribute("aria-selected", String(active));
    });
    $("#period").value = state.period;
    if ($("#search").value !== state.q) $("#search").value = state.q;
  }

  function matches(item) {
    if (state.region !== "all" && item.region !== state.region) return false;
    if (state.tag && !(item.tags || []).includes(state.tag)) return false;
    if (state.period !== "all") {
      const d = jstDate(item.published);
      const limit = Date.now() - Number(state.period) * 86400000;
      if (!d || d.getTime() < limit) return false;
    }
    if (state.q) {
      const needle = state.q.toLowerCase();
      const hay = `${item.title} ${item.summary} ${item.source} ${(item.tags || []).join(" ")}`.toLowerCase();
      if (!hay.includes(needle)) return false;
    }
    return true;
  }

  function buildChips() {
    const counts = new Map();
    for (const item of allItems) {
      for (const t of item.tags || []) counts.set(t, (counts.get(t) || 0) + 1);
    }
    const sorted = [...counts.entries()].sort((a, b) => b[1] - a[1]);
    chipsEl.innerHTML = sorted
      .map(
        ([tag, n]) =>
          `<button class="chip${state.tag === tag ? " is-active" : ""}" data-tag="${esc(tag)}">${esc(tag)}<span class="n">${n}</span></button>`
      )
      .join("");
  }

  function render() {
    const items = allItems.filter(matches);
    resultEl.textContent = `${items.length.toLocaleString("ja-JP")} 件を表示`;

    if (!items.length) {
      listEl.innerHTML = "";
      emptyEl.hidden = false;
      return;
    }
    emptyEl.hidden = true;

    const groups = new Map();
    for (const item of items) {
      const d = jstDate(item.published);
      if (!d) continue;
      const key = dayKey(d);
      if (!groups.has(key)) groups.set(key, { date: d, items: [] });
      groups.get(key).items.push(item);
    }

    const html = [...groups.values()]
      .map((g) => {
        const rows = g.items
          .map((item) => {
            const d = jstDate(item.published);
            const tags = (item.tags || [])
              .map((t) => `<span class="tag ${TAG_CLASS[t] || ""}">${esc(t)}</span>`)
              .join("");
            const region = item.region === "jp" ? "国内" : "海外";
            return `<article class="item">
  <div class="item-time">
    <span>${d ? timeFmt.format(d) : "--:--"}</span>
    <span class="region region-${item.region}">${region}</span>
  </div>
  <div class="item-body">
    <div class="item-source">${esc(item.source)}</div>
    <h3 class="item-title"><a href="${esc(item.url)}" target="_blank" rel="noopener noreferrer">${esc(item.title)}</a></h3>
    ${item.summary ? `<p class="item-summary">${esc(item.summary)}</p>` : ""}
    ${tags ? `<div class="item-tags">${tags}</div>` : ""}
  </div>
</article>`;
          })
          .join("");
        const wd = DAYS_JA[g.date.getDay()];
        return `<section class="day">
  <header class="day-head">
    <span class="day-date">${dateFmt.format(g.date)}</span>
    <span class="day-week">（${wd}）</span>
    <span class="day-count">${g.items.length} 件</span>
  </header>
  ${rows}
</section>`;
      })
      .join("");

    listEl.innerHTML = html;
    updateReset();
  }

  function updateReset() {
    $("#reset").hidden = state.region === "all" && state.period === "all" && !state.tag && !state.q;
  }

  function renderMeta(data) {
    const now = Date.now();
    const jp = allItems.filter((i) => i.region === "jp").length;
    $("#stat-total").textContent = allItems.length.toLocaleString("ja-JP");
    $("#stat-jp").textContent = jp.toLocaleString("ja-JP");
    $("#stat-world").textContent = (allItems.length - jp).toLocaleString("ja-JP");
    $("#stat-24h").textContent = allItems
      .filter((i) => {
        const d = jstDate(i.published);
        return d && now - d.getTime() <= 86400000;
      })
      .length.toLocaleString("ja-JP");

    const gen = data.generated_at ? new Date(data.generated_at) : null;
    $("#updated").textContent = gen && !Number.isNaN(gen.getTime())
      ? `最終更新 ${stampFmt.format(gen)} JST`
      : "更新時刻不明";
    $("#live-dot").style.background = "";

    const sources = data.sources || [];
    $("#stat-sources").textContent = `${data.sources_ok ?? sources.filter((s) => s.status === "ok").length} / ${sources.length || "—"} ソース正常`;
    $("#source-list").innerHTML = sources
      .map(
        (s) =>
          `<li>${esc(s.name)}<span class="badge ${s.status === "ok" ? "ok" : "ng"}">${s.status === "ok" ? "OK" : "NG"}</span></li>`
      )
      .join("");
  }

  function bind() {
    document.querySelectorAll(".seg").forEach((btn) => {
      btn.addEventListener("click", () => {
        state.region = btn.dataset.region;
        syncControls();
        writeUrl();
        render();
      });
    });

    $("#period").addEventListener("change", (e) => {
      state.period = e.target.value;
      writeUrl();
      render();
    });

    let timer;
    $("#search").addEventListener("input", (e) => {
      clearTimeout(timer);
      timer = setTimeout(() => {
        state.q = e.target.value.trim();
        writeUrl();
        render();
      }, 180);
    });

    chipsEl.addEventListener("click", (e) => {
      const chip = e.target.closest(".chip");
      if (!chip) return;
      const tag = chip.dataset.tag;
      state.tag = state.tag === tag ? null : tag;
      buildChips();
      writeUrl();
      render();
    });

    $("#reset").addEventListener("click", () => {
      state.region = "all";
      state.period = "all";
      state.tag = null;
      state.q = "";
      syncControls();
      buildChips();
      writeUrl();
      render();
    });
  }

  async function boot() {
    readUrl();
    syncControls();
    bind();
    try {
      const res = await fetch(`${DATA_URL}?v=${Date.now()}`, { cache: "no-store" });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = await res.json();
      allItems = (data.items || []).filter((i) => jstDate(i.published));
      renderMeta(data);
      buildChips();
      render();
    } catch (err) {
      listEl.innerHTML = `<p class="error">データを読み込めませんでした（${esc(err.message)}）。<br>しばらくしてから再読み込みしてください。</p>`;
      $("#updated").textContent = "データ取得エラー";
      $("#live-dot").style.background = "#ff6b6b";
    }
  }

  boot();
})();
