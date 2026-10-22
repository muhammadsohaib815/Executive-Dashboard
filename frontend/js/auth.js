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

  const logout = $("logoutButton"), profileLink = $("profileLink"), adminLink = $("adminLink");
  const userMenuButton = $("userMenuButton"), userMenuPanel = $("userMenuPanel");
  const profileModal = $("profileModal"), profileClose = $("profileClose"), profileForm = $("profileForm"), passwordForm = $("passwordForm");
  const profileMessage = $("profileMessage"), profileNotifications = $("profileNotifications"), profilePhoto = $("profilePhoto"), profileAvatar = $("profileAvatar");
  let authenticatedUser = null;
  let profilePhotoData = null;
  const escapeHtml = value => String(value ?? "").replace(/[&<>"']/g, c => ({ "&":"&amp;", "<":"&lt;", ">":"&gt;", '"':"&quot;", "'":"&#39;" }[c]));
  const firstName = name => String(name || "User").trim().split(/\s+/)[0];
  const formatDate = value => value ? new Date(`${value}${/^\d{4}-\d\d-\d\d$/.test(value) ? "T00:00:00" : ""}`).toLocaleDateString() : "No due date";
  const profileStatus = (text, error = false) => {
    if (!profileMessage) return;
    profileMessage.textContent = text || "";
    profileMessage.hidden = !text;
    profileMessage.classList.toggle("error", error);
  };

  function renderProfileNotifications(notifications) {
    if (!profileNotifications) return;
    profileNotifications.innerHTML = notifications.length ? notifications.map(item => `
      <article class="profile-notification${item.read_at ? "" : " unread"}">
        <div><b>${escapeHtml(item.priority)} priority · ${escapeHtml(item.status)}</b><time>${escapeHtml(formatDate(item.created_at))}</time></div>
        <strong>${escapeHtml(item.action_text)}</strong>
        <small>From ${escapeHtml(item.sender)} · Owner ${escapeHtml(item.action_owner || "Unassigned")} · Due ${escapeHtml(formatDate(item.due_date))}</small>
      </article>`).join("") : '<p class="notification-empty">No recent notifications.</p>';
  }

  async function openProfile() {
    if (!profileModal) return;
    profileModal.hidden = false;
    profileStatus("Loading profile...");
    try {
      const [{ profile }, notificationData] = await Promise.all([request("/api/profile"), request("/api/notifications")]);
      profilePhotoData = profile.profile_photo_data || null;
      const set = (name, value) => { const input = profileForm?.querySelector(`[name="${name}"]`); if (input) input.value = value || ""; };
      set("full_name", profile.full_name); set("username", profile.username); set("role", profile.role);
      set("designation", profile.designation); set("position_code", profile.scope_position_code);
      set("territory", profile.territory); set("region", profile.region); set("zone", profile.zone);
      const name = $("profileName"), designation = $("profileDesignation");
      if (name) name.textContent = profile.full_name || "User";
      if (designation) designation.textContent = `${profile.designation || profile.role || "Dashboard user"}${profile.team ? ` · ${profile.team}` : ""}`;
      if (profileAvatar) profileAvatar.src = profilePhotoData || "/images/greenstar-short.jfif";
      renderProfileNotifications(notificationData.notifications || []);
      profileStatus("");
    } catch (error) {
      profileStatus(error.message, true);
    }
  }

  if (logout || profileLink || adminLink || userMenuButton) {
    request("/api/auth/me").then(({ user }) => {
      authenticatedUser = user;
      // The dashboard account menu always opens the personal profile. The
      // administrator workspace remains available from its own route.
      if (profileLink) profileLink.hidden = false;
      if (adminLink) adminLink.hidden = user.role !== "admin";
      if (logout) logout.hidden = false;
      const fullName = document.querySelector("[data-auth-user]");
      if (fullName) fullName.textContent = user.full_name;
      const first = document.querySelector("[data-auth-first-name]");
      if (first) first.textContent = firstName(user.full_name);
      if (userMenuButton) {
        userMenuButton.hidden = false;
        userMenuButton.title = user.full_name;
      }
      document.dispatchEvent(new CustomEvent("dashboard:auth-user", { detail: user }));
    }).catch(() => window.location.replace("/"));
    logout?.addEventListener("click", async () => {
      await fetch("/api/auth/logout", { method: "POST", credentials: "same-origin" });
      window.location.replace("/");
    });
  }

  profileLink?.addEventListener("click", event => {
    event.preventDefault();
    userMenuPanel && (userMenuPanel.hidden = true);
    userMenuButton?.setAttribute("aria-expanded", "false");
    openProfile();
  });
  profileClose?.addEventListener("click", () => { profileModal.hidden = true; });
  profileModal?.addEventListener("click", event => { if (event.target === profileModal) profileModal.hidden = true; });
  document.addEventListener("keydown", event => { if (event.key === "Escape" && profileModal && !profileModal.hidden) profileModal.hidden = true; });
  profilePhoto?.addEventListener("change", event => {
    const file = event.target.files?.[0];
    if (!file) return;
    if (!/^image\/(png|jpeg|webp)$/.test(file.type) || file.size > 1_000_000) {
      profileStatus("Choose a PNG, JPEG, or WebP image up to 1 MB.", true);
      event.target.value = "";
      return;
    }
    const reader = new FileReader();
    reader.onload = () => { profilePhotoData = String(reader.result || ""); if (profileAvatar) profileAvatar.src = profilePhotoData; profileStatus("Photo ready. Save profile to apply it."); };
    reader.readAsDataURL(file);
  });
  profileForm?.addEventListener("submit", async event => {
    event.preventDefault();
    const button = profileForm.querySelector("[type=submit]");
    button.disabled = true;
    profileStatus("Saving profile...");
    try {
      const body = { full_name: profileForm.querySelector('[name="full_name"]').value.trim() };
      if (profilePhotoData !== null) body.profile_photo_data = profilePhotoData;
      const { profile } = await request("/api/profile", { method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
      const fullName = document.querySelector("[data-auth-user]");
      const first = document.querySelector("[data-auth-first-name]");
      if (fullName) fullName.textContent = profile.full_name;
      if (first) first.textContent = firstName(profile.full_name);
      $("profileName") && ($("profileName").textContent = profile.full_name);
      profileStatus("Profile updated successfully.");
    } catch (error) { profileStatus(error.message, true); }
    finally { button.disabled = false; }
  });
  passwordForm?.addEventListener("submit", async event => {
    event.preventDefault();
    const button = passwordForm.querySelector("[type=submit]");
    button.disabled = true;
    profileStatus("Changing password...");
    try {
      const values = Object.fromEntries(new FormData(passwordForm).entries());
      if (values.current_password === values.new_password) throw new Error("New password must be different");
      await request("/api/profile/password", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(values) });
      passwordForm.reset();
      profileStatus("Password changed successfully.");
    } catch (error) { profileStatus(error.message, true); }
    finally { button.disabled = false; }
  });

  userMenuButton?.addEventListener("click", () => {
    const open = userMenuPanel.hidden;
    userMenuPanel.hidden = !open;
    userMenuButton.setAttribute("aria-expanded", String(open));
  });
  document.addEventListener("click", event => {
    if (userMenuPanel && !event.target.closest("#userMenu")) {
      userMenuPanel.hidden = true;
      userMenuButton?.setAttribute("aria-expanded", "false");
    }
  });
})();
