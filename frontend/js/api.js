/* ------------------------------------------------------------------
   Data layer – talks to server.py and fills the dashboard.
   Currently wires: filters (Region/Zone/Sub Zone/Month/FY) + KPI cards.
------------------------------------------------------------------- */
(function () {
  const $ = id => document.getElementById(id);
  const getAppEl = () => $("app") || $("executive-dashboard") || document.querySelector(".app");
  const ids = { employee: "fName", region: "fRegion", zone: "fZone", subzone: "fSubZone", territory: "fTerritory", month: "fMonth", fy: "fFY" };
  let valueMetric = "net_with_reg";
  let periodMode = "MTD";
  let closeActionOwnerPicker = null;

  /* KPI label -> API metric */
  const METRIC = {
    "GROSS TP ACH.": "gross_tp", "NET SALES ACH.": "net_sales", "UNITS ACH.": "units",
    "CYP ACH.": "cyp",
    "DISCOUNT % VS BUDGET": "discount", "DISCOUNT %": "discount",
    "ACTIVE MIO": "active_mio", "ACTIVE SPO": "active_spo",
    "ACTIVE MIO/SPO": "active_staff", "ACTIVE SHOPS": "active_shops", "ACTIVE SHOPS & COVERAGE %": "active_shops", "RETURNS VALUE": "returns",
    "GROSS PROFIT MARGIN %": "gross_profit_margin_pct", "ACTIVE FIELD STAFF": "active_field_staff",
    "TOP CUSTOMER PERFORMANCE %": "top_customer_performance_pct"
    ,"NET SALES ACHIEVEMENT %": "net_sales_value", "NET SALES VALUE": "net_sales_value", "NET SALE VALUE ACHIEVEMENT %": "net_sales_value", "NET SALE VALUE": "net_sales_value", "UNITS ACHIEVEMENT %": "units", "TARGET GAP": "target_gap",
    "ACTIVE RSM": "active_lower_staff", "ACTIVE ASM": "active_lower_staff", "ACTIVE SPO/MIO": "active_lower_staff", "GOLM": "golm",
    "PRODUCTIVE SHOPS": "productive_shops", "AVG. SALES / PRODUCTIVE SHOP": "avg_sales_per_productive_shop", "RETURN RATE %": "returns",
    "TP VALUE": "tp_value", "NET VALUE WITH REGULAR DISC.": "net_value"
  };

  /* ------------------------------ formatters ------------------------------ */
  const fmt = (n, d = 1) => Number(n).toLocaleString("en-US", { minimumFractionDigits: d, maximumFractionDigits: d });
  const short = n => {
    const a = Math.abs(n);
    if (a >= 1e9) return fmt(n / 1e9, 2) + "B";
    if (a >= 1e6) return fmt(n / 1e6, 1) + "M";
    if (a >= 1e3) return fmt(n / 1e3, 1) + "K";
    return fmt(n, 0);
  };
  const rs = n => "Rs. " + short(n);
  const pct = n => (n == null ? "--" : fmt(n, 1) + "%");
  const change = (now, prior, suffix = "") => prior == null ? "" : ` | ${now - prior >= 0 ? "+" : ""}${fmt(now - prior, 1)}${suffix} vs prev`;

  /* ------------------------------ status banner ------------------------------ */
  function status(msg) {
    let el = $("apiStatus");
    if (!msg) { if (el) el.remove(); return; }
    if (!el) {
      el = document.createElement("div");
      el.id = "apiStatus"; el.className = "api-status"; el.setAttribute("role", "alert");
      $("dashboard").before(el);
    }
    el.textContent = msg;
  }

  const inFlightRequests = new Map();
  async function getJSON(url) {
    if (inFlightRequests.has(url)) return inFlightRequests.get(url);
    const request = (async () => {
      const r = await fetch(url);
      if (!r.ok) {
        let detail = "";
        try { const body = await r.json(); detail = body.detail ? `: ${body.detail}` : ""; } catch (_) {}
        throw new Error(`${r.status} ${r.statusText}${detail}`);
      }
      return r.json();
    })();
    inFlightRequests.set(url, request);
    try { return await request; }
    finally { if (inFlightRequests.get(url) === request) inFlightRequests.delete(url); }
  }

  /* ------------------------------ filter state ------------------------------ */
  let currentDesignation = "";
  const filterFields = ["employee", "region", "zone", "subzone", "territory"];
  const userSelections = { employee: "All", zone: "All", subzone: "All", region: "All", territory: "All" };
  const effectiveSelections = { employee: "All", zone: "All", subzone: "All", region: "All", territory: "All" };
  const autoFilledSelections = new Set();
  let employeeScopeSnapshot = null;
  let employeeScopeRequestId = 0;
  let territoryScopeRequestId = 0;
  let activeTerritoryScope = null;
  let activeEmployeeRecord = null;
  let authenticatedDashboardUser = null;
  let lastHeaderMeta = {};
  let hierarchyDrilldownTrail = [];
  let scopedHierarchyRoot = null;
  let hierarchyNavigationBusy = false;
  let filterRequestId = 0;

  const current = () => ({
    designation: $("fDesignation").value || "ALL",
    employee: effectiveSelections.employee,
    region: effectiveSelections.region,
    zone: effectiveSelections.zone,
    subzone: effectiveSelections.subzone,
    territory: $(ids.territory) ? effectiveSelections.territory : "All",
    month: $(ids.month).value || "Jul-2026",
    fy: $(ids.fy).value || "2026-27",
    team: $("fTeam")?.value || "COMBINED",
    period: periodMode,
    value_metric: valueMetric
  });
  window.getDashboardChatFilters = () => ({ ...current() });
  const qs = o => new URLSearchParams(o).toString();

  function fillSelectOptions(el, values, selected, field, search = "") {
    if (!el) return;
    const cleanValues = values.filter(value => String(value).trim().toLowerCase() !== "all");
    const safeSelected = cleanValues.includes(selected) ? selected : "All";
    const allLabels = {
      employee: "Employee",
      region: "Region",
      zone: "Zone",
      subzone: "Sub Zone",
      territory: "Dept Terr Code"
    };
    const options = [{ value: "All", label: allLabels[field] || field } , ...cleanValues.map(v => ({ value: v, label: v }))];
    el.innerHTML = options.map(o => `<option value="${o.value}" ${o.value === safeSelected ? "selected" : ""}>${o.label}</option>`).join("");
    el.value = safeSelected;
    renderFilterPicker(field, search);
  }

  function renderEmployeePicker(values, search = "") {
    const list = $("employeePickerOptions");
    const trigger = $("employeePickerToggle");
    const selected = effectiveSelections.employee;
    if (trigger) trigger.textContent = selected !== "All" ? selected : "Employee";
    if (!list) return;
    const needle = String(search || "").trim().toLowerCase();
    const matches = values.filter(name => !needle || name.toLowerCase().includes(needle));
    list.innerHTML = `<button type="button" class="employee-picker-option employee-picker-clear" data-employee-value="All" role="option">Employee</button>` +
      (matches.length ? matches.map(name => `<button type="button" class="employee-picker-option" data-employee-value="${html(name)}" role="option">${html(name)}</button>`).join("") : `<div class="employee-picker-empty">No employees found</div>`);
  }

  const filterPickerConfig = {
    designation: { id: "fDesignation", label: "Designation" },
    region: { id: "fRegion", label: "Region" },
    zone: { id: "fZone", label: "Zone" },
    subzone: { id: "fSubZone", label: "Sub Zone" },
    territory: { id: "fTerritory", label: "Dept Terr Code" }
  };

  function renderFilterPicker(field, search = "") {
    const config = filterPickerConfig[field];
    if (!config) return;
    const select = $(config.id);
    const trigger = document.querySelector(`[data-picker-toggle="${field}"]`);
    const list = document.querySelector(`[data-picker-options="${field}"]`);
    if (!select || !trigger || !list) return;
    const options = Array.from(select.options).map(option => ({ value: option.value, label: option.textContent }));
    const chosen = options.find(option => option.value === select.value);
    trigger.textContent = chosen?.label || config.label;
    const needle = String(search || "").trim().toLowerCase();
    const matches = options.filter(option => !needle || option.label.toLowerCase().includes(needle));
    list.innerHTML = matches.length
      ? matches.map(option => `<button type="button" class="filter-picker-option${option.value === "All" || option.value === "" ? " filter-picker-clear" : ""}" data-filter-picker-value="${html(option.value)}" role="option">${html(option.label)}</button>`).join("")
      : `<div class="filter-picker-empty">No matching options found</div>`;
  }

  function adaptLegacyFilterRows(data, searchField = "", search = "") {
    if (!Array.isArray(data.rows)) return data;
    const fields = { employee: "employee", region: "region", zone: "zone", subzone: "subzone", territory: "territory" };
    for (const [field, key] of Object.entries(fields)) {
      const rows = data.rows.filter(row => filterFields.every(other =>
        other === field || userSelections[other] === "All" || row[other] === userSelections[other]
      ));
      let values = Array.from(new Set(rows.map(row => row[key]).filter(Boolean))).sort();
      if (field === searchField && search) values = values.filter(value => value.toLowerCase().includes(search.toLowerCase()));
      data[field] = values;
    }
    return data;
  }

  async function loadFilters(designation, team = "COMBINED", searchField = "", search = "") {
    const requestId = ++filterRequestId;
    let data;
    for (let pass = 0; pass < filterFields.length + 1; pass++) {
      const params = new URLSearchParams({ designation, team, ...userSelections, search_field: searchField, search });
      data = adaptLegacyFilterRows(await getJSON("/api/filters?" + params), searchField, search);
      if (requestId !== filterRequestId) return;
      let reset = false;
      for (const field of filterFields) {
        if (field === searchField && search) continue;
        if (userSelections[field] !== "All" && !(data[field] || []).includes(userSelections[field])) {
          userSelections[field] = "All";
          autoFilledSelections.delete(field);
          reset = true;
        }
      }
      if (!reset) break;
    }
    for (const field of filterFields) effectiveSelections[field] = userSelections[field];
    const selectIds = { employee: ids.employee, region: ids.region, zone: ids.zone, subzone: ids.subzone, territory: ids.territory };
    for (const field of filterFields) {
      const values = [...(data?.[field] || [])];
      if (effectiveSelections[field] !== "All" && !values.includes(effectiveSelections[field])) values.push(effectiveSelections[field]);
      fillSelectOptions($(selectIds[field]), values, effectiveSelections[field], field);
    }
    renderEmployeePicker(data?.employee || [], searchField === "employee" ? search : "");
  }

  async function searchFilterOptions(field, search = "") {
    const requestId = ++filterRequestId;
    const params = new URLSearchParams({
      designation: $("fDesignation").value || "ALL",
      team: $("fTeam")?.value || "COMBINED",
      ...userSelections,
      search_field: field,
      search
    });
    const data = adaptLegacyFilterRows(await getJSON("/api/filters?" + params), field, search);
    if (requestId !== filterRequestId) return;
    const values = data[field] || [];
    if (field === "employee") {
      renderEmployeePicker(values, search);
      return;
    }
    const selectId = { region: ids.region, zone: ids.zone, subzone: ids.subzone, territory: ids.territory }[field];
    fillSelectOptions($(selectId), values, effectiveSelections[field], field, search);
  }

  function applyCascadingFilters(changedField, newVal) {
    if (changedField) {
      employeeScopeRequestId += 1;
      // Keep compatible selections; loadFilters clears only values that no
      // longer exist in the changed scope. This avoids wiping valid manual or
      // employee-derived filters during a cascade.
      autoFilledSelections.delete(changedField);
      userSelections[changedField] = newVal || "All";
    }
    // A selected territory already supplied the exact related rows.  Do not
    // replace those constrained choices with the generic top-down lists.
    if (activeTerritoryScope && userSelections.territory === activeTerritoryScope.territory) {
      for (const field of filterFields) effectiveSelections[field] = userSelections[field];
      return Promise.resolve();
    }
    return loadFilters($("fDesignation").value || "ALL", $("fTeam")?.value || "COMBINED");
  }

  function chooseEmployeeRecord(records) {
    const team = $("fTeam")?.value || "COMBINED";
    const designation = $("fDesignation")?.value || "";
    const score = record =>
      (team !== "COMBINED" && record.team_filter === team ? 2 : 0) +
      (designation && record.designation === designation ? 1 : 0);
    return [...records].sort((a, b) => score(b) - score(a))[0];
  }

  function hierarchyNode(record) {
    if (!record) return null;
    return {
      employee: String(record.employee || "").trim(),
      designation: String(record.designation || "").trim().toUpperCase(),
      position_code: String(record.position_code || "").trim()
    };
  }

  function sameHierarchyNode(left, right) {
    if (!left || !right) return false;
    if (left.position_code && right.position_code) return left.position_code === right.position_code;
    return left.employee === right.employee && left.designation === right.designation;
  }

  function normalizedHierarchyTrail(nodes = hierarchyDrilldownTrail) {
    return nodes.filter(node => !sameHierarchyNode(node, scopedHierarchyRoot));
  }

  function renderHierarchyBreadcrumb() {
    const nav = $("hierarchyBreadcrumb");
    if (!nav) return;
    const root = scopedHierarchyRoot
      ? hierarchyNode(scopedHierarchyRoot)
      : { employee: "Executive", designation: "", position_code: "" };
    const trail = normalizedHierarchyTrail();
    const nodes = [root, ...trail];
    nav.replaceChildren();

    const label = document.createElement("span");
    label.className = "hierarchy-breadcrumb-label";
    label.textContent = "Hierarchy";
    nav.append(label);

    nodes.forEach((node, index) => {
      if (index) {
        const separator = document.createElement("span");
        separator.className = "hierarchy-breadcrumb-separator";
        separator.setAttribute("aria-hidden", "true");
        separator.textContent = "›";
        nav.append(separator);
      }
      const button = document.createElement("button");
      button.type = "button";
      button.className = "hierarchy-breadcrumb-item";
      button.dataset.hierarchyBreadcrumbIndex = String(index - 1);
      if (index === 0) button.dataset.hierarchyBreadcrumbRoot = "true";
      const name = node.employee || node.position_code || node.designation || "Dashboard";
      button.textContent = node.designation && name !== node.designation
        ? `${node.designation}: ${name}`
        : name;
      button.title = node.position_code
        ? `${node.designation || "Employee"} · ${node.position_code}`
        : "Return to the executive dashboard";
      if (index === nodes.length - 1) {
        button.setAttribute("aria-current", "page");
        button.disabled = true;
      }
      nav.append(button);
    });
  }

  function setDesignationValue(value) {
    const select = $("fDesignation");
    if (!select) return;
    if (value && !Array.from(select.options).some(option => option.value === value)) {
      select.add(new Option(value, value));
    }
    select.value = value || "";
    renderFilterPicker("designation");
  }

  function distinctScopeValues(records, field) {
    return Array.from(new Set(records.map(record => String(record[field] || "").trim()).filter(Boolean))).sort();
  }

  function setTeamOptions(teams, selected = "COMBINED") {
    const control = $("fTeam");
    if (!control) return "COMBINED";
    const available = teams.length ? teams : ["FMCG", "PHARMA"];
    const safeSelected = available.includes(selected) ? selected : "COMBINED";
    control.replaceChildren(
      new Option("Team", "COMBINED"),
      ...available.map(team => new Option(team === "PHARMA" ? "Pharma" : team, team))
    );
    control.value = safeSelected;
    return safeSelected;
  }

  function setScopedDesignationOptions(designations) {
    const control = $("fDesignation");
    if (!control) return "ALL";
    const selected = designations.length === 1 ? designations[0] : "ALL";
    control.replaceChildren(
      new Option("Designation", ""),
      ...designations.map(designation => new Option(designation, designation))
    );
    control.value = selected === "ALL" ? "" : selected;
    renderFilterPicker("designation");
    return selected;
  }

  async function applyTerritorySelection(territory) {
    const requestId = ++territoryScopeRequestId;
    const selectedTerritory = String(territory || "").trim();
    employeeScopeRequestId += 1;
    employeeScopeSnapshot = null;

    if (!selectedTerritory || selectedTerritory === "All") {
      activeTerritoryScope = null;
      if (lastHeaderMeta) {
        lastHeaderMeta.territory = "";
        lastHeaderMeta.dept_territory_code = "";
        lastHeaderMeta.position_code = "";
      }
      setTeamOptions([], $("fTeam")?.value || "COMBINED");
      await applyCascadingFilters("territory", "All");
      updateDashboardHeader();
      if (requestId === territoryScopeRequestId) refresh({ reloadFilters: false });
      return;
    }

    try {
      const response = await getJSON("/api/territory-scope?territory=" + encodeURIComponent(selectedTerritory));
      if (requestId !== territoryScopeRequestId) return;
      const records = response.records || [];
      if (!records.length) throw new Error("No matching staff records were returned");

      const teams = distinctScopeValues(records, "team_filter").filter(team => team !== "COMBINED");
      const team = setTeamOptions(teams, teams.length === 1 ? teams[0] : "COMBINED");
      await loadMeta(team);
      if (requestId !== territoryScopeRequestId) return;

      const fields = ["employee", "region", "zone", "subzone", "territory"];
      const valuesByField = Object.fromEntries(fields.map(field => [field, distinctScopeValues(records, field)]));
      valuesByField.territory = [selectedTerritory];
      activeTerritoryScope = { territory: selectedTerritory, records, valuesByField };
      for (const field of fields) {
        const values = valuesByField[field];
        const selected = values.length === 1 ? values[0] : "All";
        userSelections[field] = selected;
        effectiveSelections[field] = selected;
        autoFilledSelections.add(field);
      }

      const selectIds = { employee: ids.employee, region: ids.region, zone: ids.zone, subzone: ids.subzone, territory: ids.territory };
      for (const field of fields) {
        fillSelectOptions($(selectIds[field]), valuesByField[field], effectiveSelections[field], field);
      }
      renderEmployeePicker(valuesByField.employee);
      const designation = setScopedDesignationOptions(distinctScopeValues(records, "designation"));
      updateDashboardHeader({
        territory: selectedTerritory,
        dept_territory_code: selectedTerritory,
        department: records[0]?.department,
        header_region: records[0]?.region
      });
      if (window.setDashboardDesignation) {
        window.setDashboardDesignation(designation);
      } else {
        refresh({ reloadFilters: false });
      }
    } catch (error) {
      if (requestId !== territoryScopeRequestId) return;
      status("Could not resolve Dept Terr Code from staff records: " + error.message);
      await applyCascadingFilters("territory", selectedTerritory);
      refresh({ reloadFilters: false });
    }
  }

  async function applyEmployeeSelection(employee, { positionCode = "" } = {}) {
    const requestId = ++employeeScopeRequestId;
    const selectedEmployee = employee || "All";
    const exactPosition = String(positionCode || "").trim();
    if (selectedEmployee === "All") {
      activeEmployeeRecord = null;
      if (lastHeaderMeta) {
        lastHeaderMeta.employee = "";
        lastHeaderMeta.position_code = "";
        lastHeaderMeta.dept_territory_code = "";
      }
      autoFilledSelections.forEach(field => {
        if (field !== "employee") userSelections[field] = "All";
      });
      autoFilledSelections.clear();
      userSelections.employee = "All";
      if (employeeScopeSnapshot) {
        const previous = employeeScopeSnapshot;
        employeeScopeSnapshot = null;
        $("fTeam").value = previous.team;
        await loadMeta(previous.team);
        if (requestId !== employeeScopeRequestId) return;
        setDesignationValue(previous.designation);
      }
      const team = $("fTeam")?.value || "COMBINED";
      const designation = $("fDesignation")?.value || "ALL";
      await loadFilters(designation, team);
      if (requestId !== employeeScopeRequestId) return;
      updateDashboardHeader();
      window.setDashboardDesignation?.(designation);
      return null;
    }

    try {
      const params = exactPosition
        ? new URLSearchParams({ position_code: exactPosition })
        : new URLSearchParams({ employee: selectedEmployee });
      const endpoint = exactPosition ? "/api/position-scope?" : "/api/employee-scope?";
      const response = await getJSON(endpoint + params);
      if (requestId !== employeeScopeRequestId) return;
      const record = exactPosition
        ? (response.records || []).find(item => String(item.position_code || "").trim() === exactPosition) || response.records?.[0]
        : chooseEmployeeRecord(response.records || []);
      if (!record) throw new Error("No matching staff record was returned");

      if (!employeeScopeSnapshot) {
        employeeScopeSnapshot = {
          team: $("fTeam")?.value || "COMBINED",
          designation: $("fDesignation")?.value || ""
        };
      }
      autoFilledSelections.forEach(field => {
        if (field !== "employee") userSelections[field] = "All";
      });
      autoFilledSelections.clear();
      const scope = {
        employee: record.employee || selectedEmployee,
        region: record.region || "All",
        zone: record.zone || "All",
        subzone: record.subzone || "All",
        territory: record.territory || "All"
      };
      Object.entries(scope).forEach(([field, value]) => {
        userSelections[field] = value;
        effectiveSelections[field] = value;
        autoFilledSelections.add(field);
      });
      activeEmployeeRecord = record;
      const team = record.team_filter || "COMBINED";
      $("fTeam").value = team;
      await loadMeta(team);
      if (requestId !== employeeScopeRequestId) return;
      const designation = record.designation || "ALL";
      setDesignationValue(designation === "ALL" ? "" : designation);
      await loadFilters(designation, team);
      if (requestId !== employeeScopeRequestId) return;
      updateDashboardHeader({
        employee: record.employee || selectedEmployee,
        team_filter: team,
        team: team,
        designation: designation,
        department: record.department,
        position_code: record.position_code,
        dept_territory_code: record.territory,
        header_region: record.region,
        region: record.region
      });
      window.setDashboardDesignation?.(designation);
      return record;
    } catch (error) {
      if (requestId !== employeeScopeRequestId) return;
      status("Could not load the selected employee's staff record: " + error.message);
      if (exactPosition) return null;
      await applyCascadingFilters("employee", selectedEmployee);
      refresh({ reloadFilters: false });
      return null;
    }
  }

  async function drillIntoHierarchy({ employee, positionCode }) {
    if (hierarchyNavigationBusy || !positionCode) return;
    hierarchyNavigationBusy = true;
    const previousTrail = normalizedHierarchyTrail();
    const parent = hierarchyNode(activeEmployeeRecord);
    let nextTrail = [...previousTrail];
    if (parent && !sameHierarchyNode(parent, scopedHierarchyRoot) && !sameHierarchyNode(nextTrail.at(-1), parent)) {
      const parentIndex = nextTrail.findIndex(node => sameHierarchyNode(node, parent));
      nextTrail = parentIndex >= 0 ? nextTrail.slice(0, parentIndex + 1) : [...nextTrail, parent];
    }
    try {
      const record = await applyEmployeeSelection(employee, { positionCode });
      if (!record) return;
      const target = hierarchyNode(record);
      const existingIndex = nextTrail.findIndex(node => sameHierarchyNode(node, target));
      hierarchyDrilldownTrail = existingIndex >= 0
        ? nextTrail.slice(0, existingIndex + 1)
        : [...nextTrail, target];
      renderHierarchyBreadcrumb();
    } catch (error) {
      hierarchyDrilldownTrail = previousTrail;
      renderHierarchyBreadcrumb();
      status("Could not open the selected employee dashboard: " + error.message);
    } finally {
      hierarchyNavigationBusy = false;
    }
  }

  async function navigateHierarchyBreadcrumb(index, isRoot) {
    if (hierarchyNavigationBusy) return;
    hierarchyNavigationBusy = true;
    const previousTrail = normalizedHierarchyTrail();
    try {
      if (isRoot) {
        hierarchyDrilldownTrail = [];
        renderHierarchyBreadcrumb();
        if (scopedHierarchyRoot) {
          await applyEmployeeSelection(scopedHierarchyRoot.employee, {
            positionCode: scopedHierarchyRoot.position_code
          });
        } else {
          await applyEmployeeSelection("All");
        }
        return;
      }
      const target = previousTrail[index];
      if (!target) return;
      hierarchyDrilldownTrail = previousTrail.slice(0, index + 1);
      renderHierarchyBreadcrumb();
      const record = await applyEmployeeSelection(target.employee, { positionCode: target.position_code });
      if (!record) throw new Error("The selected hierarchy level is no longer available");
    } catch (error) {
      hierarchyDrilldownTrail = previousTrail;
      renderHierarchyBreadcrumb();
      status("Could not return to the selected hierarchy level: " + error.message);
    } finally {
      hierarchyNavigationBusy = false;
    }
  }

  let authenticatedScopeRequestId = 0;
  async function applyAuthenticatedScope(user) {
    if (!user || user.role === "admin" || !user.scope_position_code) return;
    const requestId = ++authenticatedScopeRequestId;
    try {
      const response = await getJSON("/api/position-scope?position_code=" + encodeURIComponent(user.scope_position_code));
      if (requestId !== authenticatedScopeRequestId) return;
      const record = response.records?.[0];
      if (!record) throw new Error("No staff record exists for the assigned position");

      activeEmployeeRecord = record;
      scopedHierarchyRoot = record;
      hierarchyDrilldownTrail = [];
      renderHierarchyBreadcrumb();
      employeeScopeSnapshot = null;
      autoFilledSelections.clear();
      const scopedValues = {
        employee: record.employee || "All", region: record.region || "All",
        zone: record.zone || "All", subzone: record.subzone || "All",
        territory: record.territory || "All"
      };
      Object.entries(scopedValues).forEach(([field, value]) => {
        userSelections[field] = value;
        effectiveSelections[field] = value;
        autoFilledSelections.add(field);
      });

      const team = record.team_filter || "COMBINED";
      setTeamOptions([team], team);
      $("fTeam").value = team;
      $("teamToggle")?.querySelectorAll("[data-team]").forEach(item => {
        item.setAttribute("aria-pressed", String(item.dataset.team === team));
      });
      periodMode = "YTD";
      $("periodToggle")?.querySelectorAll("[data-period]").forEach(item => {
        item.setAttribute("aria-pressed", String(item.dataset.period === "YTD"));
      });
      valueMetric = "net_with_reg";
      $("valueToggle")?.querySelectorAll("[data-value-metric]").forEach(item => {
        item.setAttribute("aria-pressed", String(item.dataset.valueMetric === valueMetric));
      });

      await loadMeta(team, { preferLatestMonth: true });
      setDesignationValue(record.designation || "SPO");
      await loadFilters(record.designation || "SPO", team);
      if (requestId !== authenticatedScopeRequestId) return;
      updateDashboardHeader({
        employee: record.employee, designation: record.designation, team: record.team,
        team_filter: team, position_code: record.position_code,
        dept_territory_code: record.territory, territory: record.territory,
        department: record.department, header_region: record.region,
        region: record.region, zone: record.zone, subzone: record.subzone
      });
      window.setDashboardDesignation?.(record.designation || "SPO");
    } catch (error) {
      status("Could not load your assigned dashboard position: " + error.message);
    }
  }

  async function resetDashboardView() {
    // A scoped user must remain on their assigned position after reset.  The
    // same bootstrap path restores the assigned team, designation and scope.
    if (authenticatedDashboardUser && authenticatedDashboardUser.role !== "admin" && authenticatedDashboardUser.scope_position_code) {
      await applyAuthenticatedScope(authenticatedDashboardUser);
      return;
    }

    employeeScopeRequestId += 1;
    territoryScopeRequestId += 1;
    filterRequestId += 1;
    activeTerritoryScope = null;
    activeEmployeeRecord = null;
    scopedHierarchyRoot = null;
    hierarchyDrilldownTrail = [];
    renderHierarchyBreadcrumb();
    employeeScopeSnapshot = null;
    autoFilledSelections.clear();
    for (const field of filterFields) {
      userSelections[field] = "All";
      effectiveSelections[field] = "All";
    }
    lastHeaderMeta = {};
    periodMode = "MTD";
    valueMetric = "net_with_reg";
    $("periodToggle")?.querySelectorAll("[data-period]").forEach(item => {
      item.setAttribute("aria-pressed", String(item.dataset.period === periodMode));
    });
    $("valueToggle")?.querySelectorAll("[data-value-metric]").forEach(item => {
      item.setAttribute("aria-pressed", String(item.dataset.valueMetric === valueMetric));
    });
    setTeamOptions([], "COMBINED");
    $("fFY").value = "";
    $("fDesignation").value = "";
    await loadMeta("COMBINED", { preferLatestMonth: true });
    await loadFilters("ALL", "COMBINED");
    window.setDashboardDesignation?.("ALL");
    updateDashboardHeader();
    refresh({ reloadFilters: false });
  }

  window.resetDashboardView = resetDashboardView;

  document.addEventListener("dashboard:auth-user", event => {
    authenticatedDashboardUser = event.detail || null;
    applyAuthenticatedScope(event.detail);
    if (latestData) paintSpoPanels(latestData);
  });

  function renderDropdowns(searchField = "", search = "") {
    return searchFilterOptions(searchField, search);
  }

  function renderEmployeeOptions(search = "") {
    return searchFilterOptions("employee", search);
  }

  let metaReady = Promise.resolve();
  function loadMeta(team = $("fTeam")?.value || "COMBINED", { preferLatestMonth = false } = {}) {
    metaReady = getJSON("/api/meta?team=" + encodeURIComponent(team)).then(m => {
      const designation = $("fDesignation");
      const keep = designation.value || "ALL";
      const hiddenDesignations = new Set(["EXEC", "HOD", "DGM"]);
      const apiDesignations = Array.isArray(m.designations) ? m.designations : [];
      const fromApi = apiDesignations.filter(v => v !== "ALL" && !hiddenDesignations.has(String(v).trim().toUpperCase()));
      const fromConfig = DESIGNATIONS.filter(v => v !== "ALL" && !hiddenDesignations.has(String(v).trim().toUpperCase()));
      const visibleDesignations = Array.isArray(m.designations) ? fromApi : fromConfig;
      designation.innerHTML = `<option value="">Designation</option>` + visibleDesignations.map(v => `<option value="${v}">${v}</option>`).join("");
      designation.value = visibleDesignations.includes(keep) ? keep : "";
      renderFilterPicker("designation");
      const set = (el, vals, preferLatest = false) => {
        const keep = el.value;
        // On first load use the newest month that exists in sales_data. Later
        // metadata refreshes retain the user's current choice when possible.
        const selected = preferLatest ? vals.at(-1) : (vals.includes(keep) ? keep : vals.at(-1));
        el.innerHTML = vals.map(v => `<option ${v === selected ? "selected" : ""}>${v}</option>`).join("");
        el.value = selected || "";
      };
      set($(ids.month), m.months, preferLatestMonth);
      set($(ids.fy), m.fiscal_years);
      updateDashboardHeader();
    });
    return metaReady;
  }
  // app.js starts the first dashboard render after its filter controls exist.
  // Exposing this small bootstrap hook keeps months sourced from sales_data.
  window.loadDashboardMeta = loadMeta;

  /* ------------------------------ KPI cards ------------------------------ */
  function setKpi(card, val, sub, state) {
    card.querySelector(".kpi-val").textContent = val;
    const data = card.querySelector(".kpi-data");
    if (data) {
      if (Array.isArray(sub)) {
        data.hidden = sub.length === 0;
        data.innerHTML = sub.map(detail =>
          `<span class="kpi-detail"><b>${html(detail.label)}</b> ${html(detail.value)}</span>`
        ).join("");
      } else {
      const showSalesTarget = card.dataset.metricKey === "net_sales_value" && sub != null;
      data.hidden = !showSalesTarget;
      if (!showSalesTarget) {
        data.textContent = "";
      } else {
        const salesTarget = String(sub).replace(/^Sales\s+/, "").split(/\s+·\s+Target\s+/);
        data.innerHTML = salesTarget.length === 2
          ? `<b>Sales</b> ${salesTarget[0]}<span>·</span><b>Target</b> ${salesTarget[1]}`
          : sub;
      }
      }
    }
    card.classList.remove("ach-good", "ach-warn", "ach-bad");
    if (state) card.classList.add("ach-" + state);
  }
  const achState = a => (a == null ? null : a >= 100 ? "good" : a >= 80 ? "warn" : "bad");

  function paintKpis(d) {
    const selectedMetricIsCount = ["units", "cyp"].includes(d.meta?.value_metric);
    const selectedValue = n => selectedMetricIsCount ? fmt(Number(n || 0), 0) : rs(n);
    const selectedMetricLabel = d.meta?.value_metric_label || "NET SALE VALUE";
    document.querySelectorAll("#kpiRow .kpi").forEach(card => {
      const label = card.querySelector(".kpi-label").textContent.trim();
      const key = card.dataset.metricKey || METRIC[label];
      const m = key && d[key];
      if (m === null || m === undefined) return; // preserve legitimate zero values
      switch (key) {
        case "net_sales_value": {
          card.dataset.metricKey = "net_sales_value";
          const actual = selectedValue(Number(m.actual));
          const target = selectedValue(Number(m.target));
          card.querySelector(".kpi-label").textContent = `${selectedMetricLabel} ACHIEVEMENT %`;
          setKpi(card, label === "NET SALES VALUE" ? actual : pct(m.ach), [
            { label: "Sales", value: actual }, { label: "Target", value: target }
          ], achState(m.ach));
          break;
        }
        case "golm": {
          const current = selectedValue(Number(d.net_sales_value?.actual || 0));
          const previous = selectedValue(Number(d.golm_previous_value || 0));
          setKpi(card, pct(m), [
            { label: "Current", value: current }, { label: "Previous", value: previous }
          ], m == null ? null : m >= 0 ? "good" : "bad");
          break;
        }
        case "active_lower_staff":
        case "active_field_staff":
          setKpi(card, fmt(m.actual, 0), `${fmt(m.actual, 0)} with sales / ${fmt(m.target, 0)} total`, achState(m.ach)); break;
        case "active_shops":
          setKpi(card, fmt(m.actual, 0), [
            { label: "Active", value: fmt(m.actual, 0) }, { label: "Total", value: fmt(m.total, 0) }
          ], achState(m.ach)); break;
        case "gross_profit_margin_pct":
          setKpi(card, m == null ? "--" : pct(m), "Actual COGS is unavailable", null); break;
        case "top_customer_performance_pct":
          setKpi(card, pct(m), "Top customer's share of positive sales", null); break;
        case "target_gap": {
          const gap = Number(m);
          const ahead = d.target_gap_status === "ahead";
          const gapValue = selectedValue(Math.abs(gap));
          setKpi(card, gapValue, [
            { label: "Actual", value: selectedValue(Number(d.net_sales_value?.actual || 0)) },
            { label: "Target", value: selectedValue(Number(d.net_sales_value?.target || 0)) }
          ], ahead ? "good" : "bad"); break;
        }
        case "productive_shops":
          setKpi(card, fmt(Number(m), 0), `Positive net sales${change(Number(m), d.spo_metrics.previous.shops)}`, null); break;
        case "avg_sales_per_productive_shop":
          setKpi(card, selectedValue(Number(d.avg_sales_per_productive_shop)), `${d.meta.value_metric_label} / productive shop`, null); break;
        case "tp_value":
        case "net_value": {
          const value = Number(d.discount[key]);
          setKpi(card, rs(value), "Selected period actual", null); break;
        }
        case "units":
          setKpi(card, pct(m.ach), [
            { label: "Units", value: short(m.actual) }, { label: "Target", value: short(m.target) }
          ], achState(m.ach)); break;
        case "cyp":
          setKpi(card, pct(m.ach), `${fmt(m.actual, 0)} / ${fmt(m.target, 0)}`, achState(m.ach)); break;
        case "discount": {
          const diff = m.actual_pct != null && m.budget_pct != null ? m.actual_pct - m.budget_pct : null;
          setKpi(card, pct(m.actual_pct),
            [
              { label: "Actual", value: pct(m.actual_pct) },
              { label: "Budget", value: pct(m.budget_pct) }
            ],
            diff == null ? null : diff > 0 ? "bad" : "good"); break;
        }
        case "active_mio":
        case "active_spo":
        case "active_staff":
          setKpi(card, fmt(m.actual, 0), `Target ${fmt(m.target, 0)} | ${pct(m.ach)}`, achState(m.ach)); break;
        case "returns":
          setKpi(card, pct(m.pct), `${rs(m.value)} returned${change(m.pct, d.spo_metrics.previous.return_pct, " pp")}`, m.pct > 5 ? "bad" : "good"); break;
        default:  /* gross_tp, net_sales, net_wo_reg */
          setKpi(card, pct(m.ach), `${rs(m.actual)} / ${rs(m.target)}${key === "net_sales" ? change(m.actual, d.spo_metrics.previous.net_sales, " Rs.") : key === "units" ? change(m.actual, d.spo_metrics.previous.units) : ""}`, achState(m.ach));
      }
    });
    // All designations use the same reliable customer/SKU/discount card set.
    paintSpoPanels(d);
    paintProductPanel(d);
  }

  const money = n => rs(n || 0);
  function paintSpoPanels(d) {
    const sections = d.spo_sections || {};
    const metricIsCount = ["units", "cyp"].includes(d.meta?.value_metric);
    const metricValue = n => metricIsCount ? fmt(Number(n || 0), 0) : rs(n);
    const actualLabel = metricIsCount ? "Actual" : "Sales";
    const metricLabel = d.meta?.value_metric_label || "NET SALE VALUE";
    const key = getAppEl()?.dataset?.designation || "ALL";
    const topChoice = (document.querySelector("#panel-1 .mini-select:not(.hierarchy-role-select)") || {}).value || "Top";
    const skuChoice = (document.querySelector("#panel-2 .mini-select") || {}).value || "Top";
    const discountChoice = (document.querySelector("#panel-3 .mini-select") || {}).value || "Top";
    const showBottom = value => String(value).toLowerCase().startsWith("bottom");
    const achievementTone = value => Number(value) >= 100 ? "achievement-high" : Number(value) >= 70 ? "achievement-average" : "achievement-low";
    const customerBox = document.querySelector("[data-spo-top-customers]");
    if (customerBox) {
      const hierarchy = [...(sections.hierarchy_performance || [])];
      const heading = document.querySelector("#panel-1 .panel-ttl h2");
      const description = document.querySelector("#panel-1 .panel-ttl p");
      if (key !== "field") {
        const roles = [...new Set(hierarchy.map(row => row.designation).filter(Boolean))].sort();
        const panelControls = document.querySelector("#panel-1 .panel-controls");
        let roleSelect = panelControls?.querySelector(".hierarchy-role-select");
        if (roles.length > 1 && panelControls) {
          const selectorAlreadyRendered = Boolean(roleSelect);
          const previous = roleSelect?.value || "";
          if (!roleSelect) {
            roleSelect = document.createElement("select");
            roleSelect.className = "mini-select hierarchy-role-select";
            roleSelect.setAttribute("aria-label", "Designation selector");
            panelControls.append(roleSelect);
          }
          roleSelect.replaceChildren(new Option("All Designations", ""), ...roles.map(role => new Option(role, role)));
          // The unfiltered executive dashboard starts with ASM. Once the user
          // changes this selector, preserve that choice (including All).
          roleSelect.value = roles.includes(previous)
            ? previous
            : (!selectorAlreadyRendered && d.meta?.designation === "ALL" && roles.includes("ASM") ? "ASM" : "");
          window.syncPanelChoice?.(roleSelect);
        } else {
          if (roleSelect) (roleSelect.closest(".panel-choice") || roleSelect).remove();
          roleSelect = null;
        }
        const selectedRole = roleSelect?.value || "";
        const filteredHierarchy = selectedRole ? hierarchy.filter(row => row.designation === selectedRole) : hierarchy;
        const label = selectedRole || sections.hierarchy_label || "Team";
        if (heading) heading.textContent = `1. ${showBottom(topChoice) ? "BOTTOM" : "TOP"} ${label} - SALES ACHIEVEMENT %`;
        if (description) description.textContent = selectedRole
          ? `Achievement percentage by ${selectedRole}. Click a name or position to open that dashboard.`
          : "Achievement percentage by employee. Click a name or position to open that dashboard.";
        const sorted = filteredHierarchy.filter(r => r.achievement_pct != null).sort((a, b) => a.achievement_pct - b.achievement_pct);
        const rows = showBottom(topChoice) ? sorted.slice(0, 25) : sorted.slice(-25).reverse();
        customerBox.innerHTML = rows.length ? rows.map(r => `<div class="hbar-row"><div class="hbar-label wide"><button type="button" class="hierarchy-drilldown" data-hierarchy-drilldown data-employee="${html(r.employee)}" data-position-code="${html(r.position_code)}" aria-label="Open ${html(r.designation)} dashboard for ${html(r.employee)}, position ${html(r.position_code)}"><b>${html(r.employee)}</b><small>${html(r.designation)} · ${html(r.position_code)}</small></button></div><div class="hbar-track"><span class="hbar-fill ${achievementTone(r.achievement_pct)}" style="width:${Math.min(100, Math.max(0, Number(r.achievement_pct)))}%"></span></div><div class="hbar-val ${achievementTone(r.achievement_pct)}">${pct(r.achievement_pct)}</div></div>`).join("") : `<div class="empty-state"><p>No ${html(selectedRole || "team")} members with matched monthly targets.</p></div>`;
      } else {
        if (heading) heading.textContent = `1. ${showBottom(topChoice) ? "BOTTOM" : "TOP"} CUSTOMERS / SHOPS PERFORMANCE %`;
        if (description) description.textContent = "Customer share of positive net sales";
        const source = showBottom(topChoice) ? (sections.bottom_customers || []) : (sections.top_customers || []);
        const rows = source.slice(0, 25);
        customerBox.innerHTML = rows.length ? rows.map((r, index) => `<div class="hbar-row ranked-row"><div class="hbar-label wide"><b>${html(r.cust_name || "Unknown customer")}</b><small class="ranked-values"><span>Sales ${rs(r.net_sales)}</span></small></div><div class="hbar-track"><span class="hbar-fill customer-rank-${index < 3 ? "high" : index < 7 ? "average" : "low"}" style="width:${Math.min(100, Math.max(0, Number(r.performance_pct || 0)))}%"></span></div><div class="hbar-val">${r.performance_pct == null ? "--" : pct(r.performance_pct)}</div></div>`).join("") : `<div class="empty-state"><p>No customer sales data available for the selected filters.</p></div>`;
      }
    }
    const skuBox = document.querySelector("[data-spo-skus]");
    const skuLegend = document.querySelector("#panel-2 .legend");
    if (skuLegend) skuLegend.hidden = false;
    if (skuBox) {
      const heading = document.querySelector("#panel-2 .panel-ttl h2");
      const description = document.querySelector("#panel-2 .panel-ttl p");
      {
        const source = sections.product_performance || [];
        const ranked = [...source].filter(r => r.achievement_pct != null).sort((a, b) => Number(a.achievement_pct) - Number(b.achievement_pct));
        const rows = showBottom(skuChoice) ? ranked.slice(0, 25) : ranked.slice(-25).reverse();
        // The bar must follow the achievement % printed at the right. Using
        // sales value here made a lower achievement sometimes look longer.
        const achievementMax = Math.max(100, ...rows.map(r => Number(r.achievement_pct || 0)));
        if (heading) heading.textContent = "2. SKU PERFORMANCE — TARGET VS ACTUAL";
        if (description) description.hidden = true;
        skuBox.innerHTML = rows.length ? rows.map(r => {
          const achievement = Number(r.achievement_pct || 0);
          const width = Math.min(100, Math.max(0, achievement / achievementMax * 100));
          return `<div class="hbar-row ranked-row"><div class="hbar-label wide"><b>${html(r.prd_name || "Unknown product")}</b><small class="ranked-values"><span>${actualLabel} ${metricValue(r.actual_net_sales)}</span><span>Target ${metricValue(r.target_net_sales)}</span></small></div><div class="hbar-track"><span class="hbar-fill target" style="width:100%"></span><span class="hbar-fill ${achievementTone(r.achievement_pct)}" style="width:${width}%"></span></div><div class="hbar-val ${achievementTone(r.achievement_pct)}">${r.achievement_pct == null ? "--" : pct(r.achievement_pct)}</div></div>`;
        }).join("") : `<div class="empty-state"><p>No SKU data available for the selected filters.</p></div>`;
      }
    }
    const disc = d.discount || {}, pctNow = disc.actual_pct || 0, pctTarget = disc.budget_pct;
    const box = document.querySelector("[data-spo-discount]");
    if (box) {
      const heading = document.querySelector("#panel-3 .panel-ttl h2");
      {
        if (heading) heading.textContent = "3. DISCOUNT, PROFITABILITY & EXCEPTIONS";
        box.querySelector("[data-discount-actual]").textContent = pct(pctNow);
        box.querySelector("[data-discount-target]").textContent = pctTarget == null ? "--" : pct(pctTarget);
        const scale = Math.max(pctNow, pctTarget || 0, 1) * 1.2;
        box.querySelector("[data-discount-fill]").style.width = `${Math.min(100, pctNow / scale * 100)}%`;
        box.querySelector("[data-discount-mark]").style.left = `${Math.min(100, (pctTarget || 0) / scale * 100)}%`;
        const variance = pctTarget == null ? null : pctTarget - pctNow;
        const varianceEl = box.querySelector("[data-discount-variance]");
        varianceEl.classList.toggle("above-budget", variance != null && variance < 0);
        varianceEl.textContent = variance == null ? "Budget comparison unavailable" :
          `${fmt(Math.abs(variance), 1)} pp ${variance >= 0 ? "favorable" : "above budget"}`;

        const productBox = box.querySelector("[data-discount-products]");
        const title = box.querySelector(".discount-product-section > b");
        const rankedProducts = [...(sections.discount_products || [])]
          .filter(row => row.discount_pct != null)
          .sort((a, b) => Number(a.discount_pct) - Number(b.discount_pct));
        const rows = showBottom(discountChoice) ? rankedProducts.slice(0, 25) : rankedProducts.slice(-25).reverse();
        const barMax = Math.max(1, ...rows.map(row => Number(row.discount_pct || 0)));
        const discountTone = value => Number(value) >= 20 ? "discount-high" : Number(value) >= 10 ? "discount-medium" : "discount-low";
        if (title) title.textContent = showBottom(discountChoice) ? "BOTTOM PRODUCT DISCOUNT %" : "TOP PRODUCT DISCOUNT %";
        if (productBox) productBox.innerHTML = rows.length ? rows.map(row => {
          const tone = discountTone(row.discount_pct);
          return `<div class="hbar-row"><div class="hbar-label wide"><b>${html(row.prd_name || "Unknown product")}</b><small>Discount ${rs(row.discount_value)} · TP ${rs(row.tp_value)}</small></div><div class="hbar-track"><span class="hbar-fill ${tone}" style="width:${Math.min(100, Math.max(0, Number(row.discount_pct || 0) / barMax * 100))}%"></span></div><div class="hbar-val ${tone}">${pct(row.discount_pct)}</div></div>`;
        }).join("") : `<div class="empty-state"><p>No product discount data is available for the selected filters.</p></div>`;
      }
    }

    const callBox = document.querySelector("[data-call-performance]");
    if (callBox) {
      const callData = sections.call_data || {};
      const callHeading = document.querySelector("#panel-4 .panel-ttl h2");
      const callDescription = document.querySelector("#panel-4 .panel-ttl p");
      const callDesignation = String(d.meta?.designation || "").toUpperCase();
      const callSource = String(callData.source_type || "FMCG").toUpperCase();
      const isPharmaCalls = callSource === "PHARMA";
      const isExecutiveCallView = ["EXEC", "HOD", "DGM", "ALL", "EXECUTIVE"].includes(callDesignation);
      const isManagerCallView = ["ASM", "RSM"].includes(callDesignation) || isExecutiveCallView;
      const isFieldCallView = ["SPO", "MIO", "PS", "SB", "ASMTE", "CM", "SPOWS", "TE"].includes(callDesignation);
      if (!callData.available) {
        if (callHeading) callHeading.textContent = "4. CALL DATA";
        if (callDescription) callDescription.textContent = "Call data is unavailable for the selected scope";
        callBox.innerHTML = `<div class="empty-state"><p>No call source is configured for the selected team.</p></div>`;
      } else if (isManagerCallView) {
        const rows = (callData.manager_days || []).slice(0, 10);
        const maxDays = Math.max(1, ...rows.map(row => Number(row.call_days || 0)));
        if (callHeading) callHeading.textContent = isExecutiveCallView ? "4. TEAM CALL PERFORMANCE" : "4. MANAGER FIELD-WORK DAYS";
        if (callDescription) callDescription.textContent = isPharmaCalls ? "Distinct Pharma provider-call days by field employee" : "Distinct FMCG customer-call and exception days by field employee";
        const callChartTitle = isExecutiveCallView ? "TOP TEAM MEMBERS BY CALL DAYS" : "SPO ACCOMPANIMENT DAYS";
        const callEmptyText = isExecutiveCallView ? "No call activity matches the selected executive scope and month." : "No SPO call-work days match the selected ASM/RSM scope and month.";
        callBox.innerHTML = rows.length ? `<div class="call-manager-chart"><div class="call-chart-title">${callChartTitle}</div><div class="hbar spo-data-scroll call-manager-list">${rows.map(row => `<div class="hbar-row"><div class="hbar-label wide"><b>${html(row.employee)}</b><small>${html(row.manager)} · ${fmt(row.calls, 0)} calls</small></div><div class="hbar-track"><span class="hbar-fill call-days-fill" style="width:${Math.min(100, Number(row.call_days || 0) / maxDays * 100)}%"></span></div><div class="hbar-val call-days-val">${fmt(row.call_days, 0)}d</div></div>`).join("")}</div></div>` : `<div class="empty-state"><p>${callEmptyText}</p></div>`;
      } else if (isFieldCallView) {
        const shops = callData.shops || [];
        const maxCalls = Math.max(1, ...shops.map(row => Number(row.calls || 0)));
        const outcomes = callData.outcomes || {};
        const exceptions = callData.exceptions || {};
        const decided = Number(outcomes.accepted || 0) + Number(outcomes.rejected || 0);
        const acceptedPct = decided ? Number(outcomes.accepted || 0) / decided * 100 : 0;
        const rejectedPct = decided ? 100 - acceptedPct : 0;
        const entityPlural = isPharmaCalls ? "PROVIDERS" : "SHOPS";
        const positiveLabel = isPharmaCalls ? "In Range" : "Accepted";
        const negativeLabel = isPharmaCalls ? "Out Range" : "Rejected";
        const ratioTitle = isPharmaCalls ? "CALL RANGE RATIO" : "CALL OUTCOME RATIO";
        if (callHeading) callHeading.textContent = "4. CALL PERFORMANCE";
        if (callDescription) callDescription.textContent = isPharmaCalls ? "Pharma provider calls and GPS range ratio" : "FMCG customer calls, outcomes, and exceptions";
        callBox.innerHTML = `<div class="call-field-charts"><section class="call-shop-chart"><div class="call-chart-title">TOP SHOPS BY TOTAL CALLS</div>${shops.length ? `<div class="hbar spo-data-scroll call-shop-list">${shops.map(row => `<div class="hbar-row"><div class="hbar-label wide"><b>${html(row.customer_name)}</b><small>${fmt(row.call_days, 0)} call day${Number(row.call_days) === 1 ? "" : "s"}</small></div><div class="hbar-track"><span class="hbar-fill call-shop-fill" style="width:${Math.min(100, Number(row.calls || 0) / maxCalls * 100)}%"></span></div><div class="hbar-val call-shop-val">${fmt(row.calls, 0)}</div></div>`).join("")}</div>` : `<p class="call-no-data">No shop calls match the selected scope and month.</p>`}</section><section class="call-outcome-chart"><div class="call-chart-title">CALL OUTCOME RATIO</div><div class="call-outcome-donut" style="--accepted:${acceptedPct}%;"><div><b>${fmt(acceptedPct, 0)}%</b><small>Accepted</small></div></div><div class="call-outcome-legend"><span><i class="accepted"></i>Accepted <b>${fmt(outcomes.accepted || 0, 0)}</b></span><span><i class="rejected"></i>Rejected <b>${fmt(outcomes.rejected || 0, 0)}</b></span><small>Shop closed: ${fmt(outcomes.shop_closed || 0, 0)}</small></div></section></div>`;
        const chartTitles = callBox.querySelectorAll(".call-chart-title");
        if (chartTitles[0]) chartTitles[0].textContent = `TOP ${entityPlural} BY TOTAL CALLS`;
        if (chartTitles[1]) chartTitles[1].textContent = ratioTitle;
        const donutLabel = callBox.querySelector(".call-outcome-donut small");
        if (donutLabel) donutLabel.textContent = positiveLabel;
        const legendRows = callBox.querySelectorAll(".call-outcome-legend span");
        if (legendRows[0]) legendRows[0].childNodes[1].textContent = positiveLabel + " ";
        if (legendRows[1]) legendRows[1].childNodes[1].textContent = negativeLabel + " ";
        const noCallData = callBox.querySelector(".call-no-data");
        if (noCallData) noCallData.textContent = `No ${entityPlural.toLowerCase()} calls match the selected scope and month.`;
        const outcomeDetail = callBox.querySelector(".call-outcome-legend small");
        if (outcomeDetail) outcomeDetail.textContent = isPharmaCalls
          ? `In Range ${fmt(acceptedPct, 0)}% | Out Range ${fmt(rejectedPct, 0)}%`
          : `Accepted ${fmt(acceptedPct, 0)}% | Rejected ${fmt(rejectedPct, 0)}% | Shop closed: ${fmt(outcomes.shop_closed || 0, 0)} | Exceptions: ${fmt(exceptions.total || 0, 0)}`;
      } else {
        if (callHeading) callHeading.textContent = "4. CALL DATA";
        if (callDescription) callDescription.textContent = `${callSource} call data follows the selected dashboard scope`;
        callBox.innerHTML = `<div class="empty-state"><p>Select ASM/RSM for field-work days or a field designation for detailed call performance.</p></div>`;
      }
    }
    const sm = d.spo_metrics || {}, gap = sm.target_gap || 0;
    const insightBox = document.querySelector("[data-spo-insights]");
    if (insightBox) {
      const rows = [], add = (title, finding, next, metrics, priority) => rows.push({title, finding, next, metrics, priority});
      const net = d.net_sales || {}, shop = d.active_shops || {}, discount = d.discount || {};
      const hierarchy = (sections.hierarchy_performance || []).filter(r => r.achievement_pct != null);
      const products = (sections.product_performance || []).filter(r => r.achievement_pct != null);
      const customers = (sections.bottom_customers || []).filter(r => r.performance_pct != null);
      const isField = key === "field";
      const ach = net.ach;
      if (ach != null) add("NET SALES HEALTH", `Net sales achievement is ${pct(ach)} against target.`, ach < 100 ? "Prioritize the largest gaps and assign recovery owners before the next review." : "Protect the run rate and replicate the strongest performing territories.", [`Actual ${rs(net.actual)}`, `Target ${rs(net.target)}`], Math.abs(100 - ach) + (ach < 80 ? 30 : 0));
      if (!isField && hierarchy.length) {
        const low = [...hierarchy].sort((a,b) => a.achievement_pct - b.achievement_pct)[0];
        const high = [...hierarchy].sort((a,b) => b.achievement_pct - a.achievement_pct)[0];
        add(`LOWEST ${low.position_code || "TEAM"} ACHIEVEMENT`, `${low.employee || "Team member"} (${low.position_code || "staff"}) is at ${pct(low.achievement_pct)}.`, "Review the territory pipeline, shop coverage and SKU mix with the owner this week.", [`Achievement ${pct(low.achievement_pct)}`], Math.max(1, 100 - low.achievement_pct) + 25);
        if (high && high.employee !== low.employee) add("TOP TEAM PERFORMANCE", `${high.employee} (${high.position_code || "staff"}) leads at ${pct(high.achievement_pct)}.`, "Document the winning routine and share it with below-plan members.", [`Achievement ${pct(high.achievement_pct)}`], high.achievement_pct >= 100 ? 12 : 5);
      }
      if (products.length) {
        const low = [...products].sort((a,b) => a.achievement_pct - b.achievement_pct)[0];
        add("SKU RECOVERY GAP", `${low.prd_name || low.product_no || "SKU"} is at ${pct(low.achievement_pct)} achievement.`, "Set a SKU-specific recovery target and check stock, distribution and outlet visibility.", [`Achievement ${pct(low.achievement_pct)}`, `Actual ${metricValue(low.actual_net_sales)}`], Math.max(1, 100 - low.achievement_pct) + 20);
      }
      if (discount.actual_pct != null && discount.budget_pct != null) {
        const over = discount.actual_pct - discount.budget_pct;
        add("DISCOUNT CONTROL", `Discount is ${pct(discount.actual_pct)} versus a ${pct(discount.budget_pct)} budget.`, over > 0 ? "Review exception orders and protect margin on the next approval cycle." : "Keep discount within the current guardrail while pursuing volume.", [`Variance ${over >= 0 ? "+" : ""}${pct(over)}`], Math.abs(over) + (over > 0 ? 25 : 5));
      }
      if (d.golm != null) add("GROWTH OVER LAST MONTH", `Growth over last month is ${pct(d.golm)}.`, d.golm < 0 ? "Build a short recovery list from declining territories or customers and review it daily." : "Use the growth pockets to offset remaining target gaps.", [`GOLM ${pct(d.golm)}`], Math.abs(d.golm) + (d.golm < 0 ? 20 : 4));
      if (shop.ach != null) add("SHOP COVERAGE", `Active shop coverage achievement is ${pct(shop.ach)}.`, shop.ach < 90 ? "Revisit inactive shops and schedule coverage for the highest-value gaps." : "Maintain visit frequency and convert uncovered shops.", [`Active ${shop.actual ?? 0}`, `Coverage ${pct(shop.ach)}`], Math.max(1, 100 - shop.ach) + (shop.ach < 80 ? 18 : 0));
      if (isField && customers.length) {
        const low = customers.sort((a,b) => a.performance_pct - b.performance_pct)[0];
        add("CUSTOMER RECOVERY", `${low.cust_name || low.cust_number || "Customer"} is at ${pct(low.performance_pct)} performance.`, "Schedule a focused visit, confirm the next order opportunity and record the recovery commitment.", [`Performance ${pct(low.performance_pct)}`], Math.max(1, 100 - low.performance_pct) + 22);
      }
      const seen = new Set();
      const finalRows = rows.sort((a,b) => b.priority - a.priority).filter(r => { const k = r.title.split(" ")[0]; if (seen.has(k)) return false; seen.add(k); return true; }).slice(0, 5);
      insightBox.innerHTML = finalRows.length ? finalRows.map((r, i) => {
        const title = String(r.title || '').toUpperCase();
        const lowest = /^LOWEST\b/.test(title);
        const tone = lowest ? 'red'
          : /TOP TEAM PERFORMANCE|TOP .*PERFORMANCE/.test(title) ? 'green'
          : /GAP/.test(title) ? 'blue'
          : /GROWTH|GOLM/.test(title) ? 'yellow'
          : 'violet';
        return `<details class="num-row section5-insight insight-tone-${tone}"><summary><span class="num insight-num-tone-${tone}">${i + 1}</span><span class="section5-insight-summary"><b class="section5-insight-title">${html(r.title)}</b><small>Click for details</small></span></summary><div class="section5-insight-detail"><span class="section5-insight-finding"><strong>Finding:</strong> ${html(r.finding)}</span><small class="section5-insight-metrics">${r.metrics.map(html).join(" · ")}</small><span class="section5-insight-next"><strong>Next Step:</strong> ${html(r.next)}</span></div></details>`;
      }).join("") : '<div class="empty-state"><p>No actionable insights are available for this selection.</p></div>';
    }
    const actions = document.querySelector("[data-spo-actions]");
    if (actions) {
      closeActionOwnerPicker?.();
      const contextPositionCode = String(
        activeEmployeeRecord?.position_code || authenticatedDashboardUser?.scope_position_code || ""
      ).trim();
      actions.innerHTML = `<form class="form-grid action-plan-form" data-action-plan-form>
        <label class="form-field wide"><span>Corrective Action:</span><textarea name="action_text" rows="3" required maxlength="4000" placeholder="Add action based on the insights above..."></textarea></label>
        <input type="hidden" name="context_position_code" value="${html(contextPositionCode)}">
        <label class="form-field wide"><span>Owner Designation:</span><select class="action-owner-select" data-owner-designation><option value="">All designations</option></select></label>
        <div class="form-field wide action-owner-field"><span id="actionOwnerLabel" data-action-owner-label>Action Owner:</span>
          <input type="hidden" name="action_owner_position_code" value="">
          <div class="action-owner-picker" data-owner-picker>
            <button type="button" class="action-owner-toggle" data-owner-toggle aria-labelledby="actionOwnerLabel actionOwnerValue" aria-haspopup="listbox" aria-expanded="false"><span id="actionOwnerValue" data-owner-selected>Loading staff…</span><svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="10.8" cy="10.8" r="6.8"></circle><path d="m16 16 5 5"></path></svg></button>
            <div class="filter-picker-menu action-owner-menu" data-owner-menu hidden>
              <input class="filter-picker-search" type="search" data-owner-search placeholder="Search name or position code" aria-label="Search action owners" autocomplete="off">
              <div class="filter-picker-options" data-owner-options role="listbox" aria-labelledby="actionOwnerLabel"></div>
            </div>
          </div>
          <small class="action-owner-help">Choose a direct report for this dashboard position.</small>
        </div>
        <label class="form-field"><span>Timeline / Due Date:</span><input name="due_date" type="date"></label>
        <label class="form-field"><span>Priority:</span><select name="priority" class="action-priority-select" data-priority="Medium"><option value="High">High</option><option value="Medium" selected>Medium</option><option value="Low">Low</option></select></label>
        <div class="action-plan-submit wide"><button class="action-plan-send" type="submit">Save action plan &amp; send message</button><span class="action-plan-message" role="status"></span></div>
      </form>`;
      const form = actions.querySelector("[data-action-plan-form]");
      const priority = form?.querySelector("[name=priority]");
      priority?.addEventListener("change", () => { priority.dataset.priority = priority.value; });
      const recipientParams = new URLSearchParams();
      if (contextPositionCode) recipientParams.set("context_position_code", contextPositionCode);
      const recipientUrl = "/api/action-plan-recipients" + (recipientParams.size ? `?${recipientParams}` : "");
      getJSON(recipientUrl).then(({ recipients, recipient_label: recipientLabel }) => {
        if (!form?.isConnected) return;
        const owner = form?.querySelector("[name=action_owner_position_code]");
        const designation = form?.querySelector("[data-owner-designation]");
        const picker = form?.querySelector("[data-owner-picker]");
        const toggle = form?.querySelector("[data-owner-toggle]");
        const selectedLabel = form?.querySelector("[data-owner-selected]");
        const menu = form?.querySelector("[data-owner-menu]");
        const search = form?.querySelector("[data-owner-search]");
        const options = form?.querySelector("[data-owner-options]");
        const submit = form?.querySelector("[type=submit]");
        const label = form?.querySelector("[data-action-owner-label]");
        const help = form?.querySelector(".action-owner-help");
        if (!owner || !designation || !picker || !toggle || !selectedLabel || !menu || !search || !options) return;
        const labelText = recipientLabel || "reporting staff";
        if (label) label.textContent = `Action Owner (${labelText})`;
        if (help) help.textContent = labelText === "selected employee"
          ? "This position has no direct reports, so the action is assigned to the selected employee."
          : "Choose one direct report for this corrective action.";
        if (!recipients.length) {
          selectedLabel.textContent = `No ${labelText} employees available`;
          toggle.disabled = true;
          submit && (submit.disabled = true);
          return;
        }
        const designations = [...new Set(recipients.map(r => r.designation).filter(Boolean))].sort();
        designation.innerHTML = '<option value="">All designations</option>' + designations.map(value => `<option value="${html(value)}">${html(value)}</option>`).join("");
        if (recipients.length === 1) owner.value = recipients[0].position_code;
        const updateOwnerHelp = () => {
          const selected = recipients.find(r => r.position_code === owner.value);
          const availableCount = recipients.filter(r => !designation.value || r.designation === designation.value).length;
          selectedLabel.textContent = selected ? `${selected.employee_name} · ${selected.designation} · ${selected.position_code}` : `Select ${labelText} (${availableCount})`;
          toggle.title = selectedLabel.textContent;
          if (help) help.textContent = !selected ? `Choose ${labelText}.`
            : selected.user_id ? "An in-app message will be sent to this employee now."
            : "The in-app message will wait for an account assigned to this position code.";
        };
        const renderOwners = () => {
          const term = search.value.trim().toLocaleLowerCase();
          const eligible = recipients.filter(r => !designation.value || r.designation === designation.value);
          const matches = eligible.filter(r => !term || `${r.employee_name} ${r.position_code} ${r.designation}`.toLocaleLowerCase().includes(term));
          options.innerHTML = `<button type="button" class="filter-picker-option filter-picker-clear" data-owner-value="" role="option">Select ${html(labelText)} (${eligible.length})</button>` +
            (matches.length ? matches.map(r => `<button type="button" class="filter-picker-option" data-owner-value="${html(r.position_code)}" role="option" aria-selected="${r.position_code === owner.value}">${html(r.employee_name)} · ${html(r.designation)} · ${html(r.position_code)}</button>`).join("") : '<div class="filter-picker-empty">No matching employees</div>');
          updateOwnerHelp();
        };
        const closePicker = () => {
          if (menu.hidden) return;
          menu.hidden = true;
          toggle.setAttribute("aria-expanded", "false");
          picker.append(menu);
          document.removeEventListener("pointerdown", outsidePicker);
          document.removeEventListener("keydown", escapePicker);
          window.removeEventListener("scroll", scrollPicker, true);
          window.removeEventListener("resize", positionPicker);
        };
        const positionPicker = () => {
          const rect = toggle.getBoundingClientRect();
          const below = window.innerHeight - rect.bottom - 8;
          const above = rect.top - 8;
          const openAbove = below < 220 && above > below;
          const height = Math.min(320, Math.max(120, openAbove ? above : below));
          const width = Math.min(rect.width, window.innerWidth - 16);
          menu.style.width = `${width}px`;
          menu.style.height = `${height}px`;
          menu.style.left = `${Math.max(8, Math.min(rect.left, window.innerWidth - width - 8))}px`;
          menu.style.top = `${openAbove ? Math.max(8, rect.top - height - 4) : rect.bottom + 4}px`;
        };
        const outsidePicker = event => { if (!picker.contains(event.target) && !menu.contains(event.target)) closePicker(); };
        const escapePicker = event => { if (event.key === "Escape") { closePicker(); toggle.focus(); } };
        const scrollPicker = event => { if (!menu.contains(event.target)) closePicker(); };
        toggle.addEventListener("click", () => {
          if (!menu.hidden) { closePicker(); return; }
          search.value = "";
          renderOwners();
          document.body.append(menu);
          menu.hidden = false;
          positionPicker();
          toggle.setAttribute("aria-expanded", "true");
          document.addEventListener("pointerdown", outsidePicker);
          document.addEventListener("keydown", escapePicker);
          window.addEventListener("scroll", scrollPicker, true);
          window.addEventListener("resize", positionPicker);
          search.focus();
        });
        options.addEventListener("click", event => {
          const option = event.target.closest("[data-owner-value]");
          if (!option) return;
          owner.value = option.dataset.ownerValue;
          toggle.classList.remove("error");
          const message = form.querySelector(".action-plan-message");
          if (message) { message.textContent = ""; message.classList.remove("error"); }
          updateOwnerHelp();
          closePicker();
          toggle.focus();
        });
        designation.addEventListener("change", () => {
          if (owner.value && !recipients.some(r => r.position_code === owner.value && (!designation.value || r.designation === designation.value))) owner.value = "";
          search.value = "";
          renderOwners();
          closePicker();
        });
        search.addEventListener("input", renderOwners);
        closeActionOwnerPicker = closePicker;
        renderOwners();
      }).catch(error => {
        if (!form?.isConnected) return;
        const toggle = form?.querySelector("[data-owner-toggle]");
        const submit = form?.querySelector("[type=submit]");
        if (toggle) { toggle.querySelector("[data-owner-selected]").textContent = error.message; toggle.disabled = true; }
        submit && (submit.disabled = true);
      });
    }
  }

  function paintProductPanel(d) {
    const box = document.querySelector("[data-product-performance]");
    if (!box) return;
    const designation = getAppEl()?.dataset?.designation || "ALL";
    if (["spo", "mio"].includes(designation)) return;

    const heading = document.querySelector("#panel-4 .panel-ttl h2");
    const description = document.querySelector("#panel-4 .panel-ttl p");
    const mode = document.querySelector("#panel-4 .mini-select")?.value || "Top";
    const metricIsCount = ["units", "cyp"].includes(d.meta?.value_metric);
    const metricValue = n => metricIsCount ? fmt(Number(n || 0), 0) : rs(n);
    const metricLabel = d.meta?.value_metric_label || "NET SALE VALUE";
    const allRows = d.spo_sections?.product_performance || [];
    const byAchievement = (a, b) => (b.achievement_pct ?? -1) - (a.achievement_pct ?? -1);
    let rows = [...allRows].sort(byAchievement);
    rows = rows.filter(r => r.achievement_pct != null);
    if (String(mode).toLowerCase().startsWith("bottom")) rows = rows.sort((a, b) => a.achievement_pct - b.achievement_pct).slice(0, 25);
    else rows = rows.slice(0, 25);
    const achievementScale = Math.max(100, ...rows.map(row => Number(row.achievement_pct || 0)));

    if (heading) heading.textContent = `4. PRODUCT PERFORMANCE — ${metricLabel} ACHIEVEMENT`;
    if (description) description.textContent = `${metricLabel} achievement · Team: ${d.meta?.team_filter === "COMBINED" ? "Combined" : d.meta?.team_filter || "Combined"}`;
    box.innerHTML = rows.length ? rows.map(r => {
      const ach = r.achievement_pct;
      const level = ach == null ? "unknown" : ach < 50 ? "low" : ach < 80 ? "mid" : ach < 100 ? "near" : "good";
      const width = ach == null ? 0 : Math.min(100, Math.max(0, Number(ach) / achievementScale * 100));
      return `<div class="hbar-row product-ach-row"><div class="hbar-label wide"><b>${html(r.prd_name || "Unknown product")}</b><small>${html(r.product_no)} · ${metricLabel} ${metricValue(r.actual_net_sales)} / Target ${r.target_net_sales ? metricValue(r.target_net_sales) : "--"}</small></div><div class="hbar-track"><span class="product-ach-fill ${level}" style="width:${width}%"></span></div><div class="hbar-val product-ach-val ${level}">${ach == null ? "--" : pct(ach)}</div></div>`;
    }).join("") : `<div class="empty-state"><p>No product target or sales data for ${html(d.meta?.team_filter || "this team")} in the selected period.</p></div>`;
  }

  /* ------------------------- overview templates ------------------------- */
  const html = value => String(value ?? "").replace(/[&<>"']/g, c => ({"&":"&amp;", "<":"&lt;", ">":"&gt;", '"':"&quot;", "'":"&#39;"}[c]));
  const achievement = value => value == null ? "--" : pct(value);
  const achievementClass = value => value == null ? "" : value >= 100 ? " good" : value >= 80 ? " warn" : " bad";
  const panelBody = (n, content) => {
    const el = document.querySelector(`#panel-${n} .panel-body`);
    if (el) el.innerHTML = content;
  };
  const valueBar = (label, actual, target, ach, suffix = "") => {
    return `<div class="overview-row"><div class="overview-row-label" title="${html(label)}">${html(label)}${suffix ? `<small>${html(suffix)}</small>` : ""}</div><div class="overview-row-track"><i style="width:${Math.max(2, Math.min(100, Number(actual) / (Number(target) || Number(actual) || 1) * 100))}%"></i></div><b>${rs(actual)}</b><span class="overview-ach${achievementClass(ach)}">${achievement(ach)}</span></div>`;
  };
  const metricRows = metrics => `<div class="overview-metrics">${metrics.map(m => `<div class="overview-metric"><span>${html(m.label)}</span><b>${m.actual}</b><small>Target ${m.target} <em class="overview-ach${achievementClass(m.ach)}">${achievement(m.ach)}</em></small></div>`).join("")}</div>`;
  const simpleTable = (headers, rows) => `<div class="overview-table-wrap"><table class="overview-table"><thead><tr>${headers.map(h => `<th>${html(h)}</th>`).join("")}</tr></thead><tbody>${rows.length ? rows.map(row => `<tr>${row.map(cell => `<td>${cell}</td>`).join("")}</tr>`).join("") : `<tr><td colspan="${headers.length}" class="overview-empty">No data for the selected filters.</td></tr>`}</tbody></table></div>`;
  const sectionTitle = title => `<div class="overview-section-title">${html(title)}</div>`;
  const topBottomProducts = products => {
    const top = products.slice(0, 5), bottom = products.slice(-5).reverse();
    const list = (title, rows, tone) => `<div class="overview-list-card"><h4 class="${tone}">${html(title)}</h4>${rows.length ? rows.map(p => `<div class="overview-item"><span title="${html(p.name)}">${html(p.name)}</span><b>${achievement(p.achievement_pct)}</b><small>${rs(p.actual)}</small></div>`).join("") : `<p class="overview-empty">No product data.</p>`}</div>`;
    return `<div class="overview-dual">${list("Top products", top, "positive")}${list("Bottom products", bottom, "negative")}</div>`;
  };
  const insightContent = () => '<a class="ai-ranked-link" href="#aiInsights">View ranked findings and recommended actions in AI Performance Analysis ?</a>';


  function paintOverviewPanels(o, d) {
    const key = getAppEl()?.dataset?.designation || "ALL";
    const positions = o.positions || [], products = o.products || [], customers = o.customers || [], regions = o.regions || [], channels = o.channels || [];
    const metrics = [
      ["Gross TP", d.gross_tp], ["Net Sales", d.net_sales], ["Units", d.units],
      ["Net WO/Reg", d.net_wo_reg], ["CYP", d.cyp]
    ].map(([label, m]) => ({ label, actual: label === "Units" || label === "CYP" ? fmt(m?.actual || 0, 0) : rs(m?.actual || 0), target: label === "Units" || label === "CYP" ? fmt(m?.target || 0, 0) : rs(m?.target || 0), ach: m?.ach }));
    const positionsBars = positions.slice(0, 8).map(p => valueBar(p.name, p.actual, p.target, p.achievement_pct, `${p.designation || ""} ${p.territory || p.region || ""}`)).join("");
    const regionBars = regions.slice(0, 8).map(r => valueBar(r.region, r.actual, r.target, r.achievement_pct, `${r.zone} / ${r.subzone}`)).join("");
    const productBars = products.slice(0, 10).map(p => valueBar(p.name, p.actual, p.target, p.achievement_pct, p.product_no)).join("");
    const customerRows = customers.slice(0, 8).map((c, i) => [html(i + 1), html(c.name), rs(c.actual), fmt(c.units, 0)]);
    const regionRows = regions.slice(0, 8).map(r => [html(r.region), html(r.zone), html(r.subzone), rs(r.actual), rs(r.target), `<span class="overview-ach${achievementClass(r.achievement_pct)}">${achievement(r.achievement_pct)}</span>`]);
    const positionRows = positions.slice(0, 10).map((p, i) => [html(i + 1), html(p.name), html(p.designation), html(p.region || p.territory), rs(p.actual), rs(p.target), `<span class="overview-ach${achievementClass(p.achievement_pct)}">${achievement(p.achievement_pct)}</span>`]);
    const channelCards = channels.length ? `<div class="overview-channel-grid">${channels.slice(0, 6).map(c => `<div class="overview-channel"><b>${html(c.name)}</b><strong>${rs(c.actual)}</strong><small>${fmt(c.customers, 0)} active customers</small></div>`).join("")}</div>` : `<div class="overview-empty">No channel data for the selected period.</div>`;
    const discount = d.discount || {};
    const discountBox = `<div class="overview-discount"><div><span>Actual discount</span><b>${pct(discount.actual_pct)}</b></div><div><span>Budget</span><b>${pct(discount.budget_pct)}</b></div><div><span>Discount value</span><b>${rs(discount.actual || 0)}</b></div><div><span>Returns</span><b>${rs(d.returns?.value || 0)}</b></div></div>`;

    if (key === "executive" || key === "hod") {
      panelBody(1, sectionTitle("Regional net sales achievement") + `<div class="overview-list">${regionBars || `<div class="overview-empty">No region data.</div>`}</div>`);
      panelBody(2, sectionTitle("Selected-period actual vs target") + metricRows(metrics));
      panelBody(3, sectionTitle("Discount and exception summary") + discountBox + insightContent(o, d, "position"));
      panelBody(4, simpleTable(["Region", "Zone", "Sub Zone", "Actual", "Target", "Ach. %"], regionRows));
      panelBody(5, sectionTitle("Sales by channel") + channelCards);
      panelBody(6, topBottomProducts(products));
      panelBody(7, sectionTitle("Current month designation contribution") + simpleTable(["Employee", "Designation", "Area", "Actual", "Target", "Ach. %"], positionRows));
      panelBody(8, sectionTitle("Executive insights and actions") + insightContent(o, d, "employee"));
    } else if (key === "rsm") {
      panelBody(1, sectionTitle("Team member achievement") + `<div class="overview-list">${positionsBars || `<div class="overview-empty">No team data.</div>`}</div>`);
      panelBody(2, sectionTitle("Regional actual vs target") + metricRows(metrics));
      panelBody(3, sectionTitle("Discount, profitability and exceptions") + discountBox + insightContent(o, d, "team member"));
      panelBody(4, sectionTitle("Product achievement") + `<div class="overview-list">${productBars || `<div class="overview-empty">No product data.</div>`}</div>`);
      panelBody(5, simpleTable(["Region", "Zone", "Sub Zone", "Actual", "Target", "Ach. %"], regionRows));
      panelBody(6, simpleTable(["#", "Customer", "Net Sales", "Units"], customerRows));
      panelBody(7, sectionTitle(`Selected month: ${html(o.period)}`) + metricRows([{ label: "Net Sales", actual: rs(d.net_sales?.actual || 0), target: rs(d.net_sales?.target || 0), ach: d.net_sales?.ach }, { label: "Gross TP", actual: rs(d.gross_tp?.actual || 0), target: rs(d.gross_tp?.target || 0), ach: d.gross_tp?.ach }]));
      panelBody(8, sectionTitle("Required corrective actions") + insightContent(o, d, "team member"));
    } else if (key === "asm") {
      const mio = positions.filter(p => p.designation === "MIO"), spo = positions.filter(p => p.designation === "SPO");
      panelBody(1, `<div class="overview-dual"><div class="overview-list-card"><h4 class="positive">MIO team</h4>${mio.slice(0, 6).map(p => `<div class="overview-item"><span>${html(p.name)}</span><b>${achievement(p.achievement_pct)}</b><small>${rs(p.actual)}</small></div>`).join("") || `<p class="overview-empty">No MIO data.</p>`}</div><div class="overview-list-card"><h4 class="positive">SPO team</h4>${spo.slice(0, 6).map(p => `<div class="overview-item"><span>${html(p.name)}</span><b>${achievement(p.achievement_pct)}</b><small>${rs(p.actual)}</small></div>`).join("") || `<p class="overview-empty">No SPO data.</p>`}</div></div>`);
      panelBody(2, sectionTitle("Area actual vs target") + metricRows(metrics));
      panelBody(3, sectionTitle("Discount and exceptions") + discountBox + insightContent(o, d, "team member"));
      panelBody(4, sectionTitle("Product achievement") + `<div class="overview-list">${productBars || `<div class="overview-empty">No product data.</div>`}</div>`);
      panelBody(5, simpleTable(["#", "Employee", "Designation", "Area", "Actual", "Target", "Ach. %"], positionRows));
      panelBody(6, sectionTitle("Insights and required actions") + insightContent(o, d, "team member"));
      panelBody(7, sectionTitle("ASM corrective action plan") + insightContent(o, d, "team member") + `<div class="form-grid"><label class="form-field wide"><span>ASM / Area Comments:</span><textarea rows="3" placeholder="Add corrective actions and follow-up notes..."></textarea></label><label class="form-field"><span>Action Owner:</span><input type="text"></label><label class="form-field"><span>Timeline:</span><input type="text"></label></div>`);
    }
  }

  function clearKpis() {
    document.querySelectorAll("#kpiRow .kpi").forEach(c => c.classList.add("loading"));
  }

  const unavailablePanelBodies = new Map();
  function hasDataFilter() {
    // Each API scope parameter is independently optional. Partial selections
    // (such as team only, region only, or designation + zone) are valid filters.
    return Boolean($(ids.month)?.value && $(ids.fy)?.value);
  }

  function showSelectionRequired() {
    latestData = null;
    $("dashboard")?.classList.add("dashboard-selection-required");
    document.querySelectorAll("#kpiRow .kpi").forEach(card => {
      card.classList.remove("loading");
      card.querySelector(".kpi-val").textContent = "--";
      const data = card.querySelector(".kpi-data");
      if (data) { data.hidden = true; data.textContent = ""; }
    });
    document.querySelectorAll("#panelGrid .panel-body").forEach(body => {
      if (!unavailablePanelBodies.has(body)) unavailablePanelBodies.set(body, body.innerHTML);
      body.innerHTML = `<div class="empty-state selection-required"><p>Complete all filters to view scoped data, or clear them to view all data.</p></div>`;
    });
    status(null);
  }

  function restoreDashboardPanels() {
    $("dashboard")?.classList.remove("dashboard-selection-required");
    unavailablePanelBodies.forEach((markup, body) => {
      if (body.isConnected) body.innerHTML = markup;
    });
    unavailablePanelBodies.clear();
  }

  function setDataLoader(visible) {
    const loader = $("dataLoader");
    if (loader) loader.hidden = !visible;
  }

  /* ------------------------------ refresh ------------------------------ */
  let seq = 0;
  let latestData = null;
  async function refresh({ reloadFilters = false } = {}) {
    const my = ++seq;
    const refreshStarted = performance.now();
    try {
      await metaReady;
      if (!hasDataFilter()) {
        showSelectionRequired();
        return;
      }
      restoreDashboardPanels();
      setDataLoader(true);
      const desig = $("fDesignation").value || "ALL";
      if (!$("fDesignation").value && desig !== "ALL") $("fDesignation").value = desig;
      const team = $("fTeam")?.value || "COMBINED";
      const hasTerritoryScope = activeTerritoryScope &&
        userSelections.territory === activeTerritoryScope.territory;
      if (!hasTerritoryScope && (reloadFilters || currentDesignation !== desig + "|" + team)) {
        currentDesignation = desig + "|" + team;
        await loadFilters(desig, team);
      } else if (hasTerritoryScope) {
        currentDesignation = desig + "|" + team;
      }
      clearKpis();
      const params = qs(current());
      const requestStarted = performance.now();
      const d = await getJSON("/api/kpis?" + params);
      if (my !== seq) return;               // a newer request superseded this one
      const renderStarted = performance.now();
      paintKpis(d);
      syncFiltersToResponse(d.meta);
      updateDashboardHeader(d.meta);
      latestData = d;
      window.dashboardPerformance = {
        endpoint: "/api/kpis",
        request_ms: Math.round((renderStarted - requestStarted) * 10) / 10,
        render_ms: Math.round((performance.now() - renderStarted) * 10) / 10,
        total_ms: Math.round((performance.now() - refreshStarted) * 10) / 10
      };
      document.dispatchEvent(new CustomEvent("dashboard:data-loaded", { detail: d.meta }));
      status(d.meta.targets_available ? null : "No targets are loaded for this fiscal year, so achievement % is unavailable.");
    } catch (e) {
      status("Could not load data from the server (" + e.message + "). Start it with: python scripts/server.py and open http://localhost:8000");
    } finally {
      if (my === seq) {
        document.querySelectorAll("#kpiRow .kpi").forEach(c => c.classList.remove("loading"));
        setDataLoader(false);
      }
    }
  }

  /* ------------------------------ events ------------------------------ */
  document.addEventListener("dashboard:rendered", () => {
    unavailablePanelBodies.clear();
    refresh({ reloadFilters: true });
  });
  $("resetDashboard")?.addEventListener("click", () => {
    const button = $("resetDashboard");
    button.disabled = true;
    Promise.resolve(resetDashboardView()).finally(() => { button.disabled = false; });
  });
  $("valueToggle")?.addEventListener("click", event => {
    const button = event.target.closest("[data-value-metric]");
    if (!button || button.dataset.valueMetric === valueMetric) return;
    valueMetric = button.dataset.valueMetric;
    $("valueToggle").querySelectorAll("[data-value-metric]").forEach(item => {
      item.setAttribute("aria-pressed", String(item === button));
    });
    document.dispatchEvent(new Event("dashboard:metric-changed"));
    refresh({ reloadFilters: false });
  });

  const filterKeyMap = { fName: "employee", fZone: "zone", fSubZone: "subzone", fRegion: "region", fTerritory: "territory" };
  [ids.employee, ids.region, ids.zone, ids.subzone, ids.territory].forEach(id => {
    const el = $(id);
    if (!el) return;
    el.addEventListener("change", async e => {
      const field = filterKeyMap[id];
      if (field) {
        if (field === "employee") {
          const record = await applyEmployeeSelection(e.target.value);
          const selectedNode = hierarchyNode(record);
          hierarchyDrilldownTrail = selectedNode && !sameHierarchyNode(selectedNode, scopedHierarchyRoot)
            ? [selectedNode]
            : [];
          renderHierarchyBreadcrumb();
          return;
        }
        if (field === "territory") {
          await applyTerritorySelection(e.target.value);
          return;
        }
        await applyCascadingFilters(field, e.target.value);
        updateDashboardHeader();
        refresh({ reloadFilters: false });
      }
    });
  });
  $("fDesignation")?.addEventListener("change", () => {
    employeeScopeRequestId += 1;
    employeeScopeSnapshot = null;
    activeEmployeeRecord = null;
    hierarchyDrilldownTrail = [];
    renderHierarchyBreadcrumb();
    if (lastHeaderMeta) lastHeaderMeta.employee = "";
    updateDashboardHeader();
  });
  [ids.month, ids.fy].forEach(i => $(i)?.addEventListener("change", () => {
    updateDashboardHeader();
    refresh({ reloadFilters: false });
  }));
  async function handleTeamChange(team) {
    employeeScopeRequestId += 1;
    employeeScopeSnapshot = null;
    activeEmployeeRecord = null;
    hierarchyDrilldownTrail = [];
    renderHierarchyBreadcrumb();
    if (lastHeaderMeta) {
      lastHeaderMeta.employee = "";
      lastHeaderMeta.position_code = "";
      lastHeaderMeta.dept_territory_code = "";
    }
    // Reflect the selected team before metadata and KPI requests complete.
    updateDashboardHeader();
    const previousDesignation = $("fDesignation").value || "ALL";
    await loadMeta(team || "COMBINED");
    const designationStillAvailable = previousDesignation === "ALL" || Array.from($("fDesignation").options).some(option => option.value === previousDesignation);
    if (!designationStillAvailable) {
      window.setDashboardDesignation?.("ALL");
      return;
    }
    refresh({ reloadFilters: false });
  }
  $("fTeam")?.addEventListener("change", () => handleTeamChange($("fTeam").value || "COMBINED"));
  $("teamToggle")?.addEventListener("click", event => {
    const button = event.target.closest("[data-team]");
    if (!button) return;
    const team = button.dataset.team;
    $("fTeam").value = team;
    $("teamToggle").querySelectorAll("[data-team]").forEach(item => {
      item.setAttribute("aria-pressed", String(item === button));
    });
    handleTeamChange(team);
  });
  $("periodToggle")?.addEventListener("click", event => {
    const button = event.target.closest("[data-period]");
    if (!button || button.dataset.period === periodMode) return;
    periodMode = button.dataset.period;
    $("periodToggle").querySelectorAll("[data-period]").forEach(item => {
      item.setAttribute("aria-pressed", String(item === button));
    });
    refresh({ reloadFilters: false });
  });
  // Apply the current filter state without re-rendering the dashboard when its
  // designation has not changed. Re-rendering here races the request with a
  // second dashboard:rendered refresh and can replace filter-dependent panels.
  document.addEventListener("filters:apply", () => refresh({ reloadFilters: false }));
  const employeePicker = $("employeePickerMenu");
  const employeePickerToggle = $("employeePickerToggle");
  const employeeSearch = $("fNameSearch");
  employeePickerToggle?.addEventListener("click", async () => {
    const opening = employeePicker.hidden;
    employeePicker.hidden = !opening;
    employeePickerToggle.setAttribute("aria-expanded", String(opening));
    if (opening) {
      // Keep manually chosen geography, but release geography that was filled
      // from the previous employee so the full employee list is available.
      autoFilledSelections.forEach(field => {
        if (field !== "employee") userSelections[field] = "All";
      });
      autoFilledSelections.delete("region");
      autoFilledSelections.delete("zone");
      autoFilledSelections.delete("subzone");
      autoFilledSelections.delete("territory");
      const previous = employeeScopeSnapshot;
      if (previous) {
        employeeScopeSnapshot = null;
        $("fTeam").value = previous.team;
        await loadMeta(previous.team);
        setDesignationValue(previous.designation);
        window.setDashboardDesignation?.(previous.designation || "ALL");
      }
      employeeSearch.value = "";
      renderEmployeeOptions("");
      employeeSearch.focus();
    }
  });
  employeeSearch?.addEventListener("input", e => renderEmployeeOptions(e.target.value).catch(error => status("Could not search employees: " + error.message)));
  $("employeePickerOptions")?.addEventListener("click", event => {
    const option = event.target.closest("[data-employee-value]");
    if (!option) return;
    const select = $(ids.employee);
    if (!Array.from(select.options).some(item => item.value === option.dataset.employeeValue)) {
      select.add(new Option(option.dataset.employeeValue, option.dataset.employeeValue));
    }
    select.value = option.dataset.employeeValue;
    employeePicker.hidden = true;
    employeePickerToggle.setAttribute("aria-expanded", "false");
    select.dispatchEvent(new Event("change", { bubbles: true }));
  });
  document.addEventListener("click", event => {
    if (employeePicker && !event.target.closest(".employee-filter")) {
      employeePicker.hidden = true;
      employeePickerToggle?.setAttribute("aria-expanded", "false");
    }
  });
  employeeSearch?.addEventListener("keydown", event => {
    if (event.key === "Escape") {
      employeePicker.hidden = true;
      employeePickerToggle?.setAttribute("aria-expanded", "false");
      employeePickerToggle?.focus();
    }
  });
  const closeFilterPickers = except => {
    document.querySelectorAll("[data-picker-menu]").forEach(menu => {
      const field = menu.dataset.pickerMenu;
      if (field === except) return;
      menu.hidden = true;
      document.querySelector(`[data-picker-toggle="${field}"]`)?.setAttribute("aria-expanded", "false");
    });
  };
  document.querySelectorAll("[data-picker-toggle]").forEach(trigger => {
    trigger.addEventListener("click", () => {
      const field = trigger.dataset.pickerToggle;
      const menu = document.querySelector(`[data-picker-menu="${field}"]`);
      const search = document.querySelector(`[data-picker-search="${field}"]`);
      if (!menu || !search) return;
      const opening = menu.hidden;
      closeFilterPickers(opening ? field : "");
      menu.hidden = !opening;
      trigger.setAttribute("aria-expanded", String(opening));
      if (opening) {
        search.value = "";
        renderFilterPicker(field);
        search.focus();
      }
    });
  });
  document.querySelectorAll("[data-picker-search]").forEach(search => {
    search.addEventListener("input", event => {
      const field = event.target.dataset.pickerSearch;
      if (field === "designation") {
        renderFilterPicker(field, event.target.value);
        return;
      }
      renderDropdowns(field, event.target.value)
        .catch(error => status("Could not search staff filters: " + error.message));
    });
    search.addEventListener("keydown", event => {
      if (event.key !== "Escape") return;
      const field = event.target.dataset.pickerSearch;
      const menu = document.querySelector(`[data-picker-menu="${field}"]`);
      const trigger = document.querySelector(`[data-picker-toggle="${field}"]`);
      if (menu) menu.hidden = true;
      trigger?.setAttribute("aria-expanded", "false");
      trigger?.focus();
    });
  });
  document.querySelectorAll("[data-picker-options]").forEach(list => {
    list.addEventListener("click", event => {
      const option = event.target.closest("[data-filter-picker-value]");
      if (!option) return;
      const field = list.dataset.pickerOptions;
      const config = filterPickerConfig[field];
      const select = config && $(config.id);
      if (!select) return;
      select.value = option.dataset.filterPickerValue;
      document.querySelector(`[data-picker-menu="${field}"]`).hidden = true;
      document.querySelector(`[data-picker-toggle="${field}"]`)?.setAttribute("aria-expanded", "false");
      renderFilterPicker(field);
      select.dispatchEvent(new Event("change", { bubbles: true }));
    });
  });
  document.addEventListener("click", event => {
    if (!event.target.closest(".picker-filter")) closeFilterPickers("");
  });
  document.addEventListener("change", e => {
    if (latestData && e.target.matches(".mini-select")) {
      paintSpoPanels(latestData);
      paintProductPanel(latestData);
    }
  });
  document.addEventListener("click", e => {
    const drilldown = e.target.closest("[data-hierarchy-drilldown]");
    if (drilldown) {
      drillIntoHierarchy({
        employee: drilldown.dataset.employee || "",
        positionCode: drilldown.dataset.positionCode || ""
      });
      return;
    }
    const breadcrumb = e.target.closest("[data-hierarchy-breadcrumb-index]");
    if (breadcrumb) {
      navigateHierarchyBreadcrumb(
        Number(breadcrumb.dataset.hierarchyBreadcrumbIndex),
        breadcrumb.dataset.hierarchyBreadcrumbRoot === "true"
      );
      return;
    }
    const button = e.target.closest("[data-discount-toggle]");
    if (!button) return;
    const breakdown = button.parentElement.querySelector("[data-discount-breakdown]");
    const donut = button.parentElement.querySelector(".discount-donut-wrap");
    const showing = !breakdown.hidden;
    breakdown.hidden = showing;
    donut.hidden = !showing;
    button.textContent = showing ? "View Value Breakdown" : "View Discount Chart";
  });


  function syncFiltersToResponse(meta) {
    if (!meta) return;
    const fields = {
      employee: "fName", region: "fRegion", zone: "fZone",
      subzone: "fSubZone", territory: "fTerritory"
    };
    Object.entries(fields).forEach(([key, id]) => {
      const value = meta[key];
      if (!value || value === "All") return;
      userSelections[key] = value;
      effectiveSelections[key] = value;
      const control = $(id);
      if (!control) return;
      if (!Array.from(control.options).some(option => option.value === value)) {
        control.add(new Option(value, value));
      }
      control.value = value;
      if (key === "employee" && $("employeePickerToggle")) $("employeePickerToggle").textContent = value;
    });
    if ($("fTeam") && meta.team_filter) $("fTeam").value = meta.team_filter;
    if (meta.period) {
      periodMode = String(meta.period).toUpperCase();
      $("periodToggle")?.querySelectorAll("[data-period]").forEach(item => {
        item.setAttribute("aria-pressed", String(item.dataset.period === periodMode));
      });
    }
    if (meta.team_filter) {
      $("teamToggle")?.querySelectorAll("[data-team]").forEach(item => {
        item.setAttribute("aria-pressed", String(item.dataset.team === meta.team_filter));
      });
    }
  }

  function formatFullMonth(monthStr, fyStr) {
    if (!monthStr || monthStr === "All" || monthStr === "ALL") return "";
    const monthMap = {
      jan: "January", feb: "February", mar: "March", apr: "April",
      may: "May", jun: "June", jul: "July", aug: "August",
      sep: "September", oct: "October", nov: "November", dec: "December"
    };
    const m = String(monthStr).trim();
    const match = m.match(/^([A-Za-z]{3,9})[- /]?(\d{2,4})?$/);
    if (match) {
      const rawMon = match[1].toLowerCase().slice(0, 3);
      const fullMon = monthMap[rawMon] || match[1];
      let year = match[2];
      if (!year && fyStr) {
        const fyMatch = String(fyStr).match(/(\d{4})/);
        if (fyMatch) year = fyMatch[1];
      }
      if (year && year.length === 2) year = "20" + year;
      return year ? `${fullMon} ${year}` : fullMon;
    }
    return m;
  }

  function normalizeTeamLabel(team) {
    const value = String(team || "").trim().toUpperCase();
    if (value.includes("FMCG") || value.includes("FAST MOVING")) return "FMCG";
    if (value.includes("PHAR") || value === "PHR") return "PHARMA";
    return "";
  }

  function extractTerritoryCode(meta, record) {
    const code = (meta && (meta.dept_territory_code || meta.position_code || meta.territory)) ||
                 (record && (record.territory || record.position_code || record.dept_territory_code)) ||
                 effectiveSelections.territory ||
                 $("fTerritory")?.value || "";
    if (!code || code === "All" || code === "ALL") return "";
    return code;
  }

  function extractRegion(meta, record) {
    const reg = (meta && (meta.header_region || meta.region)) ||
                (record && record.region) ||
                effectiveSelections.region ||
                $("fRegion")?.value || "";
    if (!reg || reg === "All" || reg === "ALL") return "";
    return String(reg).trim();
  }

  function extractZone(meta, record) {
    const zone = (meta && (meta.header_zone || meta.zone)) ||
                 (record && record.zone) ||
                 effectiveSelections.zone ||
                 $("fZone")?.value || "";
    if (!zone || zone === "All" || zone === "ALL") return "";
    return zone;
  }

  function extractMonth(meta) {
    const month = (meta && meta.month) || $(ids.month)?.value || "";
    const fy = (meta && meta.fy) || $(ids.fy)?.value || "";
    return formatFullMonth(month, fy);
  }

  function updateDashboardHeader(meta = {}) {
    if (meta && typeof meta === "object") {
      lastHeaderMeta = Object.assign({}, lastHeaderMeta, meta);
    }
    const currentMeta = lastHeaderMeta || {};

    const selectedEmployee = (currentMeta.employee && currentMeta.employee !== "All")
      ? currentMeta.employee
      : (effectiveSelections.employee !== "All" ? effectiveSelections.employee : ($("fName")?.value !== "All" ? $("fName")?.value : ""));
    const employeeName = selectedEmployee ? String(selectedEmployee).trim() : "";

    // The explicit team toggle is authoritative. `meta.team` describes the
    // selected employee's source team and can be FMCG even while Combined is
    // selected, which must not change the dashboard title.
    const rawTeam = currentMeta.team_filter || $("fTeam")?.value || currentMeta.team || (activeEmployeeRecord && activeEmployeeRecord.team_filter) || "COMBINED";
    const teamDisplay = normalizeTeamLabel(rawTeam);

    const rawDesig = (currentMeta.designation || activeEmployeeRecord?.designation || $("fDesignation")?.value || "").toUpperCase();
    const designationDisplay = (rawDesig && rawDesig !== "ALL") ? rawDesig : "";

    // Line 1 always identifies the dashboard by designation. Employee names
    // stay in the filter and scope context instead of replacing the view name.
    let line1 = "";
    if (designationDisplay) {
      line1 = `${designationDisplay} Dashboard${teamDisplay ? ` - ${teamDisplay}` : ""}`;
    } else {
      line1 = teamDisplay ? `${teamDisplay} EXECUTIVE DASHBOARD` : "EXECUTIVE DASHBOARD";
    }

    // Line 2: [Employee] | [Territory Code] | [Region] | [Zone] | [Selected Month]
    const territoryCode = extractTerritoryCode(currentMeta, activeEmployeeRecord);
    const regionName = extractRegion(currentMeta, activeEmployeeRecord);
    const zoneName = extractZone(currentMeta, activeEmployeeRecord);
    const formattedMonth = extractMonth(currentMeta);

    const line2Parts = [];
    if (employeeName) line2Parts.push(employeeName);
    if (territoryCode) line2Parts.push(territoryCode);
    if (regionName) line2Parts.push(regionName);
    if (zoneName) line2Parts.push(zoneName);
    if (!employeeName && !territoryCode && !regionName && !zoneName) {
      line2Parts.push("National Scope");
    }
    if (formattedMonth) line2Parts.push(formattedMonth);

    const line2 = line2Parts.join(" | ");

    const titleElement = $("dashTitle");
    if (titleElement) titleElement.textContent = line1;

    const subtitleElement = $("dashSubtitle");
    if (subtitleElement) {
      subtitleElement.textContent = line2;
      subtitleElement.hidden = !line2;
    }

    if (line1) {
      document.title = `${line1} | Executive Sales Dashboard`;
    }
    renderHierarchyBreadcrumb();
  }
  document.addEventListener("submit", async event => {
    const form = event.target.closest("[data-action-plan-form]");
    if (!form) return;
    event.preventDefault();
    const button = form.querySelector("[type=submit]"), message = form.querySelector(".action-plan-message");
    const values = Object.fromEntries(new FormData(form).entries());
    values.due_date = values.due_date || null;
    values.status = "Open";
    if (!values.action_owner_position_code) {
      message.textContent = "Select an action owner.";
      message.classList.add("error");
      const toggle = form.querySelector("[data-owner-toggle]");
      toggle?.classList.add("error");
      toggle?.focus();
      return;
    }
    button.disabled = true; button.textContent = "Saving…"; message.textContent = ""; message.classList.remove("error");
    try {
      const response = await fetch("/api/action-plans", { method: "POST", credentials: "same-origin", headers: { "Content-Type": "application/json" }, body: JSON.stringify(values) });
      const result = await response.json();
      if (!response.ok) throw new Error(result.detail || "Could not save action plan");
      form.reset();
      form.querySelector("[name=priority]")?.dispatchEvent(new Event("change"));
      form.querySelector("[data-owner-designation]")?.dispatchEvent(new Event("change"));
      message.textContent = result.queued ? "Action saved. Message queued for this position's dashboard inbox." : "Action saved and in-app message sent.";
    } catch (error) {
      message.textContent = error.message; message.classList.add("error");
    } finally { button.disabled = false; button.textContent = "Save action plan & send message"; }
  });
  window.updateDashboardHeader = updateDashboardHeader;
})();
