const state = {
  models: [],
  symbolsByModel: {},
  loadedDim: 0,
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
    'Select model/symbol and click "Load Config" to edit JSON: {"SYMBOL": {"factor_names": [...], "mean_values": [...], "variance_values": [...]}}';
  el.factorJsonEditor.value = "";
  state.loadedDim = 0;
  state.loadedFactorNames = [];
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

  if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) {
    throw new Error("JSON must be an object keyed by symbol");
  }

  return parsed;
}

function normalizeNumericArray(raw, path) {
  if (!Array.isArray(raw)) {
    throw new Error(`${path} must be an array`);
  }

  return raw.map((item, idx) => {
    const value = Number(item);
    if (!Number.isFinite(value)) {
      throw new Error(`${path}[${idx}] is not a finite number`);
    }
    return value;
  });
}

function getSymbolEntry(payload, selectedSymbol) {
  if (!payload || typeof payload !== "object" || Array.isArray(payload)) {
    throw new Error("response must be object keyed by symbol");
  }

  let key = selectedSymbol;
  if (!Object.prototype.hasOwnProperty.call(payload, key)) {
    const upper = String(selectedSymbol || "").toUpperCase();
    if (Object.prototype.hasOwnProperty.call(payload, upper)) {
      key = upper;
    } else {
      const keys = Object.keys(payload);
      if (keys.length === 1) {
        key = keys[0];
      } else {
        throw new Error(`response missing symbol key '${selectedSymbol}'`);
      }
    }
  }

  const entry = payload[key];
  if (!entry || typeof entry !== "object" || Array.isArray(entry)) {
    throw new Error(`symbol '${key}' config must be an object`);
  }

  const meanValues = normalizeNumericArray(entry.mean_values, `${key}.mean_values`);
  const varianceValues = normalizeNumericArray(entry.variance_values, `${key}.variance_values`);
  let factorNames = [];
  if (entry.factor_names != null) {
    if (!Array.isArray(entry.factor_names)) {
      throw new Error(`${key}.factor_names must be an array`);
    }
    factorNames = entry.factor_names.map((item, idx) => {
      const value = String(item || "").trim();
      if (!value) {
        throw new Error(`${key}.factor_names[${idx}] must not be empty`);
      }
      return value;
    });
  }

  if (meanValues.length !== varianceValues.length) {
    throw new Error(
      `${key} mean_values and variance_values length mismatch: ${meanValues.length} vs ${varianceValues.length}`
    );
  }
  if (factorNames.length && factorNames.length !== meanValues.length) {
    throw new Error(
      `${key} factor_names length mismatch: factor_names=${factorNames.length}, dim=${meanValues.length}`
    );
  }

  return {
    symbol: key,
    factor_names: factorNames,
    mean_values: meanValues,
    variance_values: varianceValues,
  };
}

function renderFactorStats(payload) {
  const selectedSymbol = el.selectSymbol.value;
  const stats = getSymbolEntry(payload, selectedSymbol);
  state.loadedDim = stats.mean_values.length;
  state.loadedFactorNames = stats.factor_names.length
    ? stats.factor_names
    : Array.from({ length: state.loadedDim }, (_, idx) => `factor_${idx}`);

  el.factorStatsMeta.textContent =
    `model=${el.selectModel.value || "-"}, symbol=${stats.symbol || "-"}, dim=${state.loadedDim}`;

  const editorDoc = {
    [stats.symbol]: {
      factor_names: state.loadedFactorNames,
      mean_values: stats.mean_values,
      variance_values: stats.variance_values,
    },
  };
  el.factorJsonEditor.value = `${JSON.stringify(editorDoc, null, 2)}\n`;
}

function collectFactorStatsPayload() {
  const selectedSymbol = el.selectSymbol.value;
  if (!selectedSymbol) {
    throw new Error("symbol not selected");
  }

  const parsed = parseEditorJson();
  if (!Object.prototype.hasOwnProperty.call(parsed, selectedSymbol)) {
    throw new Error(`root JSON key must be selected symbol '${selectedSymbol}'`);
  }

  const stats = getSymbolEntry(parsed, selectedSymbol);
  const expectedDim = state.loadedDim || stats.mean_values.length;

  if (stats.mean_values.length !== expectedDim || stats.variance_values.length !== expectedDim) {
    throw new Error(
      `array length must equal dim=${expectedDim}; got mean=${stats.mean_values.length}, variance=${stats.variance_values.length}`
    );
  }
  const expectedFactorNames = state.loadedFactorNames.length
    ? state.loadedFactorNames
    : Array.from({ length: expectedDim }, (_, idx) => `factor_${idx}`);
  const providedFactorNames = stats.factor_names.length
    ? stats.factor_names
    : expectedFactorNames;
  if (providedFactorNames.length !== expectedDim) {
    throw new Error(
      `factor_names length must equal dim=${expectedDim}; got ${providedFactorNames.length}`
    );
  }
  for (let idx = 0; idx < expectedDim; idx += 1) {
    if (providedFactorNames[idx] !== expectedFactorNames[idx]) {
      throw new Error(
        `factor_names[${idx}] mismatch: expected '${expectedFactorNames[idx]}', got '${providedFactorNames[idx]}'`
      );
    }
  }

  return {
    [selectedSymbol]: {
      factor_names: providedFactorNames,
      mean_values: stats.mean_values,
      variance_values: stats.variance_values,
    },
  };
}

function resetFactorStatsToDefault() {
  const selectedSymbol = el.selectSymbol.value;
  if (!selectedSymbol) {
    throw new Error("symbol not selected");
  }

  const parsed = parseEditorJson();
  if (!Object.prototype.hasOwnProperty.call(parsed, selectedSymbol)) {
    throw new Error(`root JSON key must be selected symbol '${selectedSymbol}'`);
  }

  const stats = getSymbolEntry(parsed, selectedSymbol);
  const dim = state.loadedDim || stats.mean_values.length;
  const factorNames = stats.factor_names.length
    ? stats.factor_names
    : state.loadedFactorNames.length
      ? state.loadedFactorNames
      : Array.from({ length: dim }, (_, idx) => `factor_${idx}`);
  parsed[selectedSymbol] = {
    factor_names: factorNames,
    mean_values: Array(dim).fill(0.2),
    variance_values: Array(dim).fill(1.0),
  };
  el.factorJsonEditor.value = `${JSON.stringify(parsed, null, 2)}\n`;
  state.loadedDim = dim;
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
