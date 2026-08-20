function renderNav(activePage) {
  const loggedIn = Auth.isLoggedIn();
  const isAdmin = Auth.isAdmin();
  const nav = document.getElementById("site-nav");
  if (!nav) return;

  const links = [
    { href: "index.html", label: "Home", key: "home" },
    { href: "generate.html", label: "Generate", key: "generate" },
    ...(loggedIn ? [
      { href: "dashboard.html", label: "Dashboard", key: "dashboard" },
      { href: "history.html", label: "History", key: "history" },
      { href: "favorites.html", label: "Favorites", key: "favorites" },
    ] : []),
    { href: "pricing.html", label: "Pricing", key: "pricing" },
    ...(isAdmin ? [{ href: "admin.html", label: "Admin", key: "admin" }] : []),
  ];

  const linkHtml = links.map(l =>
    `<a href="${l.href}" class="${activePage === l.key ? "active" : ""}">${l.label}</a>`
  ).join("");

  const actionsHtml = loggedIn
    ? `<a href="profile.html" class="btn btn-ghost btn-sm">${(Auth.getUser()?.full_name || "Profile").split(" ")[0]}</a>
       <button class="btn btn-primary btn-sm nav-logout-btn">Sign out</button>`
    : `<a href="login.html" class="btn btn-ghost btn-sm">Sign in</a>
       <a href="register.html" class="btn btn-primary btn-sm">Get started</a>`;

  nav.innerHTML = `
    <div class="nav-inner">
      <a href="index.html" class="brand-mark"><span class="seal">B</span>Brandmark</a>
      <button class="nav-toggle" id="nav-toggle" aria-label="Toggle menu">&#9776;</button>
      <div class="nav-links" id="nav-links">
        ${linkHtml}
        <div class="nav-actions-mobile">${actionsHtml}</div>
      </div>
      <div class="nav-actions">${actionsHtml}</div>
    </div>`;

  document.getElementById("nav-toggle")?.addEventListener("click", () => {
    document.getElementById("nav-links").classList.toggle("open");
  });

  document.querySelectorAll(".nav-logout-btn").forEach(btn => {
    btn.addEventListener("click", async () => {
      try { await Api.logout(); } catch (e) { /* ignore */ }
      Auth.clear();
      window.location.href = "index.html";
    });
  });
}

function requireAuth() {
  if (!Auth.isLoggedIn()) {
    window.location.href = "login.html";
  }
}

function requireAdmin() {
  if (!Auth.isLoggedIn() || !Auth.isAdmin()) {
    window.location.href = "index.html";
  }
}

function renderFooter() {
  const footer = document.getElementById("site-footer");
  if (!footer) return;
  footer.innerHTML = `
    <div class="container">
      <span>&copy; ${new Date().getFullYear()} Brandmark. Naming, screened.</span>
      <span>Trademark and domain results are preliminary screenings, not legal guarantees.</span>
    </div>`;
}
