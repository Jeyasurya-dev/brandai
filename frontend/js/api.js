// Central API client for the Brand Name Generator frontend.
// Change API_BASE to point at your running Flask backend.
const API_BASE = window.BRANDGEN_API_BASE || "http://localhost:5000/api";

const Auth = {
  getAccessToken() { return localStorage.getItem("bg_access_token"); },
  getRefreshToken() { return localStorage.getItem("bg_refresh_token"); },
  getUser() {
    const raw = localStorage.getItem("bg_user");
    return raw ? JSON.parse(raw) : null;
  },
  setSession({ access_token, refresh_token, user }) {
    if (access_token) localStorage.setItem("bg_access_token", access_token);
    if (refresh_token) localStorage.setItem("bg_refresh_token", refresh_token);
    if (user) localStorage.setItem("bg_user", JSON.stringify(user));
  },
  clear() {
    localStorage.removeItem("bg_access_token");
    localStorage.removeItem("bg_refresh_token");
    localStorage.removeItem("bg_user");
  },
  isLoggedIn() { return !!this.getAccessToken(); },
  isAdmin() { const u = this.getUser(); return !!u && u.role === "ADMIN"; },
};

async function apiRequest(path, { method = "GET", body, auth = true, retry = true } = {}) {
  const headers = { "Content-Type": "application/json" };
  if (auth && Auth.getAccessToken()) {
    headers["Authorization"] = `Bearer ${Auth.getAccessToken()}`;
  }

  const res = await fetch(`${API_BASE}${path}`, {
    method,
    headers,
    body: body !== undefined ? JSON.stringify(body) : undefined,
  });

  if (res.status === 401 && auth && retry && Auth.getRefreshToken()) {
    const refreshed = await tryRefreshToken();
    if (refreshed) {
      return apiRequest(path, { method, body, auth, retry: false });
    }
    Auth.clear();
    window.location.href = "/login.html";
    return null;
  }

  let data = null;
  try { data = await res.json(); } catch (e) { /* no body */ }

  if (!res.ok) {
    const message = (data && (data.error || (data.errors && JSON.stringify(data.errors)))) || `Request failed (${res.status})`;
    const err = new Error(message);
    err.status = res.status;
    err.data = data;
    throw err;
  }
  return data;
}

async function tryRefreshToken() {
  try {
    const res = await fetch(`${API_BASE}/auth/refresh`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ refresh_token: Auth.getRefreshToken() }),
    });
    if (!res.ok) return false;
    const data = await res.json();
    Auth.setSession(data);
    return true;
  } catch (e) {
    return false;
  }
}

const Api = {
  register: (payload) => apiRequest("/auth/register", { method: "POST", body: payload, auth: false }),
  login: (payload) => apiRequest("/auth/login", { method: "POST", body: payload, auth: false }),
  logout: () => apiRequest("/auth/logout", { method: "POST" }),
  me: () => apiRequest("/auth/me"),

  generate: (payload) => apiRequest("/generate", { method: "POST", body: payload }),
  buildBrief: (payload) => apiRequest("/brief-builder", { method: "POST", body: payload }),
  nameIntelligence: (id) => apiRequest(`/names/${id}/intelligence`),
  compareNames: (ids) => apiRequest("/names/compare", { method: "POST", body: { ids } }),
  refineName: (id, direction) => apiRequest(`/names/${id}/refine`, { method: "POST", body: { direction } }),
  generateLogo: (id, payload) => apiRequest(`/names/${id}/logo`, { method: "POST", body: payload }),
  history: () => apiRequest("/history"),
  historyDetail: (id) => apiRequest(`/history/${id}`),

  listFavorites: () => apiRequest("/favorites"),
  addFavorite: (generated_name_id, extra) => apiRequest("/favorites", { method: "POST", body: { generated_name_id, ...(extra || {}) } }),
  updateFavorite: (id, fields) => apiRequest(`/favorites/${id}`, { method: "PATCH", body: fields }),
  removeFavorite: (id) => apiRequest(`/favorites/${id}`, { method: "DELETE" }),
  generateTaglines: (favoriteId) => apiRequest(`/favorites/${favoriteId}/taglines`, { method: "POST" }),
  downloadBrandKit: async (favoriteId, filenameHint) => {
    const res = await fetch(`${API_BASE}/favorites/${favoriteId}/export`, {
      headers: { Authorization: `Bearer ${Auth.getAccessToken()}` },
    });
    if (!res.ok) {
      let message = `Export failed (${res.status})`;
      try { const data = await res.json(); message = data.error || message; } catch (e) { /* no JSON body */ }
      throw new Error(message);
    }
    const blob = await res.blob();
    const url = window.URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `${(filenameHint || "brand").replace(/\s+/g, "-").toLowerCase()}-brand-kit.zip`;
    document.body.appendChild(a);
    a.click();
    a.remove();
    window.URL.revokeObjectURL(url);
  },

  plans: () => apiRequest("/plans", { auth: false }),
  createCheckout: (plan_id) => apiRequest("/payments/checkout", { method: "POST", body: { plan_id } }),
  verifyPayment: (payload) => apiRequest("/payments/verify", { method: "POST", body: payload }),
  billingPortal: () => apiRequest("/payments/portal", { method: "POST" }),

  admin: {
    users: (page = 1) => apiRequest(`/admin/users?page=${page}`),
    updateUser: (id, payload) => apiRequest(`/admin/users/${id}`, { method: "PATCH", body: payload }),
    plans: () => apiRequest("/admin/plans"),
    createPlan: (payload) => apiRequest("/admin/plans", { method: "POST", body: payload }),
    updatePlan: (id, payload) => apiRequest(`/admin/plans/${id}`, { method: "PATCH", body: payload }),
    deletePlan: (id) => apiRequest(`/admin/plans/${id}`, { method: "DELETE" }),
    subscriptions: () => apiRequest("/admin/subscriptions"),
    assignSubscription: (payload) => apiRequest("/admin/subscriptions", { method: "POST", body: payload }),
    updateSubscription: (id, payload) => apiRequest(`/admin/subscriptions/${id}`, {method: "PATCH", body: payload }),
    trademarkSearches: (page = 1) => apiRequest(`/admin/trademark-searches?page=${page}`),
    analytics: () => apiRequest("/admin/analytics"),
    settings: () => apiRequest("/admin/settings"),
    updateSetting: (key, value) => apiRequest(`/admin/settings/${key}`, { method: "PUT", body: { value } }),
  },
};
