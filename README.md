# Brandmark — AI Brand Name Generator + Trademark Screening Platform

This implements the PRD in `AI_Brand_Name_Generator_PRD.md`. It's a two-part
project: a Flask API backend and a vanilla HTML/CSS/JS frontend, built through
Phase 4 of the PRD's roadmap with the remaining phases scaffolded and clearly
marked (see "What's implemented" below).

## Project layout

```
backend/
  app/
    config.py            # env-driven config
    extensions.py         # db, cors, rate limiter
    models/models.py      # full schema: users, plans, subscriptions,
                           # generations, generated_names, favorites,
                           # trademark_searches, admin_settings, audit_logs
    services/
      ai_service.py        # AIService — structured JSON generation via Google Gemini
      ranking_service.py   # quality filter, duplicate filter, ranking
      trademark_service.py # TrademarkService — real-provider architecture
      domain_service.py    # DomainService — real-provider architecture
      payment_service.py   # PaymentService — modular, no hard-coded prices
    routes/
      auth_routes.py       # register, login, logout, refresh, me
      generate_routes.py   # POST /api/generate (the full pipeline), history
      favorite_routes.py   # favorites CRUD
      plan_routes.py        # public pricing
      admin_routes.py       # users, plans, subscriptions, trademark logs,
                             # analytics, settings — all @admin_required
    utils/auth.py          # bcrypt hashing, JWT issuing/verification,
                            # login_required / admin_required decorators
  run.py                  # entrypoint
  seed_admin.py           # create/promote an admin user
  requirements.txt
  .env.example

frontend/
  index.html, generate.html, login.html, register.html, dashboard.html,
  history.html, favorites.html, pricing.html, profile.html, admin.html
  css/main.css            # design system (see "Design" below)
  js/api.js               # fetch client + token storage/refresh
  js/nav.js                # shared nav, route guards
  js/generate.js           # generator page logic
```

## How to run the backend

```bash
cd backend
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
# edit .env: set SECRET_KEY, JWT_SECRET_KEY, and GEMINI_API_KEY at minimum
python run.py
# API now on http://localhost:5000/api, health check at /api/health
```

Create an admin user:

```bash
python seed_admin.py you@example.com "StrongPass123"
```

## How to run the frontend

It's static — no build step. Two options:

```bash
cd frontend
python3 -m http.server 5500
# open http://localhost:5500
```

Or open `index.html` directly and set `window.BRANDGEN_API_BASE` in a
`<script>` tag before `js/api.js` loads if your backend isn't on
`http://localhost:5000/api`.

Also set `FRONTEND_ORIGIN` in the backend `.env` to match wherever the
frontend is served from, so CORS allows it.

## Required environment variables

See `backend/.env.example` for the full list. At minimum to actually
generate names you need:
- `SECRET_KEY`, `JWT_SECRET_KEY` — any long random strings
- `GEMINI_API_KEY` — required for `/api/generate` to work (uses the
  `google-genai` SDK); without it the endpoint returns a clear 503 rather
  than fake results

## External APIs that still need credentials

