"use strict";

/* =========================================================
   ADMIN DASHBOARD
   ========================================================= */

requireAdmin();
renderNav("admin");
renderFooter();


/* =========================================================
   STATE
   ========================================================= */

let plans = [];
let editingPlanId = null;


/* =========================================================
   HELPERS
   ========================================================= */

function showMessage(id, message, type = "success") {
  const el = document.getElementById(id);

  if (!el) return;

  el.textContent = message;
  el.className = `form-msg ${type}`;

  setTimeout(() => {
    el.textContent = "";
    el.className = "form-msg";
  }, 4000);
}


function formatPrice(priceCents, currency = "INR") {
  if (priceCents === null || priceCents === undefined) {
    return "—";
  }

  const amount = Number(priceCents) / 100;

  const symbol =
    currency === "INR"
      ? "₹"
      : currency === "USD"
        ? "$"
        : currency + " ";

  return `${symbol}${amount.toFixed(2)}`;
}


/* =========================================================
   TABS
   ========================================================= */

document.querySelectorAll(".tab-btn").forEach(btn => {

  btn.addEventListener("click", () => {

    document
      .querySelectorAll(".tab-btn")
      .forEach(b => b.classList.remove("active"));

    document
      .querySelectorAll(".tab-panel")
      .forEach(p => p.classList.remove("active"));

    btn.classList.add("active");

    const panel = document.getElementById(
      `tab-${btn.dataset.tab}`
    );

    if (panel) {
      panel.classList.add("active");
    }

  });

});


/* =========================================================
   ANALYTICS
   ========================================================= */

async function loadAnalytics() {

  try {

    const a = await Api.admin.analytics();

    const cards = document.querySelectorAll(
      "#analytics-grid .stat-card"
    );

    if (cards[0]) {
      cards[0].querySelector(".stat-num").textContent =
        a.total_users;
    }

    if (cards[1]) {
      cards[1].querySelector(".stat-num").textContent =
        a.total_generations;
    }

    if (cards[2]) {
      cards[2].querySelector(".stat-num").textContent =
        a.total_names_generated;
    }

    if (cards[3]) {
      cards[3].querySelector(".stat-num").textContent =
        a.active_subscriptions;
    }

    if (cards[4]) {
      cards[4].querySelector(".stat-num").textContent =
        a.trademark_searches?.total ?? "—";
    }


    const FEATURE_LABELS = {
      logo_generation: "Logo generation",
      name_comparison: "Name comparison",
      name_refinement: "Name refinement",
      brand_intelligence: "Brand Intelligence",
      tagline_generation: "Tagline generation"
    };


    const usage = a.feature_usage || {};

    const usageBody =
      document.getElementById("usage-tbody");

    if (usageBody) {

      usageBody.innerHTML =
        Object.keys(FEATURE_LABELS)
          .map(key => `
            <tr>
              <td>${FEATURE_LABELS[key]}</td>
              <td>${usage[key]?.this_month ?? 0}</td>
              <td>${usage[key]?.total ?? 0}</td>
            </tr>
          `)
          .join("");

    }

  } catch (e) {

    console.error("Analytics error:", e);

  }

}


/* =========================================================
   USERS
   ========================================================= */

async function loadUsers() {

  try {

    const result = await Api.admin.users();

    const users = result.users || [];

    const tbody =
      document.getElementById("users-tbody");

    if (!tbody) return;


    tbody.innerHTML = users.length

      ? users.map(user => `
          <tr>

            <td>${user.email}</td>

            <td>
              ${user.full_name || "—"}
            </td>

            <td>
              <span class="pill-status ${
                user.role === "ADMIN"
                  ? "completed"
                  : "Generating..."
              }">
                ${user.role}
              </span>
            </td>

            <td>
              <span class="pill-status ${
                user.is_active
                  ? "active"
                  : "failed"
              }">
                ${user.is_active
                  ? "active"
                  : "disabled"}
              </span>
            </td>

            <td>
              ${new Date(
                user.created_at
              ).toLocaleDateString()}
            </td>

            <td>

              <button
                class="btn btn-ghost btn-sm toggle-active"
                data-id="${user.id}"
                data-active="${user.is_active}"
              >
                ${
                  user.is_active
                    ? "Disable"
                    : "Enable"
                }
              </button>

            </td>

          </tr>
        `).join("")

      : `
          <tr>
            <td
              colspan="6"
              style="color:var(--muted);"
            >
              No users found.
            </td>
          </tr>
        `;


    document
      .querySelectorAll(".toggle-active")
      .forEach(btn => {

        btn.addEventListener("click", async () => {

          try {

            const newActive =
              btn.dataset.active !== "true";

            await Api.admin.updateUser(
              btn.dataset.id,
              {
                is_active: newActive
              }
            );

            await loadUsers();

          } catch (e) {

            alert(e.message);

          }

        });

      });


  } catch (e) {

    console.error("Users error:", e);

  }

}


