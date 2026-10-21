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
  const positionMap = () => new Map(staffRows.map(row => [row.position_code, row]));
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
  function optionMarkup(selected = "") {
    const seen = new Set();
    return '<option value="">Select hierarchy position</option>' + staffRows.filter(row => {
      if (!row.position_code || seen.has(row.position_code)) return false;
      seen.add(row.position_code); return true;
    }).map(row => `<option value="${escapeHtml(row.position_code)}"${row.position_code === selected ? " selected" : ""}>${escapeHtml(choiceLabel(row))}</option>`).join("");
  }
  function renderScopePreview(select, target) {
    const position = select?.value, box = $(target);
    if (!box) return;
    const row = positionMap().get(position), tree = descendants(position);
    box.hidden = !row;
    if (!row) { box.innerHTML = ""; return; }
    const asm = tree.filter(person => String(person.designation || "").trim().toUpperCase() === "ASM");
    box.innerHTML = `<b>${escapeHtml(choiceLabel(row))}</b><span>Dashboard visibility: ${tree.length} staff position(s), including this position.</span><details><summary>View reporting hierarchy (${asm.length} ASM)</summary><span>${tree.map(person => `${person.designation || "Staff"}: ${person.employee || "Unnamed"} (${person.position_code})`).map(escapeHtml).join(" · ")}</span></details>`;
  }

  async function loadStaff() {
    const { staff } = await request("/api/admin/staff");
    staffRows = staff;
    const select = $("newUserScope");
    if (select) select.innerHTML = optionMarkup();
  }

  async function loadUsers() {
    const body = $("usersBody");
    try {
      const { users } = await request("/api/admin/users");
      body.innerHTML = users.map(user => `<tr>
        <td>${escapeHtml(user.full_name)}</td><td>${escapeHtml(user.username)}</td>
        <td>${escapeHtml(user.role)}</td>
        <td>${user.role === "admin" ? "All dashboard data" : `<select class="user-scope-select" data-scope-user="${user.id}">${optionMarkup(user.scope_position_code || "")}</select><small class="scope-row-preview" data-scope-preview="${user.id}"></small><button class="row-action scope-save" type="button" data-save-scope="${user.id}">Save access</button>`}</td>
        <td class="${user.is_active ? "status-active" : "status-inactive"}">${user.is_active ? "Active" : "Inactive"}</td>
        <td>${escapeHtml(formatDate(user.last_login_at))}</td>
        <td><button class="row-action" data-user-id="${user.id}" data-active="${user.is_active}">${user.is_active ? "Deactivate" : "Activate"}</button></td>
      </tr>`).join("") || `<tr><td colspan="7">No users found.</td></tr>`;
    } catch (error) { body.innerHTML = `<tr><td colspan="7">${escapeHtml(error.message)}</td></tr>`; }
  }
  function escapeHtml(value) { return String(value ?? "").replace(/[&<>'"]/g, char => ({ "&":"&amp;", "<":"&lt;", ">":"&gt;", "'":"&#39;", '"':"&quot;" }[char])); }

  $("userForm")?.addEventListener("submit", async event => {
    event.preventDefault(); message("");
    try {
      const values = formData(event.target);
      if (values.role === "admin") values.scope_position_code = null;
      await request("/api/admin/users", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(values) });
      event.target.reset(); message("User created successfully."); await loadUsers();
    } catch (error) { message(error.message, true); }
  });
  $("userForm select[name=role]")?.addEventListener("change", event => {
    const scope = $("newUserScope"), required = event.target.value !== "admin";
    scope.required = required; scope.disabled = !required;
    if (!required) { scope.value = ""; renderScopePreview(scope, "newUserScopePreview"); }
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
  $("usersBody")?.addEventListener("change", event => {
    const select = event.target.closest("[data-scope-user]"); if (!select) return;
    const row = positionMap().get(select.value), tree = descendants(select.value);
    const preview = document.querySelector(`[data-scope-preview="${select.dataset.scopeUser}"]`);
    if (!preview) return;
    const asm = tree.filter(person => String(person.designation || "").trim().toUpperCase() === "ASM");
    preview.textContent = row ? `Includes ${tree.length} positions (${asm.length} ASM): ${asm.map(person => `${person.employee} [${person.position_code}]`).join(", ") || "No ASM reporting below this position"}` : "Choose a position";
  });
  $("usersBody")?.addEventListener("click", async event => {
    const button = event.target.closest("[data-save-scope]"); if (!button) return;
    const select = document.querySelector(`[data-scope-user="${button.dataset.saveScope}"]`);
    if (!select?.value) { message("Choose a hierarchy position before saving access.", true); return; }
    button.disabled = true;
    try {
      await request(`/api/admin/users/${button.dataset.saveScope}`, { method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ scope_position_code: select.value }) });
      message("Hierarchy access updated. The user’s next dashboard request will use this scope."); await loadUsers();
    } catch (error) { message(error.message, true); button.disabled = false; }
  });
  $("newUserScope")?.addEventListener("change", event => renderScopePreview(event.target, "newUserScopePreview"));
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
