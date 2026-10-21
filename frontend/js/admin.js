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

  async function loadUsers() {
    const body = $("usersBody");
    try {
      const { users } = await request("/api/admin/users");
      body.innerHTML = users.map(user => `<tr>
        <td>${escapeHtml(user.full_name)}</td><td>${escapeHtml(user.username)}</td>
        <td>${escapeHtml(user.role)}</td><td class="${user.is_active ? "status-active" : "status-inactive"}">${user.is_active ? "Active" : "Inactive"}</td>
        <td>${escapeHtml(formatDate(user.last_login_at))}</td>
        <td><button class="row-action" data-user-id="${user.id}" data-active="${user.is_active}">${user.is_active ? "Deactivate" : "Activate"}</button></td>
      </tr>`).join("") || `<tr><td colspan="6">No users found.</td></tr>`;
    } catch (error) { body.innerHTML = `<tr><td colspan="6">${escapeHtml(error.message)}</td></tr>`; }
  }
  function escapeHtml(value) { return String(value ?? "").replace(/[&<>'"]/g, char => ({ "&":"&amp;", "<":"&lt;", ">":"&gt;", "'":"&#39;", '"':"&quot;" }[char])); }

  $("userForm")?.addEventListener("submit", async event => {
    event.preventDefault(); message("");
    try {
      await request("/api/admin/users", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(formData(event.target)) });
      event.target.reset(); message("User created successfully."); await loadUsers();
    } catch (error) { message(error.message, true); }
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
  $("usersBody")?.addEventListener("click", async event => {
    const button = event.target.closest("[data-user-id]"); if (!button) return;
    button.disabled = true;
    try {
      await request(`/api/admin/users/${button.dataset.userId}`, { method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ is_active: button.dataset.active !== "true" }) });
      message("User status updated."); await loadUsers();
    } catch (error) { message(error.message, true); button.disabled = false; }
  });
  loadUsers();
})();