/* =========================================================
   PLANS
   ========================================================= */

async function loadPlans() {

  const tbody =
    document.getElementById("plans-tbody");

  if (!tbody) return;

  try {

    const result =
      await Api.admin.plans();

    plans = result.plans || [];

    tbody.innerHTML = plans.length

      ? plans.map(plan => `

          <tr>

            <td>

              <strong>
                ${plan.name}
              </strong>

              <div style="
                color:var(--muted);
                font-size:0.75rem;
                margin-top:4px;
              ">
                ${plan.code}
              </div>

            </td>


            <td>
              ${formatPrice(
                plan.price_cents,
                plan.currency
              )}

              <div style="
                color:var(--muted);
                font-size:0.75rem;
              ">
                / ${plan.billing_period || "month"}
              </div>
            </td>


            <td>
              ${plan.names_per_generation}
            </td>


            <td>
              ${
                plan.monthly_generation_limit ??
                "Unlimited"
              }
            </td>


            <td>

              <span class="pill-status ${
                plan.is_active
                  ? "active"
                  : "failed"
              }">

                ${
                  plan.is_active
                    ? "Active"
                    : "Inactive"
                }

              </span>

            </td>


            <td>

              <div style="
                display:flex;
                gap:8px;
                flex-wrap:wrap;
              ">

                <button
                  type="button"
                  class="btn btn-ghost btn-sm edit-plan-btn"
                  data-id="${plan.id}"
                >
                  Edit
                </button>

                <button
                  type="button"
                  class="btn btn-ghost btn-sm delete-plan-btn"
                  data-id="${plan.id}"
                  data-name="${plan.name}"
                >
                  Delete
                </button>

              </div>

            </td>

          </tr>

        `).join("")

      : `
          <tr>

            <td
              colspan="6"
              style="color:var(--muted);"
            >
              No subscription plans found.
            </td>

          </tr>
        `;


    /* Populate assignment dropdown */

    populatePlanDropdown();


  } catch (e) {

    console.error("Plans error:", e);

    tbody.innerHTML = `
      <tr>

        <td
          colspan="6"
          style="color:var(--high);"
        >
          ${e.message}
        </td>

      </tr>
    `;

  }

}

document.addEventListener("click", async (event) => {

  const button =
    event.target.closest(".delete-plan-btn");

  if (!button) return;

  const planId =
    button.dataset.id;

  const planName =
    button.dataset.name || "this plan";

  const confirmed = window.confirm(
    `Are you sure you want to delete "${planName}"?`
  );

  if (!confirmed) {
    return;
  }

  try {

    button.disabled = true;
    button.textContent = "Deleting…";

    await Api.admin.deletePlan(planId);

    alert(
      `Plan "${planName}" deleted successfully.`
    );

    await loadPlans();

    // Refresh subscription dropdown
    populatePlanDropdown();

  } catch (e) {

    console.error(
      "Delete plan error:",
      e
    );

    alert(
      e.message ||
      "Failed to delete the plan."
    );

    button.disabled = false;
    button.textContent = "Delete";

  }

});

/* =========================================================
   PLAN DROPDOWN
   ========================================================= */

function populatePlanDropdown() {

  const select =
    document.getElementById(
      "subscription-plan"
    );

  if (!select) return;


  select.innerHTML = `
    <option value="">
      Select a plan
    </option>
  `;


  plans
    .filter(plan => plan.is_active)
    .forEach(plan => {

      const option =
        document.createElement("option");

      option.value = plan.id;

      option.textContent =
        `${plan.name} — ${formatPrice(
          plan.price_cents,
          plan.currency
        )}`;

      select.appendChild(option);

    });

}


/* =========================================================
   PLAN FORM
   ========================================================= */

