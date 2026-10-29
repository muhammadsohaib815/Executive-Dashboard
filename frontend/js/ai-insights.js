/* Compact, dashboard-style AI Sales Insights panel. */
(function () {
  const root = document.getElementById('aiInsights');
  if (!root) return;

  const $ = id => document.getElementById(id);
  const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  const amount = value => value == null ? 'N/A' : `PKR ${Number(value).toLocaleString('en-PK', { maximumFractionDigits: 0 })}`;
  const performanceBand = value => Number(value) >= 100 ? 'high' : Number(value) >= 70 ? 'average' : 'low';
  const percent = value => value == null ? 'N/A' : `${Number(value).toFixed(1)}%`;
  const signedPercent = value => value == null ? 'New' : `${Number(value) >= 0 ? '+' : ''}${Number(value).toFixed(1)}%`;
  const discountPair = row => `${percent(row.discount_pct)} / ${row.discount_budget_pct == null ? 'N/A' : percent(row.discount_budget_pct)}`;
  const inFlightRequests = new Map();
  async function getJSON(url) {
    if (inFlightRequests.has(url)) return inFlightRequests.get(url);
    const request = (async () => {
      const response = await fetch(url);
      if (!response.ok) throw new Error('Request failed');
      return response.json();
    })();
    inFlightRequests.set(url, request);
    try { return await request; }
    finally { if (inFlightRequests.get(url) === request) inFlightRequests.delete(url); }
  }
  const salesSignal = row => {
    const gap = Number(row.actual || 0) - Number(row.target || 0);
    return gap >= 0 ? `Sales are ${amount(gap)} above target.` : `Sales are ${amount(Math.abs(gap))} below target.`;
  };
  const keyPoints = row => {
    const points = [];
    const achievement = Number(row.achievement_pct || 0);
    const ucc = Number(row.total_ucc || 0);
    const growth = Number(row.golm_pct);
    const variance = row.discount_variance_pp == null ? null : Number(row.discount_variance_pp);
    points.push(salesSignal(row));
    if (achievement >= 100 && growth > 0) points.push(`Momentum is strong: achievement is ${percent(achievement)} with sales growth of ${signedPercent(growth)}.`);
    else if (achievement < 70 && growth < 0) points.push(`Recovery risk: achievement is ${percent(achievement)} and sales declined ${Math.abs(growth).toFixed(1)}% versus last month.`);
    else if (achievement >= 100) points.push(`Target leadership: achievement is ${percent(achievement)}; protect this run rate in the next cycle.`);
    else if (achievement >= 70) points.push(`Near-plan delivery: achievement is ${percent(achievement)}; close the remaining target gap.`);
    else points.push(`Recovery priority: achievement is ${percent(achievement)} and needs focused coverage.`);
    if (ucc === 0) points.push('No matched customer records were found in the selected sales scope.');
    else if (ucc < 25) points.push(`Customer reach is concentrated at ${ucc} UCC; add productive outlets before extending volume.`);
    else if (ucc >= 100) points.push(`Broad customer reach across ${ucc} UCC is supporting the selected sales scope.`);
    else points.push(`Customer coverage includes ${ucc} UCC in the selected month.`);
    if (variance == null) points.push('Discount target is unavailable for this scope, so no budget exception is inferred.');
    else if (variance > 2) points.push(`Discount exception: actual discount is ${variance.toFixed(1)} pp above target.`);
    else if (variance < -2) points.push(`Pricing headroom: discount is ${Math.abs(variance).toFixed(1)} pp below target.`);
    else points.push(`Discount is controlled within ${Math.abs(variance).toFixed(1)} pp of target.`);
    return points;
  };
  const chevronSvg = '<span class="ai-diagnosis-arrow" aria-hidden="true"><svg width="13" height="13" viewBox="0 0 14 14" fill="none"><path d="M3 5.25L7 9.25L11 5.25" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/></svg></span>';
  const kpHtml = row => `<div class="ai-card-diagnosis ai-card-keypoints">
    <button type="button" class="ai-diagnosis-head neutral" aria-expanded="false" title="Click to show/hide details">
      <div class="ai-diagnosis-head-text"><b>KEY POINTS</b><span>Product performance indicators</span></div>
      ${chevronSvg}
    </button>
    <div class="ai-diagnosis-body" hidden>
      <ul>${keyPoints(row).map(point => `<li>${esc(point)}</li>`).join('')}</ul>
    </div>
  </div>`;
  const findingHtml = (item, tone) => {
    const related = Array.isArray(item.related_items) ? item.related_items : [];
    const remaining = related.slice(3);
    const relatedTotal = Number(item.related_total ?? related.length);
    const remainingTotal = Math.max(0, relatedTotal - 3);
    const evidence = Array.isArray(item.evidence) ? item.evidence.filter(Boolean) : [];
    const evidenceDropdown = evidence.length
      ? `<details class="ai-evidence"><summary>View evidence (${evidence.length})</summary><ul>${evidence.map(point => `<li>${esc(point)}</li>`).join('')}</ul></details>`
      : '';
    const expandedNames = remaining.length
      ? `<details class="ai-related-names"><summary>Show more names (${remaining.length}${remainingTotal > remaining.length ? ` of ${remainingTotal}` : ''})</summary><ul>${remaining.map(person => `<li><b>${esc(person.name)}</b>${person.value ? ` <span>(${esc(person.value)})</span>` : ''}</li>`).join('')}</ul></details>`
      : '';
    return `<li class="ai-why ${tone}"><div class="ai-why-top"><b>${esc(item.title)}</b>${item.impact > 0 ? `<span>${esc(item.impact_label)}</span>` : ''}</div><p>${esc(item.detail)}</p>${evidenceDropdown}${expandedNames}</li>`;
  };
  const bridgeHtml = bridge => {
    if (!bridge) return '';
    const part = (label, value, tone) => Math.abs(value) < 1 ? '' : `<span class="${tone}">${label} <b>${value > 0 ? '+' : '−'}${amount(Math.abs(value))}</b></span>`;
    return `<div class="ai-bridge"><small>VS LAST MONTH (CUSTOMER BRIDGE)</small><div>${part('Lost customers', bridge.lost, 'neg')}${part('Buying less', bridge.reduced, 'neg')}${part('New customers', bridge.new, 'pos')}${part('Buying more', bridge.grew, 'pos')}</div></div>`;
  };
  const diagnosisHtml = row => {
    const d = row.diagnosis;
    if (!d) return kpHtml(row);
    const high = Number(row.achievement_pct) >= 100;
    const main = high ? d.strengths : d.blockers;
    const sections = [];
    if (main.length) sections.push(`<ul class="ai-why-list">${main.map(item => findingHtml(item, high ? 'good' : 'bad')).join('')}</ul>`);
    if (high && d.watch.length) sections.push(`<div class="ai-why-sub">WATCH-OUTS</div><ul class="ai-why-list">${d.watch.map(item => findingHtml(item, 'warn')).join('')}</ul>`);
    if (!high && d.strengths.length) sections.push(`<div class="ai-why-sub">STILL WORKING</div><ul class="ai-why-list">${d.strengths.map(item => findingHtml(item, 'good')).join('')}</ul>`);
    if (!high && d.ruled_out.length) sections.push(`<div class="ai-ruled"><b>RULED OUT</b>${d.ruled_out.map(text => `<span>✓ ${esc(text)}</span>`).join('')}</div>`);
    if (d.bridge) sections.push(bridgeHtml(d.bridge));
    return `<div class="ai-card-diagnosis">
      <button type="button" class="ai-diagnosis-head ${high ? 'good' : 'bad'}" aria-expanded="false" title="Click to show/hide details">
        <div class="ai-diagnosis-head-text">
          <b>${high ? 'WHY IT IS PERFORMING' : 'WHY IT IS NOT SELLING'}</b>
          <span>${esc(d.headline)}</span>
        </div>
        ${chevronSvg}
      </button>
      <div class="ai-diagnosis-body" hidden>
        ${sections.join('')}
      </div>
    </div>`;
  };
  const DESIGNATIONS = [['ALL', 'All Designations'], ['SPO', 'SPO'], ['MIO', 'MIO'], ['ASM', 'ASM'], ['RSM', 'RSM'], ['HOD', 'HOD'], ['ASMTE', 'ASMTE'], ['CM', 'CM'], ['DGM', 'DGM'], ['EXEC', 'EXEC'], ['PS', 'PS'], ['SB', 'SB'], ['SPOWS', 'SPOWS'], ['TE', 'TE']];
  const defaultMonths = typeof MONTHS !== 'undefined' && Array.isArray(MONTHS) ? [...MONTHS] : ['Jul-2026'];
  const fiscalYearForMonth = month => {
    const match = String(month || '').match(/^[A-Za-z]{3}-(\d{4})$/);
    if (!match) return '2026-27';
    const year = Number(match[1]);
    const monthName = String(month).slice(0, 3).toLowerCase();
    const startYear = ['jan', 'feb', 'mar', 'apr', 'may', 'jun'].includes(monthName) ? year - 1 : year;
    return `${startYear}-${String(startYear + 1).slice(-2)}`;
  };
  const state = {
    mode: 'employee', band: 'all', visibleCount: 4, enabled: false, loading: false,
    data: null, request: 0, designation: 'ALL', month: defaultMonths[0] || 'Jul-2026',
    monthOptions: defaultMonths, fy: fiscalYearForMonth(defaultMonths[0] || 'Jul-2026'), monthTouched: false,
    pageSize: 20, pageOffset: 0, allowedDesignations: null, metadataDesignations: null, authenticatedUser: null
  };

  // The AI panel follows the same hierarchy scope as the dashboard.  A
  // scoped account must never be offered a designation outside its reporting
  // tree; field users are locked to their own position level.  Managers can
  // still choose an accessible level (for example an RSM can choose ASM),
  // while the API remains the final authorization boundary.
  const fieldDesignations = new Set(['MIO', 'SPO', 'PS', 'SB', 'ASMTE', 'CM', 'SPOWS', 'TE']);
  const preferredChildLevels = {
    EXEC: ['RSM', 'ASM', 'SPO', 'MIO'], HOD: ['RSM', 'ASM', 'SPO', 'MIO'], DGM: ['RSM', 'ASM', 'SPO', 'MIO'],
    RSM: ['ASM', 'SPO', 'MIO'], ASM: ['SPO', 'MIO', 'PS', 'SB', 'ASMTE', 'CM', 'SPOWS', 'TE']
  };
  function scopedDesignationFallback(available) {
    const values = available.filter(value => value && value !== 'ALL');
    if (!values.length) return 'ALL';
    const own = String(state.authenticatedUser?.designation || '').trim().toUpperCase();
    if (fieldDesignations.has(own) && values.includes(own)) return own;
    const preferred = (preferredChildLevels[own] || []).find(value => values.includes(value));
    return preferred || (values.includes(own) ? own : values[0]);
  }
  function setAllowedDesignations(values) {
    const normalized = Array.from(new Set((values || []).map(value => String(value || '').trim().toUpperCase()).filter(Boolean)));
    state.metadataDesignations = normalized;
    const scoped = state.authenticatedUser && state.authenticatedUser.role !== 'admin' && state.authenticatedUser.scope_position_code;
    state.allowedDesignations = scoped ? normalized.filter(value => value !== 'ALL') : null;
    if (state.allowedDesignations && (!state.allowedDesignations.includes(state.designation))) {
      state.designation = scopedDesignationFallback(state.allowedDesignations);
      state.pageOffset = 0;
      state.visibleCount = 4;
    }
  }

  function filters() {
    const params = new URLSearchParams({
      mode: state.mode === 'product' ? 'product' : 'employee',
      designation: state.designation,
      month: state.month,
      fy: state.fy,
      band: state.band,
      offset: state.pageOffset,
      limit: state.pageSize
    });
    return params;
  }

  async function loadIndependentOptions() {
    try {
      const metadata = await getJSON('/api/meta?team=COMBINED');
      const months = Array.isArray(metadata.months) && metadata.months.length ? metadata.months : defaultMonths;
      state.monthOptions = months;
      if (Array.isArray(metadata.designations)) setAllowedDesignations(metadata.designations);
      if (!state.monthTouched) state.month = months[months.length - 1];
      else if (!months.includes(state.month)) state.month = months[months.length - 1];
      state.fy = fiscalYearForMonth(state.month);
      shell();
      if (state.enabled) loadInsights();
    } catch (_) {
      // The built-in reporting calendar remains available if metadata cannot load.
    }
  }

  function stat(label, value, tone) {
    return `<div class="ai-stat tone-${tone}"><span>${label}</span><b>${value}</b><em>Selected-period findings</em></div>`;
  }

  function shell() {
    const productMode = state.mode === 'product';
    const designationOptions = (state.allowedDesignations || DESIGNATIONS.filter(([value]) => value !== 'ALL').map(([value]) => value));
    const designationValues = state.allowedDesignations ? designationOptions : ['ALL', ...designationOptions];
    root.classList.add('open');
    root.innerHTML = `
      <header class="ai-head ai-compact-head">
        <div class="ai-title"><span class="ai-logo">✦</span><div><h2>AI SALES INSIGHTS</h2><p>Deterministic performance, gap, discount and risk analysis</p></div></div>
        <button type="button" id="aiToggle" class="ai-load-toggle" aria-pressed="${state.enabled}">${state.enabled ? 'Turn Off' : 'Load Insights'}</button>
      </header>
      <div class="ai-compact-body" ${state.enabled ? '' : 'hidden'}>
        <div class="ai-context"><div class="ai-context-filters">
          <label>Designation <select id="aiDesignation">${designationValues.map(value => {
            const label = (DESIGNATIONS.find(item => item[0] === value) || [value, value])[1];
            return `<option value="${value}" ${value === state.designation ? 'selected' : ''}>${label}</option>`;
          }).join('')}</select></label>
          <label>Month <select id="aiMonth">${state.monthOptions.map(month => `<option value="${esc(month)}" ${month === state.month ? 'selected' : ''}>${esc(month)}</option>`).join('')}</select></label>
          <div class="ai-mode-toggle" role="tablist" aria-label="AI insight scope">
            <button type="button" class="${state.mode === 'employee' ? 'active' : ''}" data-ai-mode="employee" aria-selected="${state.mode === 'employee'}">Employee</button>
            <button type="button" class="${state.mode === 'product' ? 'active' : ''}" data-ai-mode="product" aria-selected="${state.mode === 'product'}">Product</button>
          </div>
          <div class="ai-mode-toggle" role="tablist" aria-label="AI insight level">
            <button type="button" class="${state.band === 'all' ? 'active' : ''}" data-ai-band="all" aria-selected="${state.band === 'all'}">ALL</button>
            <button type="button" class="${state.band === 'high' ? 'active' : ''}" data-ai-band="high" aria-selected="${state.band === 'high'}">HIGH</button>
            <button type="button" class="${state.band === 'average' ? 'active' : ''}" data-ai-band="average" aria-selected="${state.band === 'average'}">AVG</button>
            <button type="button" class="${state.band === 'low' ? 'active' : ''}" data-ai-band="low" aria-selected="${state.band === 'low'}">LOW</button>
          </div>
        </div></div>
        <section class="ai-analysis-section" aria-label="AI analysis results" aria-live="polite">
          <div class="ai-analysis-section-head">
            <div><span>AI ANALYSIS</span><h3>Performance findings</h3></div>
            <small id="aiAnalysisStatus">Ready to analyze</small>
          </div>
          <div id="aiPerformanceCards" class="ai-performance-cards"></div>
        </section>
      </div>`;
    bind();
  }

  function bind() {
    $('aiToggle')?.addEventListener('click', () => {
      state.enabled = !state.enabled;
      state.loading = false;
      state.data = null;
      state.request++;
      shell();
      if (state.enabled) loadInsights();
    });
    $('aiDesignation')?.addEventListener('change', event => {
      state.designation = event.target.value;
      state.visibleCount = 4;
      state.pageOffset = 0;
      if (state.enabled) loadInsights();
    });
    $('aiMonth')?.addEventListener('change', event => {
      state.month = event.target.value;
      state.fy = fiscalYearForMonth(state.month);
      state.monthTouched = true;
      state.visibleCount = 4;
      state.pageOffset = 0;
      if (state.enabled) loadInsights();
    });
    root.querySelectorAll('[data-ai-mode]').forEach(button => button.addEventListener('click', () => {
      if (state.mode === button.dataset.aiMode) return;
      state.mode = button.dataset.aiMode;
      state.visibleCount = 4;
      state.pageOffset = 0;
      shell();
      if (state.enabled) loadInsights();
    }));
    root.querySelectorAll('[data-ai-band]').forEach(button => button.addEventListener('click', () => {
      state.band = button.dataset.aiBand;
      state.visibleCount = 4;
      state.pageOffset = 0;
      shell();
      if (state.enabled) loadInsights();
    }));
  }

  function cardIdentityHtml(row, isProduct) {
    if (isProduct) return `<span>SKU ${esc(row.product_id || 'N/A')}</span>`;
    const join = values => values
      .filter(value => value != null && String(value).trim() && String(value).trim().toLowerCase() !== 'all')
      .map(esc).join(' · ');
    const roleAndPosition = join([row.designation || state.designation, row.position_code || row.employee_id]);
    const teamAndTerritory = join([row.team, row.territory]);
    const geography = join([row.region, row.zone, row.subzone]);
    const manager = join([row.reports_to, row.reports_to_position_code]);
    return `<div class="ai-card-identity">
      ${roleAndPosition ? `<span class="ai-card-role-position">${roleAndPosition}</span>` : ''}
      ${teamAndTerritory ? `<span><em>Team / Territory</em>${teamAndTerritory}</span>` : ''}
      ${geography ? `<span><em>Region / Zone / Sub Zone</em>${geography}</span>` : ''}
      ${manager ? `<span><em>Reports to</em>${manager}</span>` : ''}
    </div>`;
  }

  function paint(data) {
    const performanceBox = $('aiPerformanceCards');
    if (performanceBox) {
      performanceBox.classList.remove('is-loading', 'has-error');
      const isProduct = state.mode === 'product';
      const records = (isProduct ? data.product_performance : data.employee_performance) || [];
      const recordsForBand = records.filter(row => isProduct || state.designation === 'ALL' || String(row.designation || '').toUpperCase() === String(state.designation).toUpperCase());
      const totalRecords = isProduct ? (data.product_total ?? recordsForBand.length) : (data.employee_total ?? recordsForBand.length);
      performanceBox.hidden = !recordsForBand.length;
      const title = isProduct ? 'PRODUCT PERFORMANCE' : 'INDIVIDUAL EMPLOYEE PERFORMANCE';
      const itemLabel = isProduct ? 'products' : 'employees';
      performanceBox.hidden = false;
      const status = $('aiAnalysisStatus');
      if (status) status.textContent = `${totalRecords} ${isProduct ? 'product' : 'employee'}${totalRecords === 1 ? '' : 's'} available`;
      const visibleRecords = recordsForBand.slice(0, state.visibleCount);
      performanceBox.innerHTML = recordsForBand.length
        ? `<h3>${title} <small>Showing ${visibleRecords.length} of ${totalRecords} ${itemLabel}</small></h3><div class="ai-performance-grid">${visibleRecords.map(row => `<article class="ai-performance-card performance-${performanceBand(row.achievement_pct)}"><button type="button" class="card-expand" data-card-expand aria-label="Expand ${esc(isProduct ? row.product : row.employee)}" title="Expand card"><svg viewBox="0 0 20 20" aria-hidden="true"><path d="M7 3H3v4M13 3h4v4M17 13v4h-4M3 13v4h4M3 7l5-5m4 0 5 5m0 6-5 5m-4 0-5-5"/></svg></button><div class="ai-card-head"><div><b>${esc(isProduct ? row.product : row.employee)}</b>${cardIdentityHtml(row, isProduct)}</div><strong>${percent(row.achievement_pct)}</strong></div><div class="ai-card-metrics"><div class="ai-card-sales"><span>Net Sales <b>${amount(row.actual)}</b></span><span>Target <b>${amount(row.target)}</b></span></div><div class="ai-card-kpis"><div><small>Total UCC</small><b>${esc(row.total_ucc ?? 0)}</b></div><div><small>GOLM</small><b>${signedPercent(row.golm_pct)}</b><em>Prev ${amount(row.previous_sales)} → This ${amount(row.actual)}</em></div><div><small>Disc A / T</small><b>${discountPair(row)}</b><em>Actual / Target</em></div></div></div>${diagnosisHtml(row)}</article>`).join('')}</div>${visibleRecords.length < recordsForBand.length || (isProduct ? data.has_more_products : data.has_more_employees) ? '<button type="button" class="ai-load-more" data-ai-load-more>Load More</button>' : ''}`
        : `<p class="ai-performance-empty">No ${itemLabel} match the selected ${state.band.toUpperCase()} level for this designation and month.</p>`;
      performanceBox.querySelector('[data-ai-load-more]')?.addEventListener('click', async () => {
        if (state.visibleCount < recordsForBand.length) {
          state.visibleCount += 4;
          paint(data);
          return;
        }
        state.pageOffset += state.pageSize;
        state.visibleCount += 4;
        await loadInsights(true);
      });
    }

  }

  function showAnalysisLoading(message = 'Loading AI analysis...') {
    const performanceBox = $('aiPerformanceCards');
    if (!performanceBox) return;
    performanceBox.hidden = false;
    performanceBox.classList.remove('has-error');
    performanceBox.classList.add('is-loading');
    performanceBox.innerHTML = `<div class="ai-analysis-loading" role="status"><span class="ai-analysis-spinner" aria-hidden="true"></span><div><strong>${esc(message)}</strong><p>Reviewing performance, target gaps, discount control and risk signals.</p></div></div>`;
    const status = $('aiAnalysisStatus');
    if (status) status.textContent = 'Analysis in progress';
  }

  async function loadInsights(append = false) {
    if (!state.enabled) return;
    const request = ++state.request;
    state.loading = true;
    showAnalysisLoading();
    try {
      const requestStarted = performance.now();
      const data = await getJSON('/api/ai-insights?' + filters());
      if (request !== state.request || !state.enabled) return;
      state.loading = false;
      if (append && state.data) {
        const key = state.mode === 'product' ? 'product_performance' : 'employee_performance';
        data[key] = [...(state.data[key] || []), ...(data[key] || [])];
      }
      state.data = data;
      const renderStarted = performance.now();
      paint(data);
      window.aiInsightsPerformance = {
        endpoint: '/api/ai-insights',
        request_ms: Math.round((renderStarted - requestStarted) * 10) / 10,
        render_ms: Math.round((performance.now() - renderStarted) * 10) / 10,
        appended: Boolean(append)
      };
    } catch (_) {
      if (request !== state.request || !state.enabled) return;
      state.loading = false;
      showAnalysisLoading('AI analysis could not be loaded. Please try again.');
      $('aiPerformanceCards')?.classList.add('has-error');
      const status = $('aiAnalysisStatus');
      if (status) status.textContent = 'Analysis unavailable';
    }
  }

  root.addEventListener('click', event => {
    const toggle = event.target.closest('.ai-diagnosis-head');
    if (!toggle) return;
    const diag = toggle.closest('.ai-card-diagnosis');
    if (!diag) return;
    const body = diag.querySelector('.ai-diagnosis-body');
    if (!body) return;
    const willOpen = body.hidden;
    body.hidden = !willOpen;
    diag.classList.toggle('is-open', willOpen);
    toggle.setAttribute('aria-expanded', String(willOpen));
  });

  // auth.js loads after this module.  Reconcile the AI selector as soon as
  // the authenticated account is known, so a direct SPO/MIO account cannot
  // briefly see national or unrelated employee choices.
  document.addEventListener('dashboard:auth-user', event => {
    state.authenticatedUser = event.detail || null;
    const scoped = state.authenticatedUser.role !== 'admin' && state.authenticatedUser.scope_position_code;
    if (scoped) {
      setAllowedDesignations(state.metadataDesignations || []);
      const current = Array.isArray(state.allowedDesignations) ? state.allowedDesignations : [];
      if (current.length) {
        const next = scopedDesignationFallback(current);
        if (next !== state.designation) {
          state.designation = next;
          state.pageOffset = 0;
          state.visibleCount = 4;
        }
      }
      shell();
      if (state.enabled) loadInsights();
    }
  });

  shell();
  loadIndependentOptions();
})();
