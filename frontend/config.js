const state = {
  models: [],
  symbolsByModel: {},
};

const el = {
  selectModel: document.getElementById("selectModel"),
  selectSymbol: document.getElementById("selectSymbol"),
  selectGroup: document.getElementById("selectGroup"),
  loadFactorStatsBtn: document.getElementById("loadFactorStatsBtn"),
  resetFactorStatsBtn: document.getElementById("resetFactorStatsBtn"),
  saveFactorStatsBtn: document.getElementById("saveFactorStatsBtn"),
  factorStatsMeta: document.getElementById("factorStatsMeta"),
  factorStatsTableBody: document.querySelector("#factorStatsTable tbody"),
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
    "Select model/symbol and click \"Load Config\" to edit factor mean/variance arrays.";
  el.factorStatsTableBody.innerHTML = "";
}

function formatNumberInput(value) {
  if (value == null || Number.isNaN(Number(value))) {
    return "";
  }
  return String(Number(value));
}

function renderFactorStats(payload) {
  const factors = Array.isArray(payload.factors) ? payload.factors : [];
  const means = Array.isArray(payload.mean_values) ? payload.mean_values : [];
  const variances = Array.isArray(payload.variance_values) ? payload.variance_values : [];

  if (factors.length !== means.length || factors.length !== variances.length) {
    throw new Error(
      `factor stats length mismatch: factors=${factors.length}, mean_values=${means.length}, variance_values=${variances.length}`
    );
  }

  el.factorStatsMeta.textContent =
    `model=${payload.model_name || "-"}, symbol=${payload.symbol || "-"}, dim=${payload.factor_count || factors.length}, updated=${payload.updated_at || "-"}`;

  if (!factors.length) {
    el.factorStatsTableBody.innerHTML = `
      <tr>
        <td colspan="4">No factor config rows found.</td>
      </tr>
    `;
    return;
  }

  el.factorStatsTableBody.innerHTML = factors
    .map(
      (factorName, idx) => `
      <tr>
        <td>${idx}</td>
        <td>${escapeHtml(factorName || "")}</td>
        <td>
          <input
            class="factor-input"
            type="number"
            step="any"
            data-role="mean"
            data-index="${idx}"
            value="${escapeHtml(formatNumberInput(means[idx]))}"
          />
        </td>
        <td>
          <input
            class="factor-input"
            type="number"
            step="any"
            data-role="variance"
            data-index="${idx}"
            value="${escapeHtml(formatNumberInput(variances[idx]))}"
          />
        </td>
      </tr>`
    )
    .join("");
}

function collectFactorStatsPayload() {
  const meanInputs = [...el.factorStatsTableBody.querySelectorAll('input[data-role="mean"]')];
  const varianceInputs = [...el.factorStatsTableBody.querySelectorAll('input[data-role="variance"]')];

  if (!meanInputs.length && !varianceInputs.length) {
    throw new Error("no factor rows loaded");
  }
  if (meanInputs.length !== varianceInputs.length) {
    throw new Error(
      `dimension mismatch: mean_values=${meanInputs.length}, variance_values=${varianceInputs.length}`
    );
  }

  const meanValues = meanInputs.map((node, idx) => {
    const value = Number(node.value);
    if (!Number.isFinite(value)) {
      throw new Error(`mean_values[${idx}] is not a finite number`);
    }
    return value;
  });

  const varianceValues = varianceInputs.map((node, idx) => {
    const value = Number(node.value);
    if (!Number.isFinite(value)) {
      throw new Error(`variance_values[${idx}] is not a finite number`);
    }
    return value;
  });

  return {
    mean_values: meanValues,
    variance_values: varianceValues,
  };
}

function resetFactorStatsToDefault() {
  const meanInputs = [...el.factorStatsTableBody.querySelectorAll('input[data-role="mean"]')];
  const varianceInputs = [...el.factorStatsTableBody.querySelectorAll('input[data-role="variance"]')];

  for (const input of meanInputs) {
    input.value = "0.2";
  }
  for (const input of varianceInputs) {
    input.value = "1";
  }
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
  showMessage(`Saved factor stats for ${modelName}/${symbol}.`);
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
