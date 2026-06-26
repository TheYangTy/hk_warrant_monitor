const state = {
  watchlist: [],
  status: null,
  ai: null,
  signals: [],
};

const $ = (id) => document.getElementById(id);

function toast(message) {
  const el = $("toast");
  el.textContent = message;
  el.classList.add("show");
  setTimeout(() => el.classList.remove("show"), 2200);
}

async function api(path, options = {}) {
  const response = await fetch(path, {
    headers: { "Content-Type": "application/json", ...(options.headers || {}) },
    ...options,
  });
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    throw new Error(body.error || `HTTP ${response.status}`);
  }
  return response.json();
}

async function loadAll() {
  const [status, watchlist, ai, signals, logs] = await Promise.all([
    api("/api/status"),
    api("/api/watchlist"),
    api("/api/ai-usage"),
    api("/api/signals"),
    api("/api/logs?limit=120"),
  ]);
  state.status = status;
  state.watchlist = watchlist;
  state.ai = ai;
  state.signals = signals;
  render();
  $("logView").textContent = logs.lines.join("\n") || "暂无日志";
}

function render() {
  $("enabledWatchCount").textContent = state.status.enabledWatchCount;
  $("scanInterval").textContent = `${state.status.scanInterval}s`;
  $("aiCalls").textContent = `${state.ai.calls}/${state.ai.dailyLimit}`;
  $("aiTokens").textContent = state.ai.totalTokens.toLocaleString();
  const runtime = state.status.runtimeState || {};
  $("lastScanAt").textContent = formatTime(runtime.last_scan_finished_at?.value);
  $("scanStatus").textContent = runtime.last_scan_status?.value || "-";
  renderNetworkUrls();
  renderWatchlist();
  renderSignals();
}

function formatTime(value) {
  if (!value) return "-";
  return String(value).replace("T", " ").slice(0, 19);
}

function renderNetworkUrls() {
  const box = $("networkUrls");
  const urls = state.status.dashboardUrls || {};
  const lanUrls = Array.isArray(urls.lan) ? urls.lan : urls.lan ? [urls.lan] : [];
  const rows = [
    { label: "本机", value: urls.local || `http://127.0.0.1:${state.status.port}` },
    ...lanUrls.map((value) => ({ label: "手机/iPad 候选", value })),
  ];
  if (!lanUrls.length) {
    rows.push({ label: "手机/iPad", value: "未发现局域网地址，请检查 Wi-Fi 或 macOS 防火墙" });
  }
  box.innerHTML = rows
    .map((row) => {
      const isUrl = row.value.startsWith("http");
      const value = isUrl
        ? `<a href="${escapeHtml(row.value)}" target="_blank" rel="noreferrer">${escapeHtml(row.value)}</a>`
        : `<span>${escapeHtml(row.value)}</span>`;
      return `<div class="network-row"><strong>${escapeHtml(row.label)}</strong>${value}</div>`;
    })
    .join("");
}

function renderWatchlist() {
  const tbody = $("watchlistRows");
  tbody.innerHTML = "";
  if (!state.watchlist.length) {
    tbody.innerHTML = `<tr><td colspan="7">暂无关注股票，请在右侧新增。</td></tr>`;
    return;
  }
  for (const item of state.watchlist) {
    const directionClass = item.direction === "LONG" ? "green" : item.direction === "SHORT" ? "red" : "";
    const tr = document.createElement("tr");
    tr.innerHTML = `
      <td><strong>${item.code}</strong></td>
      <td>${escapeHtml(item.name || "-")}</td>
      <td><span class="tag ${directionClass}">${item.direction}</span></td>
      <td>${item.riskLevel}</td>
      <td>${item.allowOvernight ? "允许" : "日内"}</td>
      <td>${item.enable ? '<span class="tag green">启用</span>' : '<span class="tag">停用</span>'}</td>
      <td>
        <div class="row-actions">
          <button class="secondary" data-toggle="${item.code}" data-enable="${!item.enable}">${item.enable ? "停用" : "启用"}</button>
          <button class="secondary" data-delete="${item.code}">删除</button>
        </div>
      </td>
    `;
    tbody.appendChild(tr);
  }
}

function renderSignals() {
  const list = $("signalList");
  list.innerHTML = "";
  if (!state.signals.length) {
    list.innerHTML = `<div class="signal-item">暂无信号记录</div>`;
    return;
  }
  for (const signal of state.signals) {
    const item = document.createElement("div");
    item.className = "signal-item";
    item.innerHTML = `
      <strong>${signal.underlying_code}</strong>
      <span class="tag ${signal.action.includes("BUY") ? "green" : signal.action.includes("STOP") ? "red" : ""}">${signal.action}</span>
      <span>${escapeHtml(signal.reason || "")}</span>
      <span>${signal.created_at}</span>
    `;
    list.appendChild(item);
  }
}

function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

document.addEventListener("click", async (event) => {
  const toggle = event.target.closest("[data-toggle]");
  if (toggle) {
    await api(`/api/watchlist/${encodeURIComponent(toggle.dataset.toggle)}`, {
      method: "PATCH",
      body: JSON.stringify({ enable: toggle.dataset.enable === "true" }),
    });
    toast("状态已更新");
    await loadAll();
    return;
  }

  const del = event.target.closest("[data-delete]");
  if (del && confirm(`删除 ${del.dataset.delete} ?`)) {
    await api(`/api/watchlist/${encodeURIComponent(del.dataset.delete)}`, { method: "DELETE" });
    toast("已删除");
    await loadAll();
  }
});

$("watchForm").addEventListener("submit", async (event) => {
  event.preventDefault();
  const form = new FormData(event.currentTarget);
  await api("/api/watchlist", {
    method: "POST",
    body: JSON.stringify({
      code: form.get("code"),
      name: form.get("name"),
      direction: form.get("direction"),
      riskLevel: form.get("riskLevel"),
      allowOvernight: form.get("allowOvernight") === "on",
      enable: true,
    }),
  });
  event.currentTarget.reset();
  toast("关注已保存");
  await loadAll();
});

$("refreshBtn").addEventListener("click", () => loadAll().then(() => toast("已刷新")));

$("testFeishuBtn").addEventListener("click", async () => {
  const result = await api("/api/notify/test-feishu", { method: "POST", body: "{}" });
  toast(result.sent ? "飞书已发送" : "飞书未发送，请检查配置");
});

loadAll().catch((error) => toast(error.message));