function openPlanForm(plan = null) {

  const form =
    document.getElementById("plan-form");

  if (!form) return;


  editingPlanId =
    plan ? plan.id : null;


  document.getElementById("plan-code").value =
    plan?.code || "";

  document.getElementById("plan-name").value =
    plan?.name || "";

  document.getElementById("plan-price").value =
    plan?.price_cents != null
      ? Number(plan.price_cents) / 100
      : "";

  document.getElementById("plan-currency").value =
    plan?.currency || "INR";

  document.getElementById("plan-billing-period").value =
    plan?.billing_period || "monthly";

  document.getElementById(
    "plan-names-per-generation"
  ).value =
    plan?.names_per_generation ?? "";

  document.getElementById(
    "plan-monthly-limit"
  ).value =
    plan?.monthly_generation_limit ?? "";

  document.getElementById("plan-active").value =
    String(
      plan?.is_active !== false
    );


  form.style.display = "block";


  document.getElementById(
    "save-plan-btn"
  ).textContent =
    plan
      ? "Update Plan"
      : "Save Plan";


  form.scrollIntoView({
    behavior: "smooth",
    block: "nearest"
  });

}


function closePlanForm() {

  const form =
    document.getElementById("plan-form");

  if (!form) return;

  form.style.display = "none";

  editingPlanId = null;


  document.getElementById("plan-code").value = "";
  document.getElementById("plan-name").value = "";
  document.getElementById("plan-price").value = "";
  document.getElementById("plan-currency").value = "INR";
  document.getElementById("plan-billing-period").value = "monthly";
  document.getElementById("plan-names-per-generation").value = "";
  document.getElementById("plan-monthly-limit").value = "";
  document.getElementById("plan-active").value = "true";

}


/* =========================================================
   CREATE PLAN BUTTON
   ========================================================= */

const createPlanBtn =
  document.getElementById(
    "create-plan-btn"
  );


if (createPlanBtn) {

  createPlanBtn.addEventListener(
    "click",
    () => {

      openPlanForm();

    }
  );

}


/* =========================================================
   CANCEL PLAN
   ========================================================= */

const cancelPlanBtn =
  document.getElementById(
    "cancel-plan-btn"
  );


if (cancelPlanBtn) {

  cancelPlanBtn.addEventListener(
    "click",
    () => {

      closePlanForm();

    }
  );

}


/* =========================================================
   SAVE / UPDATE PLAN
   ========================================================= */

const savePlanBtn =
  document.getElementById(
    "save-plan-btn"
  );


if (savePlanBtn) {

  savePlanBtn.addEventListener(
    "click",
    async () => {

      try {

        const code =
          document.getElementById(
            "plan-code"
          ).value.trim();

        const name =
          document.getElementById(
            "plan-name"
          ).value.trim();

        const price =
          Number(
            document.getElementById(
              "plan-price"
            ).value
          );

        const currency =
          document.getElementById(
            "plan-currency"
          ).value;

        const billingPeriod =
          document.getElementById(
            "plan-billing-period"
          ).value;

        const namesPerGeneration =
          Number(
            document.getElementById(
              "plan-names-per-generation"
            ).value
          );

        const monthlyLimitRaw =
          document.getElementById(
            "plan-monthly-limit"
          ).value.trim();

        const monthlyLimit =
          monthlyLimitRaw === ""
            ? null
            : Number(monthlyLimitRaw);

        const isActive =
          document.getElementById(
            "plan-active"
          ).value === "true";


        /* Validation */

        if (!code) {
          throw new Error(
            "Plan code is required."
          );
        }

        if (!name) {
          throw new Error(
            "Plan name is required."
          );
        }

        if (!Number.isFinite(price) || price < 0) {
          throw new Error(
            "Enter a valid price."
          );
        }

        if (
          !Number.isInteger(namesPerGeneration) ||
          namesPerGeneration < 1
        ) {
          throw new Error(
            "Names per generation must be at least 1."
          );
        }

        if (
          monthlyLimit !== null &&
          (
            !Number.isInteger(monthlyLimit) ||
            monthlyLimit < 0
          )
        ) {
          throw new Error(
            "Monthly generation limit is invalid."
          );
        }


        const payload = {

          code,
          name,

          /* Backend expects cents */

          price_cents:
            Math.round(price * 100),

          currency,

          billing_period:
            billingPeriod,

          names_per_generation:
            namesPerGeneration,

          monthly_generation_limit:
            monthlyLimit,

          is_active:
            isActive

        };


        savePlanBtn.disabled = true;

        savePlanBtn.textContent =
          editingPlanId
            ? "Updating…"
            : "Saving…";


        if (editingPlanId) {

          await Api.admin.updatePlan(
            editingPlanId,
            payload
          );

          showMessage(
            "plan-msg",
            "Plan updated successfully.",
            "success"
          );

        } else {

          await Api.admin.createPlan(
            payload
          );

          showMessage(
            "plan-msg",
            "Plan created successfully.",
            "success"
          );

        }


        closePlanForm();

        await loadPlans();

      } catch (e) {

        console.error(
          "Save plan error:",
          e
        );

        showMessage(
          "plan-msg",
          e.message || "Failed to save plan.",
          "error"
        );

      } finally {

        savePlanBtn.disabled = false;

        savePlanBtn.textContent =
          editingPlanId
            ? "Update Plan"
            : "Save Plan";

      }

    }
  );

}


