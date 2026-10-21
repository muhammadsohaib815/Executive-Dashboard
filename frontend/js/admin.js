(function () {
  const $ = id => document.getElementById(id);
  const message = (text, error = false) => {
    const el = $("adminMessage");
    if (!el) return;
    el.textContent = text || ""; el.hidden = !text; el.classList.toggle("error", error);
  };
  const readError = async response => {
    try { const body = await response.json(); return body.detail || "Request failed"; }
    catch (_) { return `Request failed (${response.status})`; }
  };
  const request = async (url, options = {}) => {
    const response = await fetch(url, { credentials: "same-origin", ...options });
    if (!response.ok) throw new Error(await readError(response));
    return response.json();
  };
  const formData = form => Object.fromEntries(new FormData(form).entries());
  const formatDate = value => value ? new Date(value).toLocaleString() : "Never";
  let staffRows = [];
  const accountRoles = [
    ["viewer", "Viewer"], ["executive", "Executive"], ["manager", "Manager"],
    ["HOD", "HOD"], ["DGM", "DGM"], ["RSM", "RSM"], ["ASM", "ASM"],
    ["SPO", "SPO"], ["MIO", "MIO"], ["IO", "IO"], ["PS", "PS"], ["SB", "SB"],
    ["ASMTE", "ASMTE"], ["CM", "CM"], ["SPOWS", "SPOWS"], ["TE", "TE"], ["EXEC", "EXEC"],
  ];
  const rolePickerMarkup = (_userId, selected) => {
    const value = String(selected || "viewer").trim();
    const entry = accountRoles.find(([role]) => role.toUpperCase() === value.toUpperCase());
    const label = entry ? entry[1] : value;
    const className = value.toLowerCase().replace(/[^a-z0-9]+/g, "-");
    return `<strong class="user-role-label role-${className}" title="Role is fixed by the assigned position">${escapeHtml(label)}</strong>`;
  };
  const positionMap = () => new Map(staffRows.map(row => [row.position_code, row]));
  function syncRoleToPosition(picker) {
    if (!picker) return;
    const roleControl = picker.id === "newUserScopePicker"
      ? document.querySelector('#userForm select[name="role"]')
      : picker.closest("tr")?.querySelector("[data-user-role]");
    if (!roleControl) return;
    const position = picker.querySelector("[data-scope-position]");
    const row = position?.value ? positionMap().get(position.value) : null;
    const designation = String(row?.designation || "").trim().toUpperCase();
    if (designation) {
      roleControl.value = designation;
      roleControl.disabled = picker.id !== "newUserScopePicker";
      roleControl.title = "Role is fixed by the assigned position";
    } else if (picker.id === "newUserScopePicker") {
      roleControl.disabled = false;
      roleControl.title = "Select a position to derive the hierarchy role";
    }
  }
  const choiceLabel = row => `${row.designation || "Staff"} · ${row.employee || "Unnamed"} · ${row.position_code}${row.reports_to ? ` · reports to ${row.reports_to}` : ""}${row.region ? ` · ${row.region}` : ""}${row.zone ? ` / ${row.zone}` : ""}`;
  function descendants(positionCode) {
    if (!positionCode) return [];
    const found = new Set([positionCode]), pending = [positionCode];
    while (pending.length) {
      const parent = pending.pop();
      staffRows.forEach(row => {
        if (String(row.reports_to || "").trim() === String(parent).trim() && !found.has(row.position_code)) { found.add(row.position_code); pending.push(row.position_code); }
      });
    }
    return [...found].map(code => positionMap().get(code)).filter(Boolean);
  }
  const uniqueRows = rows => {
    const seen = new Set();
    return rows.filter(row => row.position_code && !seen.has(row.position_code) && seen.add(row.position_code));
  };
  const designationOptions = rows => [...new Set(rows.map(row => String(row.designation || "").trim()).filter(Boolean))].sort();
  function scopeRows(picker) {
    const designation = picker.querySelector("[data-scope-designation]")?.value || "";
    return staffRows.filter(row => !designation || row.designation === designation);
  }
  function fillOptions(select, values, placeholder, selected = "") {
    select.innerHTML = `<option value="">${escapeHtml(placeholder)}</option>` + values.map(value => `<option value="${escapeHtml(value)}"${value === selected ? " selected" : ""}>${escapeHtml(value)}</option>`).join("");
    select.disabled = !values.length;
  }
  function updateScopePicker(picker, selectedPosition = "") {
    const desig = picker.querySelector("[data-scope-designation]");
    const position = picker.querySelector("[data-scope-position]");
    const search = picker.querySelector("[data-scope-position-search]")?.value.trim().toLowerCase() || "";
    selectedPosition = selectedPosition || position?.dataset.selectedScope || "";
    const selectedRow = selectedPosition ? positionMap().get(selectedPosition) : null;
    if (selectedRow && desig) desig.value = selectedRow.designation || "";
    if (desig && desig.options.length <= 1) fillOptions(desig, designationOptions(staffRows), "All designations", desig.value);
    const rows = scopeRows(picker);
    const positions = uniqueRows(rows).filter(row => !search || String(row.position_code).toLowerCase().includes(search)).sort((a, b) => String(a.position_code).localeCompare(String(b.position_code)));
    if (position) {
      position.innerHTML = `<option value="">${positions.length ? "Select position code" : "No matching positions"}</option>` + positions.map(row => `<option value="${escapeHtml(row.position_code)}"${row.position_code === selectedPosition ? " selected" : ""}>${escapeHtml(row.position_code)} · ${escapeHtml(row.employee || "Unnamed")} · ${escapeHtml(row.designation || "Staff")}</option>`).join("");
      position.disabled = !positions.length;
      if (selectedPosition && positions.some(row => row.position_code === selectedPosition)) position.value = selectedPosition;
      position.dataset.selectedScope = position.value || "";
    }
    renderScopePreview(position, picker.dataset.previewTarget || "newUserScopePreview");
    syncRoleToPosition(picker);
  }
  function scopePickerMarkup(userId = "", selected = "") {
    const suffix = userId ? `-${userId}` : "";
    return `<div class="scope-picker scope-picker-compact" data-scope-picker="${escapeHtml(userId)}" data-preview-target="scopePreview${suffix}">
      <div class="scope-filter-row"><label>Designation<select data-scope-designation><option value="">All designations</option></select></label><label>Position code<input type="search" data-scope-position-search placeholder="Search position code…" autocomplete="off"><select data-scope-position data-selected-scope="${escapeHtml(selected)}"${selected ? "" : " disabled"}><option value="">Select a position code</option></select></label></div>
    </div><small class="scope-row-preview" id="scopePreview${suffix}"></small>`;
  }
  // Searchable position-code dropdown used by both new-user and existing-user access controls.
  function updateScopePicker(picker, selectedPosition = "") {
    const desig = picker.querySelector("[data-scope-designation]");
    const position = picker.querySelector("[data-scope-position]");
    const searchInput = picker.querySelector("[data-scope-position-search]");
    const menu = picker.querySelector("[data-scope-position-menu]");
    const openMenu = picker.dataset.openPositionMenu === "true";
    const search = searchInput?.value.trim().toLowerCase() || "";
    selectedPosition = selectedPosition || position?.value || position?.dataset.selectedScope || "";
    const selectedRow = selectedPosition ? positionMap().get(selectedPosition) : null;
    if (selectedRow && desig) desig.value = selectedRow.designation || "";
    if (desig && desig.options.length <= 1) fillOptions(desig, designationOptions(staffRows), "All designations", desig.value);
    const designation = desig?.value || "";
    const positions = uniqueRows(staffRows).filter(row => (!designation || row.designation === designation) && (!search || String(row.position_code).toLowerCase().includes(search))).sort((a, b) => String(a.position_code).localeCompare(String(b.position_code)));
    if (position) {
      position.disabled = !positions.length;
      if (selectedPosition && positions.some(row => row.position_code === selectedPosition)) position.value = selectedPosition;
      position.dataset.selectedScope = position.value || "";
    }
    if (menu) {
      menu.innerHTML = positions.length ? positions.map(row => `<button type="button" class="scope-position-option${row.position_code === selectedPosition ? " is-selected" : ""}" data-position-value="${escapeHtml(row.position_code)}"><b>${escapeHtml(row.position_code)}</b><span>${escapeHtml(row.employee || "Unnamed")} · ${escapeHtml(row.designation || "Staff")}</span></button>`).join("") : `<div class="scope-position-empty">No matching position codes</div>`;
      menu.hidden = !openMenu || !positions.length;
    }
    renderScopePreview(position, picker.dataset.previewTarget || "newUserScopePreview");
    syncRoleToPosition(picker);
  }
  function scopePickerMarkup(userId = "", selected = "") {
    const suffix = userId ? `-${userId}` : "";
    return `<div class="scope-picker scope-picker-compact" data-scope-picker="${escapeHtml(userId)}" data-preview-target="scopePreview${suffix}">
      <div class="scope-filter-row"><label>Designation<select data-scope-designation><option value="">All designations</option></select></label><label>Position code<div class="scope-search-box"><input type="search" data-scope-position-search placeholder="Search position code…" autocomplete="off"><input type="hidden" data-scope-position data-selected-scope="${escapeHtml(selected)}" value="${escapeHtml(selected)}"><div class="scope-position-menu" data-scope-position-menu hidden></div></div></label></div>
    </div><small class="scope-row-preview" id="scopePreview${suffix}"></small>`;
  }
  function renderScopePreview(select, target) {
    const position = select?.value, box = $(target);
    if (!box) return;
    const row = positionMap().get(position), tree = descendants(position);
    box.hidden = !row;
    if (!row) { box.innerHTML = ""; return; }
    const children = tree.filter(person => person.position_code !== position && ["ASM", "MIO", "SPO"].includes(String(person.designation || "").trim().toUpperCase()));
    const asm = children.filter(person => String(person.designation || "").trim().toUpperCase() === "ASM");
    box.innerHTML = `<b>${escapeHtml(choiceLabel(row))}</b><span>Dashboard visibility: ${tree.length} staff position(s), including this position.</span><details><summary>View ASM / MIO / SPO below this position (${children.length})</summary><span>${children.length ? children.map(person => `${person.designation || "Staff"}: ${person.employee || "Unnamed"} (${person.position_code})`).map(escapeHtml).join(" · ") : "No ASM, MIO or SPO reports found below this position."}</span></details>`;
  }

  async function loadStaff() {
    const { staff } = await request("/api/admin/staff");
    staffRows = staff;
    document.querySelectorAll("[data-scope-picker]").forEach(picker => updateScopePicker(picker));
  }

  async function loadUsers() {
    const body = $("usersBody");
    try {
      const { users } = await request("/api/admin/users");
      body.innerHTML = users.map(user => `<tr>
        <td>${escapeHtml(user.full_name)}</td><td>${escapeHtml(user.username)}</td>
        <td>${user.role === "admin" ? "Admin" : rolePickerMarkup(user.id, user.role)}</td>
        <td>${user.role === "admin" ? "All dashboard data" : `${scopePickerMarkup(user.id, user.scope_position_code || "")}<button class="row-action scope-save" type="button" data-save-scope="${user.id}">Save access</button>`}</td>
        <td class="${user.is_active ? "status-active" : "status-inactive"}">${user.is_active ? "Active" : "Inactive"}</td>
        <td>${escapeHtml(formatDate(user.last_login_at))}</td>
        <td><button class="row-action" data-user-id="${user.id}" data-active="${user.is_active}">${user.is_active ? "Deactivate" : "Activate"}</button></td>
      </tr>`).join("") || `<tr><td colspan="7">No users found.</td></tr>`;
      body.querySelectorAll("[data-scope-picker]").forEach(picker => { updateScopePicker(picker); syncRoleToPosition(picker); });
    } catch (error) { body.innerHTML = `<tr><td colspan="7">${escapeHtml(error.message)}</td></tr>`; }
  }
  function escapeHtml(value) { return String(value ?? "").replace(/[&<>'"]/g, char => ({ "&":"&amp;", "<":"&lt;", ">":"&gt;", "'":"&#39;", '"':"&quot;" }[char])); }

  $("userForm")?.addEventListener("submit", async event => {
    event.preventDefault(); message("");
    try {
      const values = formData(event.target);
      if (values.role === "admin") values.scope_position_code = null;
      await request("/api/admin/users", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(values) });
      event.target.reset(); const search = $("newUserScopePicker")?.querySelector("[data-scope-position-search]"); if (search) search.value = ""; updateScopePicker($("newUserScopePicker")); message("User created successfully."); await loadUsers();
    } catch (error) { message(error.message, true); }
  });
  $("userForm select[name=role]")?.addEventListener("change", event => {
    const picker = $("newUserScopePicker"), required = event.target.value !== "admin";
    const scope = picker?.querySelector("[data-scope-position]");
    picker?.querySelectorAll("select, input").forEach(control => { control.disabled = !required; });
    if (scope) { scope.required = required; if (!required) scope.value = ""; }
    if (required) updateScopePicker(picker);
    picker?.classList.toggle("is-disabled", !required);
  });
  $("importForm")?.addEventListener("submit", async event => {
    event.preventDefault(); message("");
    const values = formData(event.target);
    try {
      const rows = JSON.parse(values.rows);
      if (!Array.isArray(rows) || !rows.length || rows.some(row => !row || typeof row !== "object" || Array.isArray(row))) throw new Error("Rows must be a JSON array of objects");
      const result = await request("/api/admin/data-import", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ table: values.table, rows }) });
      message(`${result.rows_inserted} row(s) imported into ${result.table}.`); event.target.reset();
    } catch (error) { message(error.message, true); }
  });
  $("refreshUsers")?.addEventListener("click", loadUsers);
  document.addEventListener("change", event => {
    const picker = event.target.closest("[data-scope-picker]"); if (!picker) return;
    if (event.target.matches("[data-scope-designation]")) updateScopePicker(picker);
    if (event.target.matches("[data-scope-position]")) { renderScopePreview(event.target, picker.dataset.previewTarget || "newUserScopePreview"); syncRoleToPosition(picker); }
  });
  document.addEventListener("input", event => {
    const picker = event.target.closest("[data-scope-picker]");
    if (picker && event.target.matches("[data-scope-position-search]")) { picker.dataset.openPositionMenu = "true"; updateScopePicker(picker); }
  });
  document.addEventListener("focusin", event => {
    const picker = event.target.closest("[data-scope-picker]");
    if (picker && event.target.matches("[data-scope-position-search]")) { picker.dataset.openPositionMenu = "true"; updateScopePicker(picker); }
  });
  document.addEventListener("click", event => {
    const option = event.target.closest("[data-position-value]");
    if (option) {
      const picker = option.closest("[data-scope-picker]");
      const position = picker?.querySelector("[data-scope-position]");
      const search = picker?.querySelector("[data-scope-position-search]");
      if (position) { position.value = option.dataset.positionValue; position.dataset.selectedScope = position.value; }
      if (search) search.value = option.dataset.positionValue;
      const menu = picker?.querySelector("[data-scope-position-menu]");
      if (menu) menu.hidden = true;
      if (picker) picker.dataset.openPositionMenu = "false";
      renderScopePreview(position, picker?.dataset.previewTarget || "newUserScopePreview");
      syncRoleToPosition(picker);
      return;
    }
    if (!event.target.closest(".scope-search-box")) document.querySelectorAll("[data-scope-picker]").forEach(picker => { picker.dataset.openPositionMenu = "false"; const menu = picker.querySelector("[data-scope-position-menu]"); if (menu) menu.hidden = true; });
  });
  $("usersBody")?.addEventListener("click", async event => {
    const button = event.target.closest("[data-save-scope]"); if (!button) return;
    const picker = document.querySelector(`[data-scope-picker="${button.dataset.saveScope}"]`);
    const select = picker?.querySelector("[data-scope-position]");
    if (!select?.value) { message("Choose a hierarchy position before saving access.", true); return; }
    button.disabled = true;
    try {
      const role = picker?.closest("tr")?.querySelector(`[data-user-role="${button.dataset.saveScope}"]`)?.value;
      await request(`/api/admin/users/${button.dataset.saveScope}`, { method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ scope_position_code: select.value, ...(role ? { role } : {}) }) });
      message("Role and hierarchy access updated. The user’s next dashboard request will use this scope."); await loadUsers();
    } catch (error) { message(error.message, true); button.disabled = false; }
  });
  $("usersBody")?.addEventListener("click", async event => {
    const button = event.target.closest("[data-user-id]"); if (!button) return;
    button.disabled = true;
    try {
      await request(`/api/admin/users/${button.dataset.userId}`, { method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ is_active: button.dataset.active !== "true" }) });
      message("User status updated."); await loadUsers();
    } catch (error) { message(error.message, true); button.disabled = false; }
  });
  loadStaff().then(loadUsers).catch(error => message(error.message, true));
})();
