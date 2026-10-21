/* ------------------------------------------------------------------
   App bootstrap – populates filters and re-renders the dashboard
   whenever the DESIGNATION filter changes.
------------------------------------------------------------------- */
(function () {
  const $ = id => document.getElementById(id);
  const appEl = $("app") || $("executive-dashboard") || document.querySelector(".app");
  const state = { designation: loadDesignation() };
  const layoutFor = d => DASHBOARDS[d] || {
    ...COMMON_FIELD_LAYOUT,
    key: "generic",
    title: `${d} PERFORMANCE DASHBOARD`,
    subtitle: `${d} | Team Performance | Target vs Actual`
  };

  function loadDesignation() {
    // Start on the full executive view after refresh; users can still choose a specific designation.
    return "ALL";
  }

  function fillSelect(el, values, selected) {
    const labels = { ALL: "Designation" };
    const hiddenDesignations = new Set(["ALL", "EXEC", "HOD", "DGM"]);
    const visibleValues = values.filter(v => !hiddenDesignations.has(v));
    el.innerHTML = `<option value="">Designation</option>` + visibleValues.map(v => `<option value="${v}" ${v === selected ? "selected" : ""}>${labels[v] || v}</option>`).join("");
    el.value = selected === "ALL" ? "" : selected;
  }

  function initFilters() {
    setupFilterDrawer();
    fillSelect($("fDesignation"), DESIGNATIONS, state.designation);
    fillSelect($("fMonth"), MONTHS, MONTHS[0]);
    fillSelect($("fFY"), FISCAL_YEARS, FISCAL_YEARS[0]);
    $("fDesignation").addEventListener("change", e => {
      setDesignation(e.target.value || "ALL");
      updateApplyState(false);
    });
    $("applyFilters")?.addEventListener("click", () => {
      const selectedDesignation = state.pendingDesignation || $("fDesignation").value || "ALL";
      if (selectedDesignation !== state.designation) setDesignation(selectedDesignation);
      document.dispatchEvent(new CustomEvent("filters:apply"));
      updateApplyState(false);
    });
  }

  function setupFilterDrawer() {
    const dashboard = $("dashboard"), filters = $("filters");
    if (!dashboard || !filters || $("filterToggle")) return;
    const wrap = document.createElement("div");
    wrap.className = "filter-drawer";
    const button = document.createElement("button");
    button.type = "button"; button.id = "filterToggle"; button.className = "filter-toggle";
    button.setAttribute("aria-expanded", "false");
    button.setAttribute("aria-controls", "filters");
    button.setAttribute("aria-label", "Open filters");
    button.setAttribute("title", "Filters");
    const headerControls = document.querySelector(".header-controls");
    if (headerControls) {
      button.classList.add("header-filter-toggle");
      button.innerHTML = icon("filter");
      headerControls.insertBefore(button, $("adminLink") || $("logoutButton") || null);
    } else {
      button.innerHTML = `${icon("filter")}<span>Filters</span><b class="filter-count">0</b><span class="filter-chevron">⌄</span>`;
      wrap.append(button);
    }
    filters.parentNode.removeChild(filters);
    wrap.append(filters);
    dashboard.parentNode.insertBefore(wrap, dashboard);
    button.addEventListener("click", () => {
      const open = wrap.classList.toggle("open");
      button.setAttribute("aria-expanded", String(open));
      button.setAttribute("aria-label", open ? "Close filters" : "Open filters");
    });
    const searchToggle = $("fNameSearchToggle");
    const searchInput = $("fNameSearch");
    searchToggle.addEventListener("click", () => {
      const open = searchToggle.closest(".filter").classList.toggle("filter-search-open");
      searchToggle.textContent = open ? "×" : "⌕";
      if (open) searchInput.focus();
    });
    filters.querySelectorAll(".filter-search-toggle").forEach(searchToggle => {
      if (searchToggle === $("fNameSearchToggle")) return;
      const searchInput = $(searchToggle.dataset.searchFor) || searchToggle.parentElement.querySelector(".filter-search");
      const filter = searchToggle.closest(".filter");
      searchToggle.addEventListener("click", () => {
        const open = filter.classList.toggle("filter-search-open");
        searchToggle.textContent = open ? "×" : "⌕";
        if (open && searchInput) searchInput.focus();
      });
    });
    filters.addEventListener("change", () => {
      const count = Array.from(filters.querySelectorAll("select")).filter(s => !["fDesignation", "fTeam", "fMonth", "fFY"].includes(s.id) && s.value && s.value !== "All").length;
      button.querySelector(".filter-count")?.replaceChildren(document.createTextNode(count));
    });
  }


  function setDesignation(value) {
    state.designation = value;
    state.pendingDesignation = value;
    localStorage.setItem("designation", value);
    history.replaceState(null, "", "#" + encodeURIComponent(value));
    render(true);
  }
  // Let the employee filter switch the dashboard to that employee's role.
  window.setDashboardDesignation = setDesignation;

  function updateApplyState(dirty = true) {
    const button = $("applyFilters");
    if (!button) return;
    button.classList.toggle("is-dirty", dirty || state.pendingDesignation !== state.designation);
  }

  function render(animate) {
    const cfg = layoutFor(state.designation);
    if (appEl) appEl.dataset.designation = cfg.key;
    if (window.updateDashboardHeader) {
      window.updateDashboardHeader();
    } else {
      document.title = `${cfg.title} | Executive Sales Dashboard`;
      $("dashTitle").textContent = cfg.title;
    }
    // ALL is the internal dashboard scope; show the field-name placeholder
    // until the user picks a designation.
    $("fDesignation").value = state.designation === "ALL" ? "" : state.designation;

    const dash = $("dashboard");
    const paint = () => {
      $("kpiRow").innerHTML = cfg.kpis.map(renderKpi).join("");
      $("panelGrid").innerHTML = cfg.panels.map(renderPanel).join("");
      bindInteractions();
      dash.classList.remove("swap-out");
      dash.classList.add("swap-in");
      setTimeout(() => dash.classList.remove("swap-in"), 500);
      document.dispatchEvent(new CustomEvent("dashboard:rendered", { detail: { designation: state.designation } }));
    };

    if (animate) {
      dash.classList.add("swap-out");
      setTimeout(paint, 180);
    } else {
      paint();
    }
  }

  function bindInteractions() {
    document.querySelectorAll(".tabs").forEach(group => {
      group.addEventListener("click", e => {
        const tab = e.target.closest(".tab");
        if (!tab) return;
        group.querySelectorAll(".tab").forEach(t => t.classList.toggle("active", t === tab));
      });
    });
  }

  window.addEventListener("hashchange", () => {
    const v = decodeURIComponent(location.hash.replace("#", ""));
    if (DESIGNATIONS.includes(v) && v !== state.designation) setDesignation(v);
  });

  initFilters();
  state.pendingDesignation = state.designation;
  // Populate Month/FY from the records actually loaded in sales_data before
  // requesting dashboard data. This selects the newest available month on a
  // fresh page load (currently Sep-2026), while later selections are retained.
  const initialMeta = window.loadDashboardMeta?.(undefined, { preferLatestMonth: true });
  if (initialMeta?.then) {
    initialMeta.then(() => render(false), () => render(false));
  } else {
    render(false);
  }
})();