/* =========================================================
   EDIT PLAN BUTTONS
   ========================================================= */

document.addEventListener(
  "click",
  event => {

    const btn =
      event.target.closest(
        ".edit-plan-btn"
      );

    if (!btn) return;


    const plan =
      plans.find(
        p => p.id === btn.dataset.id
      );

    if (plan) {

      openPlanForm(plan);

    }

  }
);


/* =========================================================
   SUBSCRIPTION USERS
   ========================================================= */

async function loadSubscriptionUsers() {

  const select =
    document.getElementById(
      "subscription-user"
    );

  if (!select) return;


  try {

    const result =
      await Api.admin.users();

    const users =
      result.users || [];


    select.innerHTML = `
      <option value="">
        Select a user
      </option>
    `;


    users
      .filter(user => user.is_active)
      .forEach(user => {

        const option =
          document.createElement("option");

        option.value = user.id;

        option.textContent =
          `${user.email}${
            user.full_name
              ? ` — ${user.full_name}`
              : ""
          }`;

        select.appendChild(option);

      });

  } catch (e) {

    console.error(
      "Subscription users error:",
      e
    );

  }

}


/* =========================================================
   ASSIGN SUBSCRIPTION
   ========================================================= */

const assignSubscriptionBtn =
  document.getElementById(
    "assign-subscription-btn"
  );


if (assignSubscriptionBtn) {

  assignSubscriptionBtn.addEventListener(
    "click",
    async () => {

      try {

        const userId =
          document.getElementById(
            "subscription-user"
          ).value;

        const planId =
          document.getElementById(
            "subscription-plan"
          ).value;


        if (!userId) {

          throw new Error(
            "Please select a user."
          );

        }

        if (!planId) {

          throw new Error(
            "Please select a plan."
          );

        }


        assignSubscriptionBtn.disabled =
          true;

        assignSubscriptionBtn.textContent =
          "Assigning…";


        await Api.admin.assignSubscription({
          user_id: userId,
          plan_id: planId
        });


        showMessage(
          "subscription-msg",
          "Subscription assigned successfully.",
          "success"
        );


        document.getElementById(
          "subscription-user"
        ).value = "";

        document.getElementById(
          "subscription-plan"
        ).value = "";


        await loadSubscriptions();

        await loadAnalytics();


      } catch (e) {

        console.error(
          "Assign subscription error:",
          e
        );

        showMessage(
          "subscription-msg",
          e.message ||
            "Failed to assign subscription.",
          "error"
        );

      } finally {

        assignSubscriptionBtn.disabled =
          false;

        assignSubscriptionBtn.textContent =
          "Assign Subscription";

      }

    }
  );

}


/* =========================================================
   SUBSCRIPTIONS TABLE
   ========================================================= */

async function loadSubscriptions() {

  const tbody =
    document.getElementById("subs-tbody");

  if (!tbody) return;

  try {

    const result =
      await Api.admin.subscriptions();

    const subscriptions =
      result.subscriptions || [];

    tbody.innerHTML =
      subscriptions.length

        ? subscriptions.map(s => {

            const userName =
              s.user?.full_name || "Unknown User";

            const userEmail =
              s.user?.email || "No email";

            const subscribedDate =
              s.created_at
                ? new Date(
                    s.created_at
                  ).toLocaleDateString()
                : "—";

            return `
              <tr>

                <td>
                  <div style="
                    font-weight:600;
                  ">
                    ${userName}
                  </div>

                  <div style="
                    color:var(--muted);
                    font-size:0.78rem;
                    margin-top:4px;
                  ">
                    ${userEmail}
                  </div>
                </td>

                <td>
                  ${s.plan?.name || "—"}
                </td>

                <td>
                  <span class="pill-status ${s.status}">
                    ${s.status}
                  </span>
                </td>

                <td>
                  ${s.provider || "—"}
                </td>

                <td>
                  ${subscribedDate}
                </td>

                <td>
                  ${
                    s.status === "active"
                      ? `
                        <button
                          type="button"
                          class="btn btn-ghost btn-sm cancel-subscription-btn"
                          data-id="${s.id}"
                        >
                          Cancel
                        </button>
                      `
                      : "—"
                  }
                </td>

              </tr>
            `;

          }).join("")

        : `
          <tr>
            <td
              colspan="6"
              style="color:var(--muted);"
            >
              No subscriptions yet.
            </td>
          </tr>
        `;

  } catch (e) {

    console.error(
      "Subscriptions error:",
      e
    );

    tbody.innerHTML = `
      <tr>
        <td
          colspan="6"
          style="color:var(--high);"
        >
          ${e.message}
        </td>
      </tr>
    `;

  }

}

