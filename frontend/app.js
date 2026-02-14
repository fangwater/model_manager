const state = {
  models: [],
  symbolsByModel: {},
  permission: "public",
  autoRefreshHandle: null,
};

const el = {
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
  loadModelFactorsBtn: document.getElementById("loadModelFactorsBtn"),
  loadModelOverviewBtn: document.getElementById("loadModelOverviewBtn"),
  modelFactorsMeta: document.getElementById("modelFactorsMeta"),
  modelFactorsTableBody: document.querySelector("#modelFactorsTable tbody"),
  modelOverviewMeta: document.getElementById("modelOverviewMeta"),
  modelSymbolsTableBody: document.querySelector("#modelSymbolsTable tbody"),
  modelAllFactorsTableBody: document.querySelector("#modelAllFactorsTable tbody"),
  detailMeta: document.getElementById("detailMeta"),
  factorTableBody: document.querySelector("#factorTable tbody"),
  icTableBody: document.querySelector("#icTable tbody"),
};

function setPermission(permission) {
  state.permission = permission || "public";
  el.permissionBadge.textContent = state.permission;
  el.permissionText.textContent = state.permission;
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
    throw new Error(detail);
  }

  return payload;
}

function showDashboard(visible) {
  if (visible) {
    startAutoRefresh();
  } else {
    el.modelsContainer.innerHTML = "";
    el.detailMeta.innerHTML = "";
    clearModelFactorsView();
    clearModelOverviewView();
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
    clearModelFactorsView();
    clearModelOverviewView();
    return;
  }

  const payload = await api(`/api/models/${encodeURIComponent(modelName)}/symbols`);
  state.symbolsByModel[modelName] = payload.items || [];

  const symbols = [...new Set((payload.items || []).map((x) => x.symbol).filter(Boolean))].sort();
  el.selectSymbol.innerHTML = symbols.map((s) => `<option value="${escapeHtml(s)}">${escapeHtml(s)}</option>`).join("");
  await updateGroupSelector();
}

function clearModelFactorsView() {
  el.modelFactorsMeta.textContent = "Select a model and click \"Load Union Factors\" to request all factors across symbols.";
  el.modelFactorsTableBody.innerHTML = "";
}

function clearModelOverviewView() {
  el.modelOverviewMeta.textContent = "Select a model and click \"Load Symbols + Factors\" to view all symbols and all factors.";
  el.modelSymbolsTableBody.innerHTML = "";
  el.modelAllFactorsTableBody.innerHTML = "";
}

function renderModelFactors(payload) {
  const factors = Array.isArray(payload.factors) ? payload.factors : [];
  el.modelFactorsMeta.textContent = `model=${payload.model_name || "-"}, factors=${payload.factor_count || 0}, symbols=${payload.symbol_count || 0}, groups=${payload.group_count || 0}`;

  if (!factors.length) {
    el.modelFactorsTableBody.innerHTML = `
      <tr>
        <td colspan="2">No factors found.</td>
      </tr>
    `;
    return;
  }

  el.modelFactorsTableBody.innerHTML = factors
    .map(
      (factor, index) => `
      <tr>
        <td>${index + 1}</td>
        <td>${escapeHtml(factor)}</td>
      </tr>`
    )
    .join("");
}

async function loadModelFactors() {
  const modelName = el.selectModel.value;
  if (!modelName) {
    clearModelFactorsView();
    return;
  }

  const payload = await api(`/api/models/${encodeURIComponent(modelName)}/factors`);
  renderModelFactors(payload);
}

function renderModelOverview(modelName, symbolsPayload, factorsPayload) {
  const rows = Array.isArray(symbolsPayload.items) ? symbolsPayload.items : [];
  const counts = new Map();
  for (const row of rows) {
    const symbol = String(row.symbol || "").trim();
    if (!symbol) {
      continue;
    }
    counts.set(symbol, (counts.get(symbol) || 0) + 1);
  }
  const symbols = [...counts.entries()].sort((a, b) => a[0].localeCompare(b[0]));

  const factors = Array.isArray(factorsPayload.factors) ? factorsPayload.factors : [];
  el.modelOverviewMeta.textContent = `model=${modelName}, unique_symbols=${symbols.length}, groups=${rows.length}, factors=${factors.length}`;

  if (!symbols.length) {
    el.modelSymbolsTableBody.innerHTML = `
      <tr>
        <td colspan="2">No symbols found.</td>
      </tr>
    `;
  } else {
    el.modelSymbolsTableBody.innerHTML = symbols
      .map(
        ([symbol, groupCount]) => `
      <tr>
        <td>${escapeHtml(symbol)}</td>
        <td>${groupCount}</td>
      </tr>`
      )
      .join("");
  }

  if (!factors.length) {
    el.modelAllFactorsTableBody.innerHTML = `
      <tr>
        <td colspan="2">No factors found.</td>
      </tr>
    `;
    return;
  }

  el.modelAllFactorsTableBody.innerHTML = factors
    .map(
      (factor, index) => `
      <tr>
        <td>${index + 1}</td>
        <td>${escapeHtml(factor)}</td>
      </tr>`
    )
    .join("");
}

async function loadModelOverview() {
  const modelName = el.selectModel.value;
  if (!modelName) {
    clearModelOverviewView();
    return;
  }

  const [symbolsPayload, factorsPayload] = await Promise.all([
    api(`/api/models/${encodeURIComponent(modelName)}/symbols`),
    api(`/api/models/${encodeURIComponent(modelName)}/factors`),
  ]);
  renderModelOverview(modelName, symbolsPayload, factorsPayload);
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

function buildGroupQuery() {
  const groupKey = el.selectGroup.value;
  return groupKey ? `?group_key=${encodeURIComponent(groupKey)}` : "";
}

async function loadDetail() {
  const modelName = el.selectModel.value;
  const symbol = el.selectSymbol.value;
  const query = buildGroupQuery();

  if (!modelName || !symbol) {
    return;
  }

  const detail = await api(
    `/api/models/${encodeURIComponent(modelName)}/symbols/${encodeURIComponent(symbol)}${query}`
  );

  renderMeta(detail);
  renderFactorTable(detail);
  renderIcTable(detail);
}

async function bootstrap() {
  try {
    setPermission("public");
    showDashboard(true);
    await loadModels();
  } catch (err) {
    showAddModelMessage(String(err.message || err), true);
  }
}

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
    clearModelFactorsView();
    clearModelOverviewView();
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

el.loadModelFactorsBtn.addEventListener("click", async () => {
  try {
    await loadModelFactors();
  } catch (err) {
    showAddModelMessage(String(err.message || err), true);
  }
});

el.loadModelOverviewBtn.addEventListener("click", async () => {
  try {
    await loadModelOverview();
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
