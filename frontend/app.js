const state = {
  token: localStorage.getItem("model_manager_token") || "",
  models: [],
  symbolsByModel: {},
  permission: "guest",
  autoRefreshHandle: null,
};

const el = {
  authHint: document.getElementById("authHint"),
  authMessage: document.getElementById("authMessage"),
  bootstrapBox: document.getElementById("bootstrapBox"),
  loginBox: document.getElementById("loginBox"),
  bootstrapForm: document.getElementById("bootstrapForm"),
  loginForm: document.getElementById("loginForm"),
  dashboard: document.getElementById("dashboard"),
  permissionBadge: document.getElementById("permissionBadge"),
  permissionText: document.getElementById("permissionText"),
  modelCount: document.getElementById("modelCount"),
  symbolCount: document.getElementById("symbolCount"),
  addModelForm: document.getElementById("addModelForm"),
  addModelMessage: document.getElementById("addModelMessage"),
  modelsContainer: document.getElementById("modelsContainer"),
  refreshModelsBtn: document.getElementById("refreshModelsBtn"),
  selectModel: document.getElementById("selectModel"),
  selectSymbol: document.getElementById("selectSymbol"),
  selectGroup: document.getElementById("selectGroup"),
  loadDetailBtn: document.getElementById("loadDetailBtn"),
  detailMeta: document.getElementById("detailMeta"),
  factorTableBody: document.querySelector("#factorTable tbody"),
  icTableBody: document.querySelector("#icTable tbody"),
};

function setToken(token) {
  state.token = token;
  if (token) {
    localStorage.setItem("model_manager_token", token);
  } else {
    localStorage.removeItem("model_manager_token");
  }
}

function setPermission(permission) {
  state.permission = permission || "guest";
  el.permissionBadge.textContent = state.permission;
  el.permissionText.textContent = state.permission;
}

function showAuthMessage(message, isError = false) {
  el.authMessage.textContent = message || "";
  el.authMessage.style.color = isError ? "#be4f22" : "#1f6a90";
}

function showAddModelMessage(message, isError = false) {
  el.addModelMessage.textContent = message || "";
  el.addModelMessage.style.color = isError ? "#be4f22" : "#1f6a90";
}

async function api(path, options = {}) {
  const headers = {
    "Content-Type": "application/json",
    ...(options.headers || {}),
  };
  if (state.token) {
    headers.Authorization = `Bearer ${state.token}`;
  }

  const resp = await fetch(path, {
    ...options,
    headers,
  });

  let payload = {};
  const text = await resp.text();
  if (text) {
    try {
      payload = JSON.parse(text);
    } catch {
      payload = { detail: text };
    }
  }

  if (!resp.ok) {
    const detail = payload.detail || payload.message || `HTTP ${resp.status}`;
    if (resp.status === 401) {
      setToken("");
      setPermission("guest");
      showDashboard(false);
    }
    throw new Error(detail);
  }

  return payload;
}

function showDashboard(visible) {
  if (visible) {
    el.dashboard.classList.remove("hidden");
    startAutoRefresh();
  } else {
    el.dashboard.classList.add("hidden");
    el.modelsContainer.innerHTML = "";
    el.detailMeta.innerHTML = "";
    el.factorTableBody.innerHTML = "";
    el.icTableBody.innerHTML = "";
    stopAutoRefresh();
  }
}

function startAutoRefresh() {
  if (state.autoRefreshHandle !== null) {
    return;
  }
  state.autoRefreshHandle = window.setInterval(async () => {
    if (!state.token) {
      return;
    }
    try {
      await loadModels();
    } catch (_) {
      // Keep silent; explicit actions still surface errors.
    }
  }, 15000);
}

function stopAutoRefresh() {
  if (state.autoRefreshHandle === null) {
    return;
  }
  window.clearInterval(state.autoRefreshHandle);
  state.autoRefreshHandle = null;
}

function updateAuthPanels(initialized) {
  el.bootstrapBox.classList.toggle("hidden", initialized);
  el.loginBox.classList.toggle("hidden", !initialized);
  if (initialized) {
    el.authHint.textContent = "Password is initialized. Login to continue.";
  } else {
    el.authHint.textContent = "No password configured. Initialize once.";
  }
}

