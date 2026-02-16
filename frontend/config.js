const state = {
  models: [],
  symbolsByModel: {},
  loadedFactorNames: [],
};

const el = {
  selectModel: document.getElementById("selectModel"),
  selectSymbol: document.getElementById("selectSymbol"),
  selectGroup: document.getElementById("selectGroup"),
  loadFactorStatsBtn: document.getElementById("loadFactorStatsBtn"),
  resetFactorStatsBtn: document.getElementById("resetFactorStatsBtn"),
  saveFactorStatsBtn: document.getElementById("saveFactorStatsBtn"),
  factorStatsMeta: document.getElementById("factorStatsMeta"),
  factorJsonEditor: document.getElementById("factorJsonEditor"),
  configMessage: document.getElementById("configMessage"),
};

function escapeHtml(raw) {
  return String(raw)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

function showMessage(message, isError = false) {
  el.configMessage.textContent = message || "";
  el.configMessage.style.color = isError ? "#be4f22" : "#1f6a90";
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

function clearFactorStatsView() {
  el.factorStatsMeta.textContent =
    'Select model/symbol and click "Load Config" to edit the symbol-level factor JSON.';
  el.factorJsonEditor.value = "";
  state.loadedFactorNames = [];
}

function formatNumber(value) {
  if (value == null || Number.isNaN(Number(value))) {
    return 0;
  }
  return Number(value);
}

function buildFactorConfigs(payload) {
  if (!Array.isArray(payload.factor_configs)) {
    throw new Error("response missing factor_configs array");
  }

  return payload.factor_configs.map((item, idx) => ({
    dim: Number.isInteger(item.dim) ? item.dim : idx,
    factor_name: String(item.factor_name || "").trim(),
    mean_values: Array.isArray(item.mean_values)
      ? item.mean_values.map((value) => formatNumber(value))
      : [],
    variance_values: Array.isArray(item.variance_values)
      ? item.variance_values.map((value) => formatNumber(value))
      : [],
  }));
}

function renderFactorStats(payload) {
  const factorConfigs = buildFactorConfigs(payload);
  state.loadedFactorNames = factorConfigs.map((item) => String(item.factor_name || "")).filter(Boolean);

  el.factorStatsMeta.textContent =
    `model=${payload.model_name || "-"}, symbol=${payload.symbol || "-"}, dim=${payload.factor_count || factorConfigs.length}, updated=${payload.updated_at || "-"}`;

  const editorDoc = {
    model_name: payload.model_name || "",
    symbol: payload.symbol || "",
    group_key: payload.group_key || "",
    factor_configs: factorConfigs,
  };
  el.factorJsonEditor.value = `${JSON.stringify(editorDoc, null, 2)}\n`;
}

function parseEditorJson() {
  const rawText = (el.factorJsonEditor.value || "").trim();
  if (!rawText) {
    throw new Error("JSON editor is empty");
  }

  let parsed;
  try {
    parsed = JSON.parse(rawText);
  } catch (err) {
    throw new Error(`invalid JSON: ${String(err.message || err)}`);
  }

  if (Array.isArray(parsed)) {
    return { factor_configs: parsed };
  }

  if (!parsed || typeof parsed !== "object") {
    throw new Error("JSON must be an object or factor_configs array");
  }

  return parsed;
}

function normalizeDimArray(raw, path, expectedDim) {
  if (!Array.isArray(raw)) {
    throw new Error(`${path} must be an array`);
  }
  if (raw.length !== expectedDim) {
    throw new Error(`${path} must contain exactly ${expectedDim} numeric values`);
  }

  return raw.map((item, idx) => {
    const value = Number(item);
    if (!Number.isFinite(value)) {
      throw new Error(`${path}[${idx}] is not a finite number`);
    }
    return value;
  });
}

function validateFactorConfigs(configs) {
  const dims = configs.map((item) => item.dim);
  const duplicateDims = dims.filter((dim, idx) => dims.indexOf(dim) !== idx);
  if (duplicateDims.length) {
    throw new Error(`duplicated dim in JSON: ${[...new Set(duplicateDims)].join(", ")}`);
  }

  if (!state.loadedFactorNames.length) {
    return;
  }

  if (configs.length !== state.loadedFactorNames.length) {
    throw new Error(
      `factor_configs length mismatch: expected ${state.loadedFactorNames.length}, got ${configs.length}`
    );
  }

  const expectedDims = new Set(state.loadedFactorNames.map((_, idx) => idx));
  const actualDims = new Set(dims);
  const missingDims = [...expectedDims].filter((dim) => !actualDims.has(dim));
  const extraDims = [...actualDims].filter((dim) => !expectedDims.has(dim));
  if (missingDims.length || extraDims.length) {
    const parts = [];
    if (missingDims.length) {
      parts.push(`missing dims: ${missingDims.slice(0, 8).join(", ")}`);
    }
    if (extraDims.length) {
      parts.push(`unknown dims: ${extraDims.slice(0, 8).join(", ")}`);
    }
    throw new Error(parts.join("; "));
  }

  for (const item of configs) {
    const expectedName = state.loadedFactorNames[item.dim];
    if (item.factor_name !== expectedName) {
      throw new Error(
        `factor name mismatch at dim=${item.dim}: expected ${expectedName}, got ${item.factor_name}`
      );
    }
  }
}

function collectFactorStatsPayload() {
  const parsed = parseEditorJson();
  const rawConfigs = parsed.factor_configs;

  if (!Array.isArray(rawConfigs)) {
    throw new Error('JSON must include field "factor_configs" as an array');
  }

  if (!rawConfigs.length) {
    throw new Error("factor_configs cannot be empty");
  }
  const expectedDim = state.loadedFactorNames.length || rawConfigs.length;

  const factorConfigs = rawConfigs.map((item, idx) => {
    if (!item || typeof item !== "object") {
      throw new Error(`factor_configs[${idx}] must be an object`);
    }

    const dim = Number(item.dim);
    if (!Number.isInteger(dim) || dim < 0 || dim >= expectedDim) {
      throw new Error(`factor_configs[${idx}].dim must be an integer in [0, ${expectedDim - 1}]`);
    }

    const factorName = String(item.factor_name || "").trim();
    if (!factorName) {
      throw new Error(`factor_configs[${idx}].factor_name must not be empty`);
    }

    return {
      dim,
      factor_name: factorName,
      mean_values: normalizeDimArray(item.mean_values, `factor_configs[${idx}].mean_values`, expectedDim),
      variance_values: normalizeDimArray(
        item.variance_values,
        `factor_configs[${idx}].variance_values`,
        expectedDim
      ),
    };
  });

  validateFactorConfigs(factorConfigs);

  return {
    factor_configs: factorConfigs,
  };
}

function resetFactorStatsToDefault() {
  const parsed = parseEditorJson();
  const rawConfigs = parsed.factor_configs;
  if (!Array.isArray(rawConfigs) || !rawConfigs.length) {
    throw new Error('JSON must include non-empty "factor_configs" array');
  }
  const expectedDim = state.loadedFactorNames.length || rawConfigs.length;

  parsed.factor_configs = rawConfigs.map((item, idx) => {
    if (!item || typeof item !== "object") {
      throw new Error(`factor_configs[${idx}] must be an object`);
    }

    return {
      ...item,
      mean_values: Array(expectedDim).fill(0.2),
      variance_values: Array(expectedDim).fill(1.0),
    };
  });

  el.factorJsonEditor.value = `${JSON.stringify(parsed, null, 2)}\n`;
}

function buildGroupQuery() {
  const groupKey = el.selectGroup.value;
  return groupKey ? `?group_key=${encodeURIComponent(groupKey)}` : "";
}

async function loadModels() {
  const payload = await api("/api/models");
  state.models = payload.items || [];

  const current = el.selectModel.value;
  const options = state.models
    .map((item) => `<option value="${escapeHtml(item.model_name)}">${escapeHtml(item.model_name)}</option>`)
    .join("");
  el.selectModel.innerHTML = options;

  if (current && state.models.some((item) => item.model_name === current)) {
    el.selectModel.value = current;
  }

  await loadSymbolsForSelectedModel();
}

async function loadSymbolsForSelectedModel() {
  const modelName = el.selectModel.value;
  if (!modelName) {
    el.selectSymbol.innerHTML = "";
    el.selectGroup.innerHTML = "";
    clearFactorStatsView();
    return;
  }

  const payload = await api(`/api/models/${encodeURIComponent(modelName)}/symbols`);
  const rows = payload.items || [];
  state.symbolsByModel[modelName] = rows;

  const symbols = [...new Set(rows.map((item) => item.symbol).filter(Boolean))].sort();
  const symbolCurrent = el.selectSymbol.value;
  el.selectSymbol.innerHTML = symbols
    .map((symbol) => `<option value="${escapeHtml(symbol)}">${escapeHtml(symbol)}</option>`)
    .join("");

  if (symbolCurrent && symbols.includes(symbolCurrent)) {
    el.selectSymbol.value = symbolCurrent;
  }

  await updateGroupSelector();
}

async function updateGroupSelector() {
  const modelName = el.selectModel.value;
  const symbol = el.selectSymbol.value;
  const rows = state.symbolsByModel[modelName] || [];
  const groups = rows
    .filter((item) => item.symbol === symbol)
    .map((item) => item.group_key)
    .filter(Boolean);

  const groupCurrent = el.selectGroup.value;
  el.selectGroup.innerHTML = groups
    .map((groupKey) => `<option value="${escapeHtml(groupKey)}">${escapeHtml(groupKey)}</option>`)
    .join("");

  if (groupCurrent && groups.includes(groupCurrent)) {
    el.selectGroup.value = groupCurrent;
  }
}

async function loadFactorStats() {
  const modelName = el.selectModel.value;
  const symbol = el.selectSymbol.value;
  if (!modelName || !symbol) {
    clearFactorStatsView();
    return;
  }

  const payload = await api(
    `/api/models/${encodeURIComponent(modelName)}/symbols/${encodeURIComponent(symbol)}/factor-stats${buildGroupQuery()}`
  );
  renderFactorStats(payload);
}

async function saveFactorStats() {
  const modelName = el.selectModel.value;
  const symbol = el.selectSymbol.value;
  if (!modelName || !symbol) {
    throw new Error("model/symbol not selected");
  }

  const payload = collectFactorStatsPayload();
  const saved = await api(
    `/api/models/${encodeURIComponent(modelName)}/symbols/${encodeURIComponent(symbol)}/factor-stats${buildGroupQuery()}`,
    {
      method: "PUT",
      body: JSON.stringify(payload),
    }
  );
  renderFactorStats(saved);
  showMessage(`Saved symbol JSON config for ${modelName}/${symbol}.`);
}

async function bootstrap() {
  try {
    await loadModels();
    clearFactorStatsView();
  } catch (err) {
    showMessage(String(err.message || err), true);
  }
}

el.selectModel.addEventListener("change", async () => {
  try {
    await loadSymbolsForSelectedModel();
    clearFactorStatsView();
  } catch (err) {
    showMessage(String(err.message || err), true);
  }
});

el.selectSymbol.addEventListener("change", async () => {
  try {
    await updateGroupSelector();
    clearFactorStatsView();
  } catch (err) {
    showMessage(String(err.message || err), true);
  }
});

el.selectGroup.addEventListener("change", () => {
  clearFactorStatsView();
});

el.loadFactorStatsBtn.addEventListener("click", async () => {
  try {
    await loadFactorStats();
  } catch (err) {
    showMessage(String(err.message || err), true);
  }
});

el.resetFactorStatsBtn.addEventListener("click", () => {
  try {
    resetFactorStatsToDefault();
  } catch (err) {
    showMessage(String(err.message || err), true);
  }
});

el.saveFactorStatsBtn.addEventListener("click", async () => {
  try {
    await saveFactorStats();
  } catch (err) {
    showMessage(String(err.message || err), true);
  }
});

bootstrap();
