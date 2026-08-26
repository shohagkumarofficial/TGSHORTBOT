(function () {
  "use strict";

  const tg = window.Telegram && window.Telegram.WebApp ? window.Telegram.WebApp : null;
  const CFG = window.TGSHORT_CONFIG || {};

  let INIT_DATA = "";
  let CURRENT_USER = null;
  let IS_OWNER = false;
  let TASKS_CACHE = [];

  const el = (id) => document.getElementById(id);

  // ---------------------------------------------------------------------
  // Telegram bootstrap
  // ---------------------------------------------------------------------
  function bootstrap() {
    if (!tg) {
      showError();
      return;
    }
    tg.ready();
    tg.expand();
    try {
      tg.setHeaderColor("#0B0F1A");
      tg.setBackgroundColor("#0B0F1A");
    } catch (e) { /* পুরনো ক্লায়েন্টে সাপোর্ট নাও থাকতে পারে */ }

    INIT_DATA = tg.initData || "";
    if (!INIT_DATA) {
      showError();
      return;
    }
    authenticate();
  }

  function showError() {
    el("loadingState").classList.add("hidden");
    el("errorState").classList.remove("hidden");
  }

  // ---------------------------------------------------------------------
  // API helper — X-Telegram-Init-Data হেডারে initData পাঠানো হয়
  // ---------------------------------------------------------------------
  async function api(path, opts) {
    opts = opts || {};
    const headers = Object.assign(
      { "X-Telegram-Init-Data": INIT_DATA },
      opts.body ? { "Content-Type": "application/json" } : {},
      opts.headers || {}
    );
    const res = await fetch(path, {
      method: opts.method || "GET",
      headers,
      body: opts.body ? JSON.stringify(opts.body) : undefined,
    });
    let data;
    try {
      data = await res.json();
    } catch (e) {
      data = { ok: false, error: "bad_response" };
    }
    return data;
  }

  function ownerQueryUrl(path) {
    return path + "?init_data=" + encodeURIComponent(INIT_DATA);
  }

  // ---------------------------------------------------------------------
  // Auth + first load
  // ---------------------------------------------------------------------
  async function authenticate() {
    const res = await api("/api/auth/", { method: "POST" });
    if (!res.ok) {
      showError();
      return;
    }
    CURRENT_USER = res.user;
    IS_OWNER = !!res.is_owner;

    el("loadingState").classList.add("hidden");
    el("mainContent").classList.remove("hidden");
    el("bottomNav").classList.remove("hidden");
    if (IS_OWNER) el("adminNavBtn").classList.remove("hidden");

    updateCoinDisplays(CURRENT_USER.coins);
    bindNav();
    bindForms();

    await loadTasks();
    await loadMyWithdrawals();
    if (IS_OWNER) await loadAdminData();
  }

  function updateCoinDisplays(coins) {
    el("coinBalance").textContent = coins;
    el("walletBalance").textContent = coins;
  }

  // ---------------------------------------------------------------------
  // Tabs
  // ---------------------------------------------------------------------
  function bindNav() {
    document.querySelectorAll(".nav-btn").forEach((btn) => {
      btn.addEventListener("click", () => {
        const tabName = btn.getAttribute("data-tab");
        document.querySelectorAll(".nav-btn").forEach((b) => b.classList.remove("active"));
        btn.classList.add("active");
        document.querySelectorAll(".tab-panel").forEach((p) => p.classList.remove("active"));
        el("tab-" + tabName).classList.add("active");
        if (tg && tg.HapticFeedback) tg.HapticFeedback.impactOccurred("light");
      });
    });
    el("coinPill").addEventListener("click", () => {
      document.querySelector('.nav-btn[data-tab="wallet"]').click();
    });
  }

  // ---------------------------------------------------------------------
  // Tasks
  // ---------------------------------------------------------------------
  const TASK_ICONS = { link: "🔗", channel: "📢", ad: "🎬", custom: "⭐" };

  async function loadTasks() {
    const res = await api("/api/tasks/");
    if (!res.ok) return;
    TASKS_CACHE = res.tasks;
    renderTasks();
  }

  function renderTasks() {
    const list = el("taskList");
    list.innerHTML = "";
    const completed = new Set((CURRENT_USER && CURRENT_USER.completed_tasks) || []);

    if (!TASKS_CACHE.length) {
      el("taskEmpty").classList.remove("hidden");
      return;
    }
    el("taskEmpty").classList.add("hidden");

    TASKS_CACHE.forEach((task) => {
      const done = completed.has(task.id);
      const card = document.createElement("div");
      card.className = "task-card";
      card.innerHTML = `
        <div class="task-icon">${TASK_ICONS[task.type] || "⭐"}</div>
        <div class="task-body">
          <p class="task-title">${escapeHtml(task.title)}</p>
          <p class="task-desc">${escapeHtml(task.description || "")}</p>
          <span class="task-reward">🪙 ${task.reward} কয়েন</span>
        </div>
        <div class="task-action"></div>
      `;
      const actionSlot = card.querySelector(".task-action");
      actionSlot.appendChild(buildTaskButton(task, done));
      list.appendChild(card);
    });
  }

  function buildTaskButton(task, done) {
    const btn = document.createElement("button");
    btn.className = "btn " + (done ? "btn-secondary" : "btn-primary");
    btn.disabled = done;
    btn.textContent = done ? "সম্পন্ন ✓" : actionLabel(task);
    if (!done) {
      btn.addEventListener("click", () => handleTaskAction(task, btn));
    }
    return btn;
  }

  function actionLabel(task) {
    if (task.verify_type === "channel_join") return "জয়েন করুন";
    if (task.verify_type === "ad_watch") return "অ্যাড দেখুন";
    return "শুরু করুন";
  }

  function handleTaskAction(task, btn) {
    if (task.verify_type === "channel_join") {
      if (task.link) tg && tg.openTelegramLink ? tg.openTelegramLink(task.link) : window.open(task.link, "_blank");
      // ইউজার জয়েন করার সময় দিয়ে তারপর claim করতে বলা হচ্ছে
      btn.textContent = "যাচাই করুন";
      btn.onclick = () => claimTask(task.id, btn);
      return;
    }
    if (task.verify_type === "ad_watch") {
      btn.disabled = true;
      btn.textContent = "লোড হচ্ছে…";
      runAd(task.ad_provider)
        .then(() => claimTask(task.id, btn))
        .catch(() => {
          btn.disabled = false;
          btn.textContent = "আবার চেষ্টা করুন";
        });
      return;
    }
    // manual: লিংক খুলে দিয়ে সরাসরি claim করার সুযোগ দেওয়া হচ্ছে
    if (task.link) window.open(task.link, "_blank");
    btn.textContent = "কয়েন নিন";
    btn.onclick = () => claimTask(task.id, btn);
  }

  function runAd(provider) {
    if (provider === "gigapub" && typeof window.showGiga === "function") {
      return window.showGiga();
    }
    const fnName = "show_" + (CFG.monetagZone || "");
    if (typeof window[fnName] === "function") {
      return window[fnName]();
    }
    return Promise.reject(new Error("ad_sdk_unavailable"));
  }

  async function claimTask(taskId, btn) {
    btn.disabled = true;
    btn.textContent = "…";
    const res = await api(`/api/tasks/${taskId}/claim/`, { method: "POST", body: {} });
    if (res.ok) {
      CURRENT_USER.coins = res.coins;
      CURRENT_USER.completed_tasks.push(taskId);
      updateCoinDisplays(res.coins);
      if (tg && tg.HapticFeedback) tg.HapticFeedback.notificationOccurred("success");
      renderTasks();
    } else {
      btn.disabled = false;
      btn.textContent = res.error === "not_joined" ? "এখনো জয়েন করেননি" : "আবার চেষ্টা করুন";
    }
  }

  // ---------------------------------------------------------------------
  // Wallet
  // ---------------------------------------------------------------------
  function bindForms() {
    el("withdrawForm").addEventListener("submit", async (e) => {
      e.preventDefault();
      const amount = parseInt(el("withdrawAmount").value, 10);
      const info = el("withdrawInfo").value.trim();
      const msg = el("withdrawMsg");
      msg.textContent = "";
      if (!amount || amount <= 0 || !info) {
        msg.textContent = "সঠিক তথ্য দিন।";
        msg.className = "form-msg err";
        return;
      }
      const res = await api("/api/withdraw/", {
        method: "POST",
        body: { amount, payment_info: info },
      });
      if (res.ok) {
        msg.textContent = "রিকোয়েস্ট পাঠানো হয়েছে, অনুমোদনের অপেক্ষায় আছে।";
        msg.className = "form-msg ok";
        CURRENT_USER.coins = res.coins;
        updateCoinDisplays(res.coins);
        el("withdrawForm").reset();
        loadMyWithdrawals();
      } else {
        msg.textContent = res.error === "insufficient_coins" ? "পর্যাপ্ত কয়েন নেই।" : "রিকোয়েস্ট ব্যর্থ হয়েছে।";
        msg.className = "form-msg err";
      }
    });

    if (IS_OWNER) bindAdminForms();
  }

  async function loadMyWithdrawals() {
    const res = await api("/api/withdrawals/");
    const box = el("withdrawHistory");
    box.innerHTML = "";
    if (!res.ok || !res.withdrawals.length) {
      box.innerHTML = '<p class="empty-note">এখনো কোনো উইথড্র রিকোয়েস্ট নেই।</p>';
      return;
    }
    res.withdrawals.forEach((w) => box.appendChild(withdrawItemEl(w)));
  }

  function withdrawItemEl(w) {
    const div = document.createElement("div");
    div.className = "withdraw-item";
    const statusClass = { pending: "status-pending", approved: "status-approved", rejected: "status-rejected" }[w.status];
    const statusText = { pending: "পেন্ডিং", approved: "অনুমোদিত", rejected: "বাতিল" }[w.status];
    div.innerHTML = `
      <span>🪙 ${w.amount} — ${escapeHtml(w.payment_info)}</span>
      <span class="status-pill ${statusClass}">${statusText}</span>
    `;
    return div;
  }

  // ---------------------------------------------------------------------
  // Admin
  // ---------------------------------------------------------------------
  function bindAdminForms() {
    el("taskVerifyType").addEventListener("change", (e) => {
      const v = e.target.value;
      el("linkField").classList.toggle("hidden", v === "channel_join");
      el("chatIdField").classList.toggle("hidden", v !== "channel_join");
      el("adProviderField").classList.toggle("hidden", v !== "ad_watch");
    });

    el("taskForm").addEventListener("submit", async (e) => {
      e.preventDefault();
      const verifyType = el("taskVerifyType").value;
      const payload = {
        title: el("taskTitle").value.trim(),
        description: el("taskDesc").value.trim(),
        reward: parseInt(el("taskReward").value, 10) || 0,
        verify_type: verifyType,
        type: verifyType === "channel_join" ? "channel" : verifyType === "ad_watch" ? "ad" : "link",
        link: el("taskLink").value.trim(),
        chat_id: el("taskChatId").value.trim(),
        ad_provider: el("taskAdProvider").value,
      };
      const msg = el("taskFormMsg");
      const res = await apiAdmin("/admin-api/tasks/create/", { method: "POST", body: payload });
      if (res.ok) {
        msg.textContent = "টাস্ক তৈরি হয়েছে।";
        msg.className = "form-msg ok";
        el("taskForm").reset();
        loadTasks();
        loadAdminData();
      } else {
        msg.textContent = "ব্যর্থ হয়েছে।";
        msg.className = "form-msg err";
      }
    });

    el("backupBtn").addEventListener("click", () => {
      window.open(ownerQueryUrl("/admin-api/backup/"), "_blank");
    });

    el("restoreFile").addEventListener("change", async (e) => {
      const file = e.target.files[0];
      if (!file) return;
      const formData = new FormData();
      formData.append("file", file);
      const msg = el("restoreMsg");
      try {
        const res = await fetch(ownerQueryUrl("/admin-api/restore/"), {
          method: "POST",
          body: formData,
        });
        const data = await res.json();
        if (data.ok) {
          msg.textContent = "রিস্টোর সম্পন্ন হয়েছে।";
          msg.className = "form-msg ok";
          await refreshUser();
          loadTasks();
          loadAdminData();
        } else {
          msg.textContent = "রিস্টোর ব্যর্থ হয়েছে।";
          msg.className = "form-msg err";
        }
      } catch (err) {
        msg.textContent = "রিস্টোর ব্যর্থ হয়েছে।";
        msg.className = "form-msg err";
      }
    });
  }

  async function apiAdmin(path, opts) {
    return api(path, opts);
  }

  async function refreshUser() {
    const res = await api("/api/me/");
    if (res.ok) {
      CURRENT_USER = res.user;
      updateCoinDisplays(res.user.coins);
    }
  }

  async function loadAdminData() {
    const [statsRes, tasksRes, wRes] = await Promise.all([
      apiAdmin("/admin-api/stats/"),
      apiAdmin("/admin-api/tasks/"),
      apiAdmin("/admin-api/withdrawals/?status=pending"),
    ]);

    if (statsRes.ok) renderAdminStats(statsRes.stats);
    if (tasksRes.ok) renderAdminTasks(tasksRes.tasks);
    if (wRes.ok) renderAdminWithdrawals(wRes.withdrawals);
  }

  function renderAdminStats(stats) {
    const map = [
      ["মোট ইউজার", stats.total_users],
      ["সক্রিয় টাস্ক", stats.active_tasks],
      ["পেন্ডিং উইথড্র", stats.pending_withdrawals],
      ["মোট কয়েন", stats.total_coins_in_circulation],
    ];
    el("adminStats").innerHTML = map
      .map(([label, num]) => `<div class="stat-box"><div class="num">${num}</div><div class="label">${label}</div></div>`)
      .join("");
  }

  function renderAdminTasks(tasks) {
    const box = el("adminTaskList");
    box.innerHTML = "";
    tasks.forEach((task) => {
      const card = document.createElement("div");
      card.className = "task-card";
      card.innerHTML = `
        <div class="task-icon">${TASK_ICONS[task.type] || "⭐"}</div>
        <div class="task-body">
          <p class="task-title">${escapeHtml(task.title)} ${task.active ? "" : "(নিষ্ক্রিয়)"}</p>
          <p class="task-desc">🪙 ${task.reward} · ${task.claims_count} জন করেছে</p>
        </div>
      `;
      const actions = document.createElement("div");
      actions.className = "btn-row";

      const toggleBtn = document.createElement("button");
      toggleBtn.className = "btn btn-secondary";
      toggleBtn.textContent = task.active ? "বন্ধ করুন" : "চালু করুন";
      toggleBtn.addEventListener("click", async () => {
        await apiAdmin(`/admin-api/tasks/${task.id}/update/`, {
          method: "POST",
          body: { active: !task.active },
        });
        loadTasks();
        loadAdminData();
      });

      const delBtn = document.createElement("button");
      delBtn.className = "btn btn-danger";
      delBtn.textContent = "ডিলিট";
      delBtn.addEventListener("click", async () => {
        await apiAdmin(`/admin-api/tasks/${task.id}/delete/`, { method: "POST" });
        loadTasks();
        loadAdminData();
      });

      actions.appendChild(toggleBtn);
      actions.appendChild(delBtn);
      card.appendChild(actions);
      box.appendChild(card);
    });
  }

  function renderAdminWithdrawals(withdrawals) {
    const box = el("adminWithdrawList");
    box.innerHTML = "";
    if (!withdrawals.length) {
      box.innerHTML = '<p class="empty-note">কোনো পেন্ডিং রিকোয়েস্ট নেই।</p>';
      return;
    }
    withdrawals.forEach((w) => {
      const div = document.createElement("div");
      div.className = "withdraw-item";
      div.innerHTML = `<span>🪙 ${w.amount} — tg:${w.tg_id} — ${escapeHtml(w.payment_info)}</span>`;
      const actions = document.createElement("div");
      actions.className = "btn-row";

      const approveBtn = document.createElement("button");
      approveBtn.className = "btn btn-teal";
      approveBtn.textContent = "Approve";
      approveBtn.addEventListener("click", async () => {
        await apiAdmin(`/admin-api/withdrawals/${w.id}/approve/`, { method: "POST" });
        loadAdminData();
      });

      const rejectBtn = document.createElement("button");
      rejectBtn.className = "btn btn-danger";
      rejectBtn.textContent = "Reject";
      rejectBtn.addEventListener("click", async () => {
        await apiAdmin(`/admin-api/withdrawals/${w.id}/reject/`, { method: "POST" });
        loadAdminData();
      });

      actions.appendChild(approveBtn);
      actions.appendChild(rejectBtn);
      div.appendChild(actions);
      box.appendChild(div);
    });
  }

  // ---------------------------------------------------------------------
  // Utils
  // ---------------------------------------------------------------------
  function escapeHtml(str) {
    const d = document.createElement("div");
    d.textContent = str == null ? "" : str;
    return d.innerHTML;
  }

  document.addEventListener("DOMContentLoaded", bootstrap);
})();