function renderModels() {
  el.modelsContainer.innerHTML = "";
  if (!state.models.length) {
    el.modelsContainer.innerHTML = '<p class="text-muted">No models registered.</p>';
  }

  let symbolTotal = 0;

  for (const item of state.models) {
    symbolTotal += item.symbol_count || 0;

    const card = document.createElement("article");
    card.className = "model-item";

    const warningsText = Array.isArray(item.warnings) && item.warnings.length
      ? `warnings: ${item.warnings.length}`
      : "warnings: 0";

    card.innerHTML = `
      <h4>${escapeHtml(item.model_name)}</h4>
      <div class="model-meta">
        <div>symbols: ${item.symbol_count} | groups: ${item.group_count}</div>
        <div>scanned: ${escapeHtml(item.scanned_at || "-")}</div>
        <div>path: ${escapeHtml(item.root_path)}</div>
        <div>${warningsText}</div>
      </div>
      <div style="margin-top:8px; display:flex; gap:8px;">
        <button type="button" data-action="open" data-model="${encodeURIComponent(item.model_name)}">Open</button>
        <button type="button" class="btn-ghost" data-action="refresh" data-model="${encodeURIComponent(item.model_name)}">Rescan</button>
      </div>
    `;

    el.modelsContainer.appendChild(card);
  }

  el.modelCount.textContent = String(state.models.length);
  el.symbolCount.textContent = String(symbolTotal);

  const current = el.selectModel.value;
  const options = state.models
    .map(
      (item) =>
        `<option value="${escapeHtml(item.model_name)}">${escapeHtml(item.model_name)} (${item.symbol_count})</option>`
    )
    .join("");

  el.selectModel.innerHTML = options;
  if (current && state.models.some((x) => x.model_name === current)) {
    el.selectModel.value = current;
  }
}

function escapeHtml(raw) {
  return String(raw)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

async function loadModels() {
  const payload = await api("/api/models");
  state.models = payload.items || [];
  renderModels();
  await loadSymbolsForSelectedModel();
}

async function loadSymbolsForSelectedModel() {
  const modelName = el.selectModel.value;
  if (!modelName) {
    el.selectSymbol.innerHTML = "";
    el.selectGroup.innerHTML = "";
    return;
  }

  const payload = await api(`/api/models/${encodeURIComponent(modelName)}/symbols`);
  state.symbolsByModel[modelName] = payload.items || [];

  const symbols = [...new Set((payload.items || []).map((x) => x.symbol).filter(Boolean))].sort();
  el.selectSymbol.innerHTML = symbols.map((s) => `<option value="${escapeHtml(s)}">${escapeHtml(s)}</option>`).join("");
  await updateGroupSelector();
}

async function updateGroupSelector() {
  const modelName = el.selectModel.value;
  const symbol = el.selectSymbol.value;

  const rows = state.symbolsByModel[modelName] || [];
  const groups = rows
    .filter((x) => x.symbol === symbol)
    .map((x) => x.group_key)
    .filter(Boolean);

  el.selectGroup.innerHTML = groups
    .map((g) => `<option value="${escapeHtml(g)}">${escapeHtml(g)}</option>`)
    .join("");
}

function renderMeta(detail) {
  const items = [
    ["Model", detail.model_name],
    ["Symbol", detail.symbol],
    ["Group", detail.group_key],
    ["Return", detail.return_name || "-"],
    ["Feature Dim", detail.feature_dim],
    ["Factors", detail.factor_count],
    ["Train Start", detail.train_start_date || "-"],
    ["Train End", detail.train_end_date || "-"],
    ["Train Samples", detail.train_samples || "-"],
    ["Payload Ready", detail.grpc_ready ? "yes" : "no"],
  ];

  el.detailMeta.innerHTML = items
    .map(
      ([k, v]) => `
      <div class="meta-pill">
        <p class="k">${escapeHtml(k)}</p>
        <p class="v">${escapeHtml(v ?? "")}</p>
      </div>`
    )
    .join("");
}

function renderFactorTable(detail) {
  const rows = detail.dim_factors || [];
  el.factorTableBody.innerHTML = rows
    .map(
      (item) => `
      <tr>
        <td>${escapeHtml(item.dim)}</td>
        <td>${escapeHtml(item.factor_name || "")}</td>
        <td>${item.kendall_tau == null ? "" : escapeHtml(item.kendall_tau)}</td>
      </tr>`
    )
    .join("");
}

function renderIcTable(detail) {
  const rows = detail.ic_rows || [];
  el.icTableBody.innerHTML = rows
    .map(
      (item) => `
      <tr>
        <td>${escapeHtml(item.factor_name || "")}</td>
        <td>${item.Kendall_tau == null ? "" : escapeHtml(item.Kendall_tau)}</td>
      </tr>`
    )
    .join("");
}

async function loadDetail() {
  const modelName = el.selectModel.value;
  const symbol = el.selectSymbol.value;
  const groupKey = el.selectGroup.value;

  if (!modelName || !symbol) {
    return;
  }

  const query = groupKey ? `?group_key=${encodeURIComponent(groupKey)}` : "";
  const detail = await api(
    `/api/models/${encodeURIComponent(modelName)}/symbols/${encodeURIComponent(symbol)}${query}`
  );

  renderMeta(detail);
  renderFactorTable(detail);
  renderIcTable(detail);
}

async function bootstrap() {
  try {
    const status = await api("/api/auth/status", { headers: {} });
    updateAuthPanels(Boolean(status.initialized));

    if (state.token) {
      const me = await api("/api/me");
      setPermission(me.permission || "readonly");
      showDashboard(true);
      await loadModels();
    }
  } catch (err) {
    showAuthMessage(String(err.message || err), true);
  }
}

el.bootstrapForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  const password = document.getElementById("bootstrapPassword").value;
  try {
    await api("/api/auth/bootstrap", {
      method: "POST",
      body: JSON.stringify({ password }),
      headers: {},
    });
    showAuthMessage("Password initialized. Please login.");
    updateAuthPanels(true);
    event.target.reset();
  } catch (err) {
    showAuthMessage(String(err.message || err), true);
  }
});

