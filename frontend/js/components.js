/* ------------------------------------------------------------------
   Component renderers – pure HTML-string builders.
   All blocks render as value-less skeletons (no data yet).
------------------------------------------------------------------- */

const ICONS = {
  bars:   '<path d="M4 20V10M10 20V4M16 20v-7M22 20H2"/>',
  coin:   '<circle cx="12" cy="12" r="9"/><path d="M12 7v10M9.5 9.5c0-1 1-1.7 2.5-1.7s2.5.7 2.5 1.7-1 1.5-2.5 1.8S9.5 12.3 9.5 14.3c0 1 1 1.700 2.500 1.700s2.500-.7 2.500-1.700"/>',
  rupee:  '<path d="M7 5h10M7 9h10M7 5c5 0 7 2 7 4s-2 4-7 4l7 6"/>',
  cube:   '<path d="M12 3l8 4.500v9L12 21l-8-4.500v-9L12 3z"/><path d="M12 12l8-4.500M12 12v9M12 12L4 7.500"/>',
  doc:    '<path d="M6 3h9l4 4v14H6z"/><path d="M15 3v4h4M9 12h7M9 16h7"/>',
  percent:'<path d="M19 5L5 19"/><circle cx="7" cy="7" r="2.500"/><circle cx="17" cy="17" r="2.500"/>',
  lock:   '<rect x="5" y="11" width="14" height="10" rx="2"/><path d="M8 11V8a4 4 0 018 0v3"/>',
  db:     '<ellipse cx="12" cy="6" rx="8" ry="3"/><path d="M4 6v12c0 1.700 3.600 3 8 3s8-1.300 8-3V6M4 12c0 1.700 3.600 3 8 3s8-1.300 8-3"/>',
  pin:    '<path d="M12 21s7-6.200 7-12a7 7 0 10-14 0c0 5.800 7 12 7 12z"/><circle cx="12" cy="9" r="2.500"/>',
  shop:   '<path d="M4 9l1.500-5h13L20 9M4 9v11h16V9M4 9c0 1.700 1.800 2.500 4 2.500S12 10.700 12 9c0 1.700 1.800 2.500 4 2.500S20 10.700 20 9"/>',
  plus:   '<path d="M12 5v14M5 12h14"/>',
  trend:  '<path d="M3 17l6-6 4 4 8-9"/><path d="M15 6h6v6"/>',
  bulb:   '<path d="M9 18h6M10 21h4M12 3a6 6 0 00-3.500 10.900c.6.500 1 1.200 1 2.100h5c0-.9.400-1.600 1-2.100A6 6 0 0012 3z"/>',
  users:  '<circle cx="9" cy="8" r="3.500"/><path d="M2 20c0-3.500 3-6 7-6s7 2.500 7 6"/><path d="M16 4.500a3.500 3.500 0 010 7M18 14c2.500.7 4 2.700 4 6"/>',
  gear:   '<circle cx="12" cy="12" r="3"/><path d="M12 2v3M12 19v3M2 12h3M19 12h3M5 5l2 2M17 17l2 2M19 5l-2 2M7 17l-2 2"/>',
  alert:  '<path d="M12 3l10 18H2L12 3z"/><path d="M12 10v5M12 18v.01"/>',
  map:    '<path d="M3 6l6-2 6 2 6-2v14l-6 2-6-2-6 2V6zM9 4v14M15 6v14"/>',
  table:  '<rect x="3" y="4" width="18" height="16" rx="2"/><path d="M3 10h18M9 4v16"/>',
  clip:   '<rect x="6" y="4" width="12" height="17" rx="2"/><path d="M9 4h6v3H9zM9 12h6M9 16h6"/>',
  window: '<rect x="3" y="4" width="18" height="16" rx="2"/><path d="M3 9h18"/>',
  tag:    '<path d="M3 12V4h8l10 10-8 8L3 12z"/><circle cx="7.500" cy="8.500" r="1.200"/>',
  pie:    '<path d="M12 3v9h9a9 9 0 11-9-9z"/>',
  return: '<path d="M9 14L4 9l5-5"/><path d="M4 9h10a6 6 0 010 12h-3"/>',
  chart:  '<path d="M4 20V10M10 20V4M16 20v-7M22 20H2"/>'
  ,filter: '<path d="M4 5h16M7 12h10M10 19h4"/>'
};

const icon = (name, cls = "") =>
  `<svg class="ico ${cls}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.800" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${ICONS[name] || ICONS.bars}</svg>`;

/* deterministic pseudo-random for stable skeleton shapes */
const ghost = (i, min = 30, max = 95) => Math.round(min + ((i * 37 + 17) % 100) / 100 * (max - min));

