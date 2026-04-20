var BOOTSTRAP = window.CPA_MONITOR_BOOTSTRAP || {};
var INITIAL_SNAPSHOT = BOOTSTRAP.initialSnapshot || {};
var REFRESH_MS = BOOTSTRAP.refreshMs || 15000;
var TAB_NAMES = ["pool", "traffic", "alerts"];
var ACTIVE_TAB_NAME = null;
var LAST_TAB_SIGNATURES = {
  pool: null,
  traffic: null,
  alerts: null
};

function text(value, fallback) {
  if (typeof value === "string" && value.length > 0) {
    return value;
  }
  return fallback;
}

function escapeHtml(value) {
  return text(String(value), "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

function tabFromHash() {
  var hash = (window.location.hash || "").replace(/^#/, "");
  for (var index = 0; index < TAB_NAMES.length; index += 1) {
    if (TAB_NAMES[index] === hash) {
      return hash;
    }
  }
  return "pool";
}

function setActiveTab(name, updateHash) {
  if (ACTIVE_TAB_NAME === name) {
    if (updateHash && window.location.hash !== "#" + name) {
      window.location.hash = name;
    }
    return;
  }

  for (var index = 0; index < TAB_NAMES.length; index += 1) {
    var tabName = TAB_NAMES[index];
    var button = document.getElementById("tab-button-" + tabName);
    var panel = document.getElementById("tab-panel-" + tabName);
    var isActive = tabName === name;
    if (button) {
      button.className = isActive ? "tab is-active" : "tab";
    }
    if (panel) {
      panel.className = isActive ? "panel tab-panel is-active" : "panel tab-panel";
    }
  }
  if (updateHash && window.location.hash !== "#" + name) {
    window.location.hash = name;
  }
  ACTIVE_TAB_NAME = name;
}

function setClassName(id, className) {
  var target = document.getElementById(id);
  if (!target || target.className === className) {
    return;
  }
  target.className = className;
}

function setText(id, value, fallback) {
  var target = document.getElementById(id);
  if (!target) {
    return;
  }
  var nextValue = text(value, fallback);
  if (target.textContent === nextValue) {
    return;
  }
  target.textContent = nextValue;
}

function setHtml(id, value) {
  var target = document.getElementById(id);
  if (!target || target.innerHTML === value) {
    return;
  }
  target.innerHTML = value;
}

function tabSignature(tabData) {
  return JSON.stringify(tabData || {});
}

function clampPercent(value) {
  if (typeof value !== "number" || isNaN(value)) {
    return 0;
  }
  if (value < 0) {
    return 0;
  }
  if (value > 100) {
    return 100;
  }
  return value;
}

function formatCompactNumber(value) {
  if (typeof value !== "number" || isNaN(value)) {
    return "";
  }
  if (value >= 1000000) {
    return (Math.round((value / 1000000) * 10) / 10).toString().replace(/\.0$/, "") + "M";
  }
  if (value >= 1000) {
    return (Math.round((value / 1000) * 10) / 10).toString().replace(/\.0$/, "") + "K";
  }
  return String(Math.round(value));
}

function renderAccountSignals(account) {
  var parts = [];

  if (account.summary) {
    parts.push('<span class="account-chip is-status">' + escapeHtml(account.summary) + "</span>");
  }
  if (typeof account.sharePercent === "number") {
    parts.push('<span class="account-chip">' + escapeHtml(String(account.sharePercent) + "% share") + "</span>");
  }
  if (typeof account.requests === "number") {
    parts.push('<span class="account-chip">' + escapeHtml(String(account.requests) + " req") + "</span>");
  }
  if (typeof account.tokens === "number") {
    parts.push('<span class="account-chip">' + escapeHtml(formatCompactNumber(account.tokens) + " tok") + "</span>");
  }
  if (typeof account.failed === "number" && account.failed > 0) {
    parts.push('<span class="account-chip is-issue">' + escapeHtml(String(account.failed) + " fail") + "</span>");
  }

  return parts.join("");
}

function shouldShowAccountNote(account) {
  var note = text(account.note, "");
  if (!note) {
    return false;
  }
  if (text(account.tone, "good") !== "good") {
    return true;
  }
  return /(resets|failed|not succeeded|waiting for first|unavailable|disabled|missing|error)/i.test(note);
}

function shouldShowWindowNote(windowData) {
  var note = text(windowData.note, "");
  if (!note) {
    return false;
  }
  if (text(windowData.state, "unknown") !== "known") {
    return true;
  }
  return /failed/i.test(note);
}

function renderMetricCards(targetId, metrics) {
  var safeMetrics = metrics && metrics.length ? metrics : [];
  var htmlParts = [];

  if (!safeMetrics.length) {
    setHtml(targetId, "");
    return;
  }

  for (var index = 0; index < safeMetrics.length; index += 1) {
    var metric = safeMetrics[index] || {};
    var detailHtml = metric.detail ? '<div class="metric-detail">' + escapeHtml(metric.detail) + "</div>" : "";
    htmlParts.push(
      '<article class="metric">' +
        '<div class="metric-label">' + escapeHtml(text(metric.label, "Metric")) + "</div>" +
        '<div class="metric-value">' + escapeHtml(text(metric.value, "n/a")) + "</div>" +
        detailHtml +
      "</article>"
    );
  }

  setHtml(targetId, htmlParts.join(""));
}

function renderCapacityCards(targetId, windows) {
  var safeWindows = windows && windows.length ? windows : [];
  var htmlParts = [];

  if (!safeWindows.length) {
    setHtml(targetId, '<article class="capacity-card"><p class="empty">No Plus capacity windows are available yet.</p></article>');
    return;
  }

  for (var index = 0; index < safeWindows.length; index += 1) {
    var windowData = safeWindows[index] || {};
    var knownWidth = clampPercent(windowData.knownBarPercent);
    var unknownWidth = clampPercent(windowData.unknownBarPercent);
    htmlParts.push(
      '<article class="capacity-card">' +
        '<div class="capacity-head">' +
          '<div class="capacity-label">' + escapeHtml(text(windowData.label, "Window")) + "</div>" +
          '<div class="capacity-value">' + escapeHtml(text(windowData.knownUnitsText, "n/a")) + "</div>" +
        "</div>" +
        '<div class="stack-bar" aria-hidden="true">' +
          '<span class="stack-segment is-known" style="left:0;width:' + knownWidth + '%"></span>' +
          '<span class="stack-segment is-unknown" style="left:' + knownWidth + '%;width:' + unknownWidth + '%"></span>' +
        "</div>" +
        '<p class="capacity-summary">' + escapeHtml(text(windowData.summary, "")) + "</p>" +
      "</article>"
    );
  }

  setHtml(targetId, htmlParts.join(""));
}

function renderQuotaLines(windows, compact) {
  var safeWindows = windows && windows.length ? windows : [];
  var htmlParts = [];
  var lastVisibleNote = null;

  for (var index = 0; index < safeWindows.length; index += 1) {
    var windowData = safeWindows[index] || {};
    var state = text(windowData.state, "unknown");
    var fillWidth = clampPercent(windowData.fillPercent);
    var barClass = "quota-bar is-" + state;
    var fillHtml = state === "known" || state === "exhausted"
      ? '<div class="quota-fill" style="width:' + fillWidth + '%"></div>'
      : "";
    var noteHtml = "";
    var note = text(windowData.note, "");
    if (!compact || shouldShowWindowNote(windowData)) {
      if (!compact || note !== lastVisibleNote) {
        noteHtml = '<div class="quota-note">' + escapeHtml(note) + "</div>";
        lastVisibleNote = note;
      }
    }

    htmlParts.push(
      '<div class="quota-line' + (compact ? " is-compact" : "") + '">' +
        '<div class="quota-head">' +
          '<span class="quota-label">' + escapeHtml(text(windowData.label, "Window")) + "</span>" +
          '<span class="quota-value">' + escapeHtml(text(windowData.valueText, "Unknown")) + "</span>" +
        "</div>" +
        '<div class="' + escapeHtml(barClass) + '" aria-hidden="true">' + fillHtml + "</div>" +
        noteHtml +
      "</div>"
    );
  }

  return htmlParts.join("");
}

function renderPoolAccounts(targetId, accounts) {
  var safeAccounts = accounts && accounts.length ? accounts : [];
  var htmlParts = [];

  if (!safeAccounts.length) {
    setHtml(targetId, '<article class="account"><p class="empty">No accounts are visible in the pool yet.</p></article>');
    return;
  }

  for (var index = 0; index < safeAccounts.length; index += 1) {
    var account = safeAccounts[index] || {};
    var title = text(account.title, "Unknown account");
    var badge = text(account.badge, "");
    var badgeHtml = badge ? '<span class="account-badge">' + escapeHtml(badge) + "</span>" : "";
    var signalsHtml = renderAccountSignals(account);
    var meta = text(account.meta, "");
    var metaHtml = meta ? '<p class="account-meta">' + escapeHtml(meta) + "</p>" : "";
    var noteHtml = shouldShowAccountNote(account)
      ? '<p class="account-note">' + escapeHtml(text(account.note, "")) + "</p>"
      : "";
    htmlParts.push(
      '<article class="account account-' + escapeHtml(text(account.tone, "good")) + '">' +
        '<div class="account-head">' +
          '<div class="account-title-wrap">' +
            '<h3 class="account-title" title="' + escapeHtml(title) + '">' + escapeHtml(title) + "</h3>" +
          '</div>' +
          badgeHtml +
        "</div>" +
        '<div class="account-signals">' + signalsHtml + "</div>" +
        metaHtml +
        noteHtml +
        '<div class="quota-grid">' + renderQuotaLines(account.windows || [], true) + "</div>" +
      "</article>"
    );
  }

  setHtml(targetId, htmlParts.join(""));
}

function renderListItems(targetId, items, emptyMessage) {
  var safeItems = items && items.length ? items : [];
  var htmlParts = [];

  if (!safeItems.length) {
    setHtml(targetId, '<article class="list-item"><p class="empty">' + escapeHtml(emptyMessage) + "</p></article>");
    return;
  }

  for (var index = 0; index < safeItems.length; index += 1) {
    var item = safeItems[index] || {};
    var barHtml = "";
    if (typeof item.barPercent === "number") {
      barHtml =
        '<div class="share-bar" aria-hidden="true">' +
          '<div class="share-fill" style="width:' + clampPercent(item.barPercent) + '%"></div>' +
        "</div>";
    }
    var noteHtml = item.note ? '<p class="list-note">' + escapeHtml(item.note) + "</p>" : "";
    htmlParts.push(
      '<article class="list-item list-item-' + escapeHtml(text(item.tone, "good")) + '">' +
        '<div class="list-head">' +
          '<div>' +
            '<h3 class="list-title">' + escapeHtml(text(item.title, "Untitled")) + "</h3>" +
            '<p class="list-summary">' + escapeHtml(text(item.summary, "")) + "</p>" +
          '</div>' +
          '<span class="list-badge">' + escapeHtml(text(item.badge, "")) + "</span>" +
        "</div>" +
        '<p class="list-detail">' + escapeHtml(text(item.detail, "")) + "</p>" +
        noteHtml +
        barHtml +
      "</article>"
    );
  }

  setHtml(targetId, htmlParts.join(""));
}

function renderPoolTab(tabData) {
  var safeTab = tabData || {};
  setText("tab-title-pool", safeTab.title, "Pool Capacity");
  setText("tab-summary-pool", safeTab.summary, "");
  setText("tab-footnote-pool", safeTab.footnote, "");
  renderMetricCards("pool-stats", safeTab.stats || []);
  renderCapacityCards("pool-capacity", safeTab.capacityWindows || []);
  renderPoolAccounts("pool-accounts", safeTab.accounts || []);
}

function renderTrafficTab(tabData) {
  var safeTab = tabData || {};
  setText("tab-title-traffic", safeTab.title, "Traffic Snapshot");
  setText("tab-summary-traffic", safeTab.summary, "");
  setText("tab-footnote-traffic", safeTab.footnote, "");
  renderMetricCards("traffic-metrics", safeTab.metrics || []);
  renderListItems("traffic-distribution", safeTab.distribution || [], "No traffic split is available yet.");
}

function renderAlertsTab(tabData) {
  var safeTab = tabData || {};
  setText("tab-title-alerts", safeTab.title, "Intervention Only");
  setText("tab-summary-alerts", safeTab.summary, "");
  setText("tab-footnote-alerts", safeTab.footnote, "");
  renderMetricCards("alerts-metrics", safeTab.metrics || []);
  renderListItems("alerts-items", safeTab.items || [], "No active alerts.");
}

function renderTabIfChanged(name, tabData, renderFn) {
  var signature = tabSignature(tabData);
  if (LAST_TAB_SIGNATURES[name] === signature) {
    return;
  }
  LAST_TAB_SIGNATURES[name] = signature;
  renderFn(tabData || {});
}

function renderSnapshot(snapshot) {
  var safeSnapshot = snapshot || {};
  var summary = safeSnapshot.summary || {};
  var tabs = safeSnapshot.tabs || {};

  setText("gateway-pill", summary.gatewayPill, "Gateway unknown");
  setText("five-hour-pill", summary.fiveHourPill, "5h unknown");
  setText("weekly-pill", summary.weeklyPill, "Weekly unknown");
  setText("alerts-pill", summary.alertsPill, "Alerts unknown");
  setText("hero-subline", summary.subline, "Waiting for usage totals.");

  setText("source-text", safeSnapshot.sourceText, "No snapshot");
  setText("sampled-at", safeSnapshot.sampledAtText, "No sample yet");
  setText("status-text", safeSnapshot.statusText, "No status available");

  if (!safeSnapshot.available || safeSnapshot.source !== "live") {
    setClassName("status-panel", "panel status-panel is-alert");
  } else {
    setClassName("status-panel", "panel status-panel");
  }

  renderTabIfChanged("pool", tabs.pool, renderPoolTab);
  renderTabIfChanged("traffic", tabs.traffic, renderTrafficTab);
  renderTabIfChanged("alerts", tabs.alerts, renderAlertsTab);
}

function refreshSnapshot() {
  var request = new XMLHttpRequest();
  request.open("GET", "/api/status", true);
  request.setRequestHeader("Cache-Control", "no-store");
  request.onreadystatechange = function () {
    if (request.readyState !== 4) {
      return;
    }

    if (request.status >= 200 && request.status < 300) {
      try {
        renderSnapshot(JSON.parse(request.responseText));
      } catch (error) {
        setClassName("status-panel", "panel status-panel is-alert");
        setText("status-text", "Refresh returned unreadable data. The page kept the previous snapshot.", "");
      }
      return;
    }

    setClassName("status-panel", "panel status-panel is-alert");
    setText("status-text", "Refresh failed. The page will keep the previous snapshot until the next retry.", "");
  };
  request.send(null);
}

window.onhashchange = function () {
  setActiveTab(tabFromHash(), false);
};

renderSnapshot(INITIAL_SNAPSHOT);
setActiveTab(tabFromHash(), false);
window.setInterval(refreshSnapshot, REFRESH_MS);
