(function () {
  const $ = id => document.getElementById(id);
  const message = text => {
    const el = $("authMessage");
    if (!el) return;
    el.textContent = text || "";
    el.hidden = !text;
  };
  const readError = async response => {
    try {
      const body = await response.json();
      return body.detail || "Request failed";
    } catch (_) {
      return `Request failed (${response.status})`;
    }
  };
  const request = async (url, options = {}) => {
    const response = await fetch(url, { credentials: "same-origin", ...options });
    if (!response.ok) throw new Error(await readError(response));
    return response.json();
  };
  const formData = form => Object.fromEntries(new FormData(form).entries());

  const loginForm = $("loginForm");
  const setupForm = $("setupForm");
  if (loginForm) {
    const loginView = $("loginView");
    const setupView = $("setupView");
    $("showSetup")?.addEventListener("click", () => { loginView.hidden = true; setupView.hidden = false; message(""); });
    $("showLogin")?.addEventListener("click", () => { setupView.hidden = true; loginView.hidden = false; message(""); });
    request("/api/auth/status").then(status => {
      if (status.authenticated) window.location.replace(status.user.role === "admin" ? "/admin" : "/dashboard");
      $("showSetup").hidden = !status.setup_required;
    }).catch(error => message(error.message));
    loginForm.addEventListener("submit", async event => {
      event.preventDefault(); message("");
      const button = loginForm.querySelector("button[type=submit]");
      button.disabled = true; button.textContent = "Signing in...";
      try {
        const result = await request("/api/auth/login", {
          method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(formData(loginForm)),
        });
        window.location.replace(result.user.role === "admin" ? "/admin" : "/dashboard");
      } catch (error) {
        message(error.message);
      } finally {
        button.disabled = false; button.textContent = "Sign in";
      }
    });
  }
  if (setupForm) {
    setupForm.addEventListener("submit", async event => {
      event.preventDefault(); message("");
      const button = setupForm.querySelector("button[type=submit]");
      button.disabled = true; button.textContent = "Creating...";
      try {
        await request("/api/auth/setup", {
          method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(formData(setupForm)),
        });
        window.location.replace("/admin");
      } catch (error) {
        message(error.message);
      } finally {
        button.disabled = false; button.textContent = "Create administrator";
      }
    });
  }

  const logout = $("logoutButton"), adminLink = $("adminLink");
  const userMenuButton = $("userMenuButton"), userMenuPanel = $("userMenuPanel");
  const notificationList = $("notificationList"), notificationBadge = $("notificationBadge");
  const escapeHtml = value => String(value ?? "").replace(/[&<>"']/g, c => ({ "&":"&amp;", "<":"&lt;", ">":"&gt;", '"':"&quot;", "'":"&#39;" }[c]));
  const firstName = name => String(name || "User").trim().split(/\s+/)[0];
  const formatDate = value => value ? new Date(`${value}${/^\d{4}-\d\d-\d\d$/.test(value) ? "T00:00:00" : ""}`).toLocaleDateString() : "No due date";

  async function loadNotifications() {
    if (!notificationList) return;
    try {
      const { notifications, unread_count } = await request("/api/notifications");
      if (notificationBadge) {
        notificationBadge.textContent = unread_count > 99 ? "99+" : String(unread_count);
        notificationBadge.hidden = !unread_count;
      }
      notificationList.innerHTML = notifications.length ? notifications.map(item => `
        <button class="notification-item${item.read_at ? " is-read" : " is-unread"}" type="button" data-notification-id="${Number(item.id)}">
          <span class="notification-item-top"><b>${escapeHtml(item.priority)} priority · ${escapeHtml(item.status)}</b><time>${escapeHtml(formatDate(item.created_at))}</time></span>
          <span class="notification-action">${escapeHtml(item.action_text)}</span>
          <span class="notification-meta">From ${escapeHtml(item.sender)} · Owner ${escapeHtml(item.action_owner || "Unassigned")} · Due ${escapeHtml(formatDate(item.due_date))}</span>
        </button>`).join("") : '<p class="notification-empty">No action plan notifications yet.</p>';
    } catch (error) {
      notificationList.innerHTML = `<p class="notification-empty">${escapeHtml(error.message)}</p>`;
    }
  }

  if (logout || adminLink || userMenuButton) {
    request("/api/auth/me").then(({ user }) => {
      if (adminLink) adminLink.hidden = user.role !== "admin";
      if (logout) logout.hidden = false;
      const fullName = document.querySelector("[data-auth-user]");
      if (fullName) fullName.textContent = user.full_name;
      const first = document.querySelector("[data-auth-first-name]");
      if (first) first.textContent = firstName(user.full_name);
      if (userMenuButton) {
        userMenuButton.hidden = false;
        userMenuButton.title = user.full_name;
        loadNotifications();
      }
    }).catch(() => window.location.replace("/"));
    logout?.addEventListener("click", async () => {
      await fetch("/api/auth/logout", { method: "POST", credentials: "same-origin" });
      window.location.replace("/");
    });
  }

  userMenuButton?.addEventListener("click", () => {
    const open = userMenuPanel.hidden;
    userMenuPanel.hidden = !open;
    userMenuButton.setAttribute("aria-expanded", String(open));
    if (open) loadNotifications();
  });
  document.addEventListener("click", event => {
    if (userMenuPanel && !event.target.closest("#userMenu")) {
      userMenuPanel.hidden = true;
      userMenuButton?.setAttribute("aria-expanded", "false");
    }
  });
  notificationList?.addEventListener("click", async event => {
    const item = event.target.closest("[data-notification-id]");
    if (!item) return;
    try {
      await request(`/api/notifications/${item.dataset.notificationId}`, {
        method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ read: true }),
      });
      await loadNotifications();
      $("panel-6")?.scrollIntoView({ behavior: "smooth", block: "center" });
    } catch (error) {
      item.title = error.message;
    }
  });
})();