- **Trademark screening** (`TRADEMARK_PROVIDER`, `TRADEMARK_API_USERNAME`,
  `TRADEMARK_API_PASSWORD`): `trademark_service.py` implements a real,
  documented provider (`markerapi` — USPTO/US wordmark search via
  markerapi.com's REST API) but it needs an active markerapi subscription
  to actually run. Until credentials are set (or for jurisdictions outside
  the US, which markerapi doesn't cover), every result is honestly reported
  as `"Search Failed"` or `"Needs Manual Review"` — the code never
  fabricates a risk level or claims "available"/"cleared".
- **Domain availability** (`DOMAIN_PROVIDER`): defaults to `rdap`, the free
  public IANA/ICANN RDAP bootstrap — this works out of the box with no
  credentials and returns real registry data. Set `DOMAIN_PROVIDER=none` to
  disable it, or wire a paid provider via `generic_rest` +
  `DOMAIN_API_KEY`/`DOMAIN_API_BASE_URL`.
- **Payments** (`PAYMENT_PROVIDER`, `PAYMENT_API_KEY`, `PAYMENT_WEBHOOK_SECRET`):
  `payment_service.py` implements a real, live Stripe integration
  (`stripe` package) — checkout, billing portal, and webhook verification
  all work once you set `PAYMENT_PROVIDER=stripe` and a real Stripe secret
  key. Until configured, checkout/portal return a clean `503` rather than
  a broken redirect.

## Jurisdiction-aware trademark screening

Trademark screening infers a jurisdiction from the Phase 3 "Advanced naming
controls" → target market field (e.g. "Tamil Nadu" → India). If nothing was
specified, jurisdiction is explicitly "Not specified" rather than silently
assuming the US. The configured provider (`markerapi`) only covers USPTO —
if the inferred jurisdiction isn't the US, the response says so plainly and
points at the correct official registry (e.g. India → the Indian Trade
Marks Registry) instead of running an unrelated US search and implying
broader coverage.

## Subscriptions & usage metering

Four premium AI-backed features are metered per plan, per calendar month:
logo generation, name comparison, name refinement, and Brand Intelligence.
Enforcement is entirely server-side (`generate_routes.py`'s
`_check_feature_limit()`) — the frontend never decides whether a request is
allowed, it just surfaces whatever the API returns. Admin accounts
(`role == "ADMIN"`) always bypass every limit. A `None`/missing limit on a
plan means unlimited for that feature, the same convention
`monthly_generation_limit` already used.

Each successful call (not failed ones — a 502/503 never costs the user
quota) logs one row to `FeatureUsage`. The limit check runs **before** the
paid Gemini/Imagen call, so a request that would be rejected never burns
provider quota either. Cached results (e.g. re-opening Brand Intelligence
you already computed) don't count again.

Limits live in each `Plan.features` JSON blob:
```
"logo_generations_per_month": 3,
"comparisons_per_month": 5,
"refinements_per_month": 10,
"brand_intelligence_per_month": 15
```
Free plan ships with the numbers above; Pro ships with all four set to
`null` (unlimited). Adjust them via `PATCH /api/admin/plans/<id>` — there's
no dedicated admin UI for editing this JSON yet, just the existing
raw-PATCH endpoint (see `admin.html`'s Feature usage tab, which explains
this inline). Existing installations get any newly-introduced feature keys
backfilled into their current plans automatically on startup, without
touching values an admin already customized.

Admin analytics (`GET /api/admin/analytics`, `admin.html` → Feature usage
tab) show this-month and all-time counts per metered feature, plus a
trademark-search status breakdown.

## What was implemented (Phases 1–4 of the PRD, plus scaffolding for 5–9)

**Phase 1 — Frontend foundation:** landing page, responsive nav, generator
form with multi-inspiration chip input and style-tag selector, results UI,
mobile-friendly throughout.

**Phase 2 — Backend:** Flask API, `AIService` wrapping the Anthropic API
with a strict structured-JSON contract and server-side validation (never
raw text parsing), a candidate pool sized larger than the requested 25 so
filtering has real material to work with, `RankingService` doing quality
filtering, duplicate filtering (normalized + fuzzy match), and ranking.

**Phase 3 — Authentication:** register/login/logout, bcrypt password
hashing, JWT access + refresh tokens, `USER`/`ADMIN` roles enforced only
server-side (`login_required` / `admin_required` decorators) — the frontend
hiding admin nav links is cosmetic, not the security boundary.

**Phase 4 — User features:** history (list + per-generation detail),
favorites (add/remove), dashboard with real stats pulled from the API.

**Phase 5 — Trademark screening:** live for US wordmarks via `markerapi`
once `TRADEMARK_API_USERNAME`/`TRADEMARK_API_PASSWORD` are set — real
exact/similar match data, USPTO classes, and jurisdiction awareness (see
above). Other jurisdictions honestly report "not applicable" rather than a
fabricated result. Legal disclaimer surfaced in the UI and API response.

**Phase 6 — Domain availability:** live by default via the free `rdap`
provider (no credentials needed) — real registry lookups across
.com/.in/.ai/.io/.co, badges per TLD in the UI.

**Phase 7 — Subscription:** `Plan`/`Subscription` models, public
`/api/plans`, admin plan CRUD and manual subscription assignment, free-tier
limit configurable via the `plans` table (defaults to 25 names/generation).
Live Stripe checkout, billing portal, and webhook reconciliation are now
wired up (`PAYMENT_PROVIDER=stripe`) — see "Subscriptions & usage
metering" above.

**Phase 8 — Admin panel:** `/admin` dashboard (users, subscriptions,
trademark logs, analytics, settings status) backed entirely by
`@admin_required` routes.

**Phase 9 — Security & hardening (partial):** bcrypt hashing, JWT auth,
input validation on register/generate, rate limiting on auth and generation
endpoints (`Flask-Limiter`), CORS scoped to `FRONTEND_ORIGIN`, centralized
error handlers, no secrets in frontend code, `.env.example` provided.
**Not yet done:** production WSGI server config, automated test suite,
security headers (CSP/HSTS), and a token-blacklist table for hard logout
revocation (logout is currently client-side token discard).

## What remains for the next phase

1. Add real trademark providers for jurisdictions beyond the US (India, UK,
   EU) — no free/documented public API was found for these at time of
   writing; would need a paid provider (e.g. Trademarkia, Signa) wired into
   `TrademarkService._dispatch()` the same way `markerapi` was.
2. Add automated tests and a production deployment config (gunicorn/nginx,
   a real Postgres `DATABASE_URL` instead of SQLite).

## A note on testing in this environment

This sandbox has no outbound network access, so I could not `pip install`
the backend's dependencies or actually run the Flask server here to hit the
API live. Every backend file passed `python3 -m py_compile` (verified) and
every frontend JS file passed `node --check` (verified) — but you should run
the "Testing" checklist from the PRD yourself after `pip install -r
requirements.txt` on a machine with network access, since I have not
personally observed it running end-to-end.

## Design

The frontend uses a "type foundry" concept: each generated name renders as
an engraved specimen plate (serif display face for the name itself, mono
for scores/status), on a near-black ground with a single brass/gold accent
standing in for a wax seal or foundry mark — a deliberate departure from
generic AI-tool defaults, chosen to fit a product whose whole value is
"names as artifacts you can trust."
