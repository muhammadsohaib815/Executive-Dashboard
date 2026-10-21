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
      if (status.authenticated) window.location.replace(status.user.role === "admin" ? "/admin" : "/");
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
        window.location.replace(result.user.role === "admin" ? "/admin" : "/");
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

  const logout = $("logoutButton");
  const adminLink = $("adminLink");
  if (logout || adminLink) {
    request("/api/auth/me").then(({ user }) => {
      if (adminLink) adminLink.hidden = user.role !== "admin";
      if (logout) logout.hidden = false;
      document.querySelector("[data-auth-user]")?.replaceChildren(document.createTextNode(user.full_name));
    }).catch(() => window.location.replace("/"));
    logout?.addEventListener("click", async () => {
      await fetch("/api/auth/logout", { method: "POST", credentials: "same-origin" });
      window.location.replace("/");
    });
  }
})();