document.addEventListener("click", async (event) => {

  const button =
    event.target.closest(".cancel-subscription-btn");

  if (!button) return;

  const subscriptionId =
    button.dataset.id;

  const confirmed = window.confirm(
    "Are you sure you want to cancel this subscription?"
  );

  if (!confirmed) return;

  try {

    button.disabled = true;
    button.textContent = "Cancelling…";

    await Api.admin.updateSubscription(
      subscriptionId,
      {
        status: "cancelled"
      }
    );

    alert(
      "Subscription cancelled successfully."
    );

    await loadSubscriptions();

    // Refresh analytics count
    if (typeof loadAnalytics === "function") {
      await loadAnalytics();
    }

  } catch (e) {

    console.error(
      "Cancel subscription error:",
      e
    );

    alert(
      e.message ||
      "Failed to cancel subscription."
    );

    button.disabled = false;
    button.textContent = "Cancel";
  }

});


/* =========================================================
   TRADEMARK
   ========================================================= */

async function loadTrademarkSearches() {

  const tbody =
    document.getElementById(
      "tm-tbody"
    );

  if (!tbody) return;


  try {

    const result =
      await Api.admin.trademarkSearches();

    const searches =
      result.searches || [];


    tbody.innerHTML =
      searches.length

        ? searches.map(s => `

            <tr>

              <td>
                ${s.query_name}
              </td>

              <td>
                ${s.provider || "none"}
              </td>

              <td>

                <span class="badge ${
                  s.status === "Low Risk"
                    ? "low"
                    : s.status === "Medium Risk"
                      ? "medium"
                      : s.status === "High Risk"
                        ? "high"
                        : "review"
                }">
                  ${s.status}
                </span>

              </td>

              <td>
                ${new Date(
                  s.created_at
                ).toLocaleString()}
              </td>

            </tr>

          `).join("")

        : `
            <tr>

              <td
                colspan="4"
                style="color:var(--muted);"
              >
                No trademark searches logged yet.
              </td>

            </tr>
          `;


  } catch (e) {

    console.error(
      "Trademark error:",
      e
    );

  }

}


/* =========================================================
   SETTINGS
   ========================================================= */

function renderSettings() {

  const el =
    document.getElementById(
      "settings-status"
    );

  if (!el) return;


  el.innerHTML = `

    <div class="stat-card">

      <div class="stat-label">
        AI provider
      </div>

      <div style="margin-top:8px;">
        Configured via
        <code>GEMINI_API_KEY</code>
      </div>

    </div>


    <div class="stat-card">

      <div class="stat-label">
        Logo generation
      </div>

      <div style="margin-top:8px;">
        Same <code>GEMINI_API_KEY</code>
      </div>

    </div>


    <div class="stat-card">

      <div class="stat-label">
        Trademark provider
      </div>

      <div style="margin-top:8px;">
        Configured via
        <code>TRADEMARK_PROVIDER</code>
      </div>

    </div>


    <div class="stat-card">

      <div class="stat-label">
        Domain provider
      </div>

      <div style="margin-top:8px;">
        Configured via
        <code>DOMAIN_PROVIDER</code>
      </div>

    </div>


    <div class="stat-card">

      <div class="stat-label">
        Payment provider
      </div>

      <div style="margin-top:8px;">
        Configured via
        <code>PAYMENT_PROVIDER</code>
      </div>

    </div>

  `;

}


/* =========================================================
   INITIAL LOAD
   ========================================================= */

(async function initAdmin() {

  await Promise.all([
    loadAnalytics(),
    loadUsers(),
    loadPlans(),
    loadSubscriptionUsers(),
    loadSubscriptions(),
    loadTrademarkSearches()
  ]);

  renderSettings();

})();