const sk = (w = "100%", h = "10px", cls = "") => `<span class="sk ${cls}" style="width:${w};height:${h}"></span>`;

/* ---------------------------- blocks ---------------------------- */
const BLOCKS = {

  topCustomers() { return `<div class="hbar spo-data-scroll" data-spo-top-customers>${Array.from({length: 5}, () => `<div class="hbar-row">${sk("80%","9px")}<div class="hbar-track"><span class="hbar-fill" style="width:0%"></span></div>${sk("34px","9px")}</div>`).join("")}</div>`; },

  skuPerformance() { return `<div class="hbar spo-data-scroll" data-spo-skus>${Array.from({length: 6}, () => `<div class="hbar-row">${sk("80%","9px")}<div class="hbar-track"><span class="hbar-fill target" style="width:0%"></span><span class="hbar-fill" style="width:0%"></span></div>${sk("34px","9px")}</div>`).join("")}</div>`; },

  productPerformance() { return `<div class="hbar spo-data-scroll product-performance-list" data-product-performance>${Array.from({length: 8}, () => `<div class="hbar-row">${sk("80%","9px")}<div class="hbar-track"><span class="hbar-fill" style="width:0%"></span></div>${sk("34px","9px")}</div>`).join("")}</div>`; },

  hbar(b) {
    const rows = Array.from({ length: b.rows }, (_, i) => `
      <div class="hbar-row">
        <div class="hbar-label ${b.labelWide ? "wide" : ""}">${sk("80%", "9px")}${b.sublabel ? sk("50%", "7px", "light") : ""}</div>
        <div class="hbar-track">
          ${b.dual ? `<span class="hbar-fill target" style="width:${ghost(i, 35, 80)}%"></span>` : ""}
          <span class="hbar-fill" style="width:${ghost(i + 3, 25, 95)}%"></span>
        </div>
        <div class="hbar-val">${sk("34px", "9px")}</div>
      </div>`).join("");
    return `<div class="hbar">${rows}</div>`;
  },

  columns(b) {
    const groups = b.groups.map((g, i) => `
      <div class="col-group">
        <div class="col-bars">
          <span class="col-bar target" style="height:${ghost(i, 35, 70)}%"></span>
          <span class="col-bar" style="height:${ghost(i + 2, 45, 92)}%"></span>
        </div>
        <div class="col-label">${g}</div>
        ${b.pills ? `<span class="pill-ghost"></span>` : ""}
      </div>`).join("");
    return `<div class="columns ${b.compact ? "compact" : ""}"><div class="col-axis"><i></i><i></i><i></i><i></i></div>${groups}</div>`;
  },

  legend(b) {
    const cls = ["target", "actual", "line"];
    return `${b.title ? `<div class="legend-title">${b.title}</div>` : ""}
      <div class="legend">${b.items.map((t, i) => `<span><i class="dot ${cls[i % 3]}"></i>${t}</span>`).join("")}</div>`;
  },

  donut(b) {
    return `${b.title ? `<div class="legend-title">${b.title}</div>` : ""}
      <div class="donut-wrap ${b.large ? "large" : ""}">
        <div class="donut"><div class="donut-center"><strong>--</strong><small>${b.center || ""}</small></div></div>
        <ul class="donut-legend">
          ${b.legend.map((t, i) => `<li><i class="swatch s${i}"></i><span>${t}</span>${sk("28px", "8px")}</li>`).join("")}
        </ul>
      </div>`;
  },

  budget() {
    return `<div class="budget">
      <div class="budget-title">Discount vs Budget</div>
      <div class="budget-labels"><span>Actual <b>--</b></span><span>Budget <b>--</b></span></div>
      <div class="budget-track"><span class="budget-fill"></span><span class="budget-mark"></span></div>
      <div class="budget-var">${sk("90px", "8px")}</div>
    </div>`;
  },

  discount() {
    return `<div class="spo-discount" data-spo-discount>
      <section class="discount-product-section" aria-label="Product discount ranking">
        <b>PRODUCT DISCOUNT RANKING</b>
        <div class="hbar spo-data-scroll discount-product-list" data-discount-products></div>
      </section>
      <div class="discount-comparison">
        <div class="discount-comparison-labels">
          <b>Actual Discount <span data-discount-actual>--</span></b>
          <span>Budget <b data-discount-target>--</b></span>
        </div>
        <div class="discount-comparison-track" aria-label="Actual discount compared with budget">
          <i class="discount-comparison-fill" data-discount-fill></i>
          <i class="discount-comparison-mark" data-discount-mark></i>
        </div>
        <strong class="discount-comparison-variance" data-discount-variance>Budget comparison unavailable</strong>
      </div>
    </div>`;
  },

  empty(b) { return `<div class="empty-state">${icon("phone")}<p>${b.text}</p></div>`; },
  callPerformance() { return `<div class="call-performance" data-call-performance><div class="empty-state"><p>Loading call data...</p></div></div>`; },
  spoInsights() { return `<div class="numbered tinted" data-spo-insights></div>`; },
  actionPlan() { return `<div class="form-block" data-spo-actions></div>`; },

  statCards(b) {
    return `<div class="stat-cards cols-${b.cols}">${b.items.map(it => `
      <div class="stat-card tone-${it.tone || "blue"} ${it.wide ? "wide" : ""}">
        <div class="stat-ico">${icon(it.icon || "bars")}</div>
        <div class="stat-body">
          <span class="stat-label">${it.label}</span>
          <strong class="stat-val">--</strong>
          ${it.sub ? `<small>${it.sub}</small>` : `<small>${sk("60%", "7px", "light")}</small>`}
        </div>
      </div>`).join("")}</div>`;
  },

  table(b) {
    const head = b.cols.map(c => `<th>${c}</th>`).join("");
    const body = Array.from({ length: b.rows }, (_, r) =>
      `<tr>${b.cols.map((c, ci) => `<td>${
        b.bars && ci === b.cols.length - 1 ? `<span class="mini-bar"><i style="width:${ghost(r, 40, 95)}%"></i></span>` : sk(ci === 0 && c === "#" ? "10px" : "70%", "8px")
      }</td>`).join("")}</tr>`).join("");
    const total = b.total ? `<tr class="total">${b.cols.map((c, i) => `<td>${i === 0 ? "Total" : sk("60%", "8px")}</td>`).join("")}</tr>` : "";
    return `<div class="table-wrap"><table class="tbl ${b.dense ? "dense" : ""}"><thead><tr>${head}</tr></thead><tbody>${body}${total}</tbody></table></div>`;
  },

  tabs(b) {
    return `<div class="tabs ${b.pill ? "pill" : ""}" role="tablist">${b.items.map((t, i) =>
      `<button type="button" class="tab ${i === 0 ? "active" : ""}" role="tab">${t}</button>`).join("")}</div>`;
  },

  line(b) {
    const months = ["Jul", "Aug", "Sep", "Oct", "Nov", "Dec", "Jan", "Feb", "Mar", "Apr", "May", "Jun"];
    return `<div class="line-chart">
      <div class="line-area">
        ${b.bars ? `<div class="line-bars">${months.map((m, i) => `<i style="height:${ghost(i, 25, 70)}%"></i>`).join("")}</div>` : ""}
        <svg viewBox="0 0 300 100" preserveAspectRatio="none" class="line-svg">
          <polyline class="ln target" points="0,70 27,66 55,58 82,52 109,48 136,50 164,46 191,42 218,38 245,36 272,32 300,30"/>
          <polyline class="ln actual" points="0,64 27,60 55,48 82,52 109,36 136,40 164,34 191,38 218,30 245,26 272,28 300,20"/>
        </svg>
      </div>
      <div class="line-x">${months.map(m => `<span>${m}</span>`).join("")}</div>
    </div>`;
  },

  map() {
    return `<div class="map-box"><div class="map-shape">${icon("map")}<span>Geo Map</span></div>
      <div class="map-legend"><small>Net Sales (Rs.)</small>${[0, 1, 2, 3, 4].map(i => `<i class="mc c${i}"></i>`).join("")}</div></div>`;
  },

  insights(b) {
    return `<div class="insights"><h4>${b.title}</h4>${Array.from({ length: b.rows }, (_, i) => `
      <div class="ins-row"><span class="num n${i % 5}">${i + 1}</span><div class="ins-text">${sk("95%", "8px")}${sk("65%", "8px")}</div></div>`).join("")}</div>`;
  },

  actions(b) {
    const tones = ["green", "orange", "blue", "violet", "red"];
    return `<div class="actions"><h4>${b.title}</h4>${Array.from({ length: b.rows }, (_, i) => `
      <div class="act-row"><span class="act-ico tone-${tones[i % 5]}">${icon(["lock", "alert", "doc", "alert", "alert"][i % 5])}</span>${sk("85%", "8px")}</div>`).join("")}</div>`;
  },

  numbered(b) {
    return `<div class="numbered ${b.tinted ? "tinted" : ""}">${Array.from({ length: b.rows }, (_, i) => `
      <div class="num-row"><span class="num n${i % 5}">${i + 1}</span><div class="num-text"><b>${sk("55%", "9px")}</b>${sk("92%", "7px", "light")}${sk("70%", "7px", "light")}</div></div>`).join("")}</div>`;
  },

  form(b) {
    return `<div class="form-block">${b.heading ? `<div class="form-heading">${b.heading}</div>` : ""}
      <div class="form-grid">${b.fields.map((f, i) => `
        <label class="form-field ${f.wide ? "wide" : ""}">
          ${b.heading ? "" : `<span>${f.label}:</span>`}
          ${f.area ? `<textarea rows="3" placeholder="${b.heading ? f.label : ""}"></textarea>` : `<input type="text" placeholder="${b.heading ? f.label : ""}" />`}
        </label>`).join("")}</div></div>`;
  },

  note(b) { return `<p class="note"><i></i>${b.text}</p>`; },

  /* composite: two columns */
  split(b) {
    const render = x => Array.isArray(x) ? x.map(renderBlock).join("") : renderBlock(x);
    return `<div class="split"><div class="split-l">${render(b.left)}</div><div class="split-r">${render(b.right || [])}</div></div>`;
  },

  dual(b) {
    const col = c => `<div class="dual-col tone-${c.tone}"><div class="dual-head">${c.title}</div>${
      Array.from({ length: c.rows }, (_, i) => `<div class="dual-row">${sk("55%", "8px")}<span class="dual-bar" style="width:${ghost(i, 30, 85)}%"></span>${sk("28px", "8px")}</div>`).join("")}</div>`;
    return `<div class="dual">${col(b.left)}${col(b.right)}</div>`;
  }
};