el.loginForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  const password = document.getElementById("loginPassword").value;
  try {
    const res = await api("/api/auth/login", {
      method: "POST",
      body: JSON.stringify({ password }),
      headers: {},
    });
    setToken(res.token);
    setPermission(res.permission || "readonly");
    showAuthMessage("Login success.");
    showDashboard(true);
    event.target.reset();
    await loadModels();
  } catch (err) {
    showAuthMessage(String(err.message || err), true);
  }
});

el.addModelForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  const modelName = document.getElementById("modelName").value.trim();
  const rootPath = document.getElementById("modelPath").value.trim();

  try {
    const res = await api("/api/models", {
      method: "POST",
      body: JSON.stringify({ model_name: modelName, root_path: rootPath }),
    });

    let msg = `Registered ${res.model_name}. symbols=${res.symbol_count}, groups=${res.group_count}.`;
    if (Array.isArray(res.warnings) && res.warnings.length) {
      msg += ` warnings=${res.warnings.length}`;
    }
    showAddModelMessage(msg, false);
    event.target.reset();
    await loadModels();
  } catch (err) {
    showAddModelMessage(String(err.message || err), true);
  }
});

el.refreshModelsBtn.addEventListener("click", async () => {
  try {
    await loadModels();
    showAddModelMessage("Model list refreshed.");
  } catch (err) {
    showAddModelMessage(String(err.message || err), true);
  }
});

el.selectModel.addEventListener("change", async () => {
  try {
    await loadSymbolsForSelectedModel();
  } catch (err) {
    showAddModelMessage(String(err.message || err), true);
  }
});

el.selectSymbol.addEventListener("change", async () => {
  await updateGroupSelector();
});

el.loadDetailBtn.addEventListener("click", async () => {
  try {
    await loadDetail();
  } catch (err) {
    showAddModelMessage(String(err.message || err), true);
  }
});

el.modelsContainer.addEventListener("click", async (event) => {
  const target = event.target.closest("button");
  if (!target) {
    return;
  }
  const action = target.dataset.action;
  const model = decodeURIComponent(target.dataset.model || "");
  if (!action || !model) {
    return;
  }

  try {
    if (action === "open") {
      el.selectModel.value = model;
      await loadSymbolsForSelectedModel();
      await loadDetail();
      return;
    }

    if (action === "refresh") {
      await api(`/api/models/${encodeURIComponent(model)}/refresh`, { method: "POST" });
      await loadModels();
      showAddModelMessage(`Rescanned ${model}.`);
    }
  } catch (err) {
    showAddModelMessage(String(err.message || err), true);
  }
});

bootstrap();