function renderBlock(b) {
  const fn = BLOCKS[b.type];
  return fn ? fn(b) : "";
}

/* -------------------------- panel / kpi ------------------------- */
function renderKpi(k) {
  return `<article class="kpi tone-${k.tone}">
    <div class="kpi-ico">${icon(k.icon)}</div>
    <div class="kpi-body">
      <span class="kpi-label">${k.label}</span>
      <strong class="kpi-val">--</strong>
      <small class="kpi-data" hidden></small>
    </div>
  </article>`;
}

function renderPanel(p) {
  const select = p.select ? `<select class="mini-select" aria-label="${p.title} selector">${p.select.map(value => {
    const label = value === "Top 10" ? "Top" : value === "Bottom 10" ? "Bottom" : value;
    return `<option value="${value}">${label}</option>`;
  }).join("")}</select>` : "";
  return `<section class="panel span-${p.span} ${p.stack ? "stack" : ""}" id="panel-${p.n}">
    <header class="panel-head">
      <div class="panel-ttl">
        <span class="panel-ico ${p.iconTone ? "tone-" + p.iconTone : ""}">${icon(p.icon || "bars")}</span>
        <div><h2>${p.n}. ${p.title}</h2>${p.desc ? `<p>${p.desc}</p>` : ""}</div>
      </div>
      ${p.fields ? `<span class="fields-tag" title="Database fields used">${p.fields}</span>` : ""}
      <button type="button" class="card-expand" data-card-expand aria-label="Expand ${p.title}" title="Expand card"><svg viewBox="0 0 20 20" aria-hidden="true"><path d="M7 3H3v4M13 3h4v4M17 13v4h-4M3 13v4h4M3 7l5-5m4 0 5 5m0 6-5 5m-4 0-5-5"/></svg></button>
    </header>
    ${select ? `<div class="panel-controls">${select}</div>` : ""}
    <div class="panel-body">${p.blocks.map(renderBlock).join("")}</div>
    ${p.note ? `<p class="note foot"><i></i>${p.note}</p>` : ""}
  </section>`;
}

// Shared card expansion controls; supports dashboard panels and generated AI cards.
(function initCardExpansion() {
  let expandedCard = null;
  function close() {
    if (!expandedCard) return;
    expandedCard.classList.remove("card-expanded");
    expandedCard.querySelector("[data-card-expand]")?.setAttribute("aria-label", "Expand card");
    expandedCard.querySelector("[data-card-expand]")?.setAttribute("title", "Expand card");
    expandedCard = null;
    document.body.classList.remove("card-expansion-open");
  }
  document.addEventListener("click", event => {
    const button = event.target.closest("[data-card-expand]");
    if (button) {
      const card = button.closest(".panel, .ai-performance-card");
      if (!card) return;
      if (expandedCard === card) { close(); return; }
      close(); expandedCard = card;
      card.classList.add("card-expanded");
      button.setAttribute("aria-label", "Close expanded card");
      button.setAttribute("title", "Close expanded card");
      document.body.classList.add("card-expansion-open");
      return;
    }
    if (event.target === document.body && expandedCard) close();
  });
  document.addEventListener("keydown", event => { if (event.key === "Escape") close(); });
})();
