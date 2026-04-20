var BOOTSTRAP = window.CPA_MONITOR_BOOTSTRAP || {};
var INITIAL_SNAPSHOT = BOOTSTRAP.initialSnapshot || {};
var REFRESH_MS = BOOTSTRAP.refreshMs || 15000;
var TAB_NAMES = ["pool", "traffic", "alerts"];

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
}

function setText(id, value, fallback) {
  var target = document.getElementById(id);
  if (!target) {
    return;
  }
  target.textContent = text(value, fallback);
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

function renderMetricCards(targetId, metrics) {
  var target = document.getElementById(targetId);
  var safeMetrics = metrics && metrics.length ? metrics : [];
  var htmlParts = [];

  if (!safeMetrics.length) {
    target.innerHTML = "";
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

  target.innerHTML = htmlParts.join("");
}

function renderCapacityCards(targetId, windows) {
  var target = document.getElementById(targetId);
  var safeWindows = windows && windows.length ? windows : [];
  var htmlParts = [];

  if (!safeWindows.length) {
    target.innerHTML = '<article class="capacity-card"><p class="empty">No Plus capacity windows are available yet.</p></article>';
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

  target.innerHTML = htmlParts.join("");
}

function renderQuotaLines(windows) {
  var safeWindows = windows && windows.length ? windows : [];
  var htmlParts = [];

  for (var index = 0; index < safeWindows.length; index += 1) {
    var windowData = safeWindows[index] || {};
    var state = text(windowData.state, "unknown");
    var fillWidth = clampPercent(windowData.fillPercent);
    var barClass = "quota-bar is-" + state;
    var fillHtml = state === "known" || state === "exhausted"
      ? '<div class="quota-fill" style="width:' + fillWidth + '%"></div>'
      : "";

    htmlParts.push(
      '<div class="quota-line">' +
        '<div class="quota-head">' +
          '<span class="quota-label">' + escapeHtml(text(windowData.label, "Window")) + "</span>" +
          '<span class="quota-value">' + escapeHtml(text(windowData.valueText, "Unknown")) + "</span>" +
        "</div>" +
        '<div class="' + escapeHtml(barClass) + '" aria-hidden="true">' + fillHtml + "</div>" +
        '<div class="quota-note">' + escapeHtml(text(windowData.note, "")) + "</div>" +
      "</div>"
    );
  }

  return htmlParts.join("");
}

function renderPoolAccounts(targetId, accounts) {
  var target = document.getElementById(targetId);
  var safeAccounts = accounts && accounts.length ? accounts : [];
  var htmlParts = [];

  if (!safeAccounts.length) {
    target.innerHTML = '<article class="account"><p class="empty">No accounts are visible in the pool yet.</p></article>';
    return;
  }

  for (var index = 0; index < safeAccounts.length; index += 1) {
    var account = safeAccounts[index] || {};
    var noteHtml = account.note ? '<p class="account-note">' + escapeHtml(account.note) + "</p>" : "";
    htmlParts.push(
      '<article class="account account-' + escapeHtml(text(account.tone, "good")) + '">' +
        '<div class="account-head">' +
          '<div>' +
            '<h3 class="account-title">' + escapeHtml(text(account.title, "Unknown account")) + "</h3>" +
            '<p class="account-summary">' + escapeHtml(text(account.summary, "")) + "</p>" +
          '</div>' +
          '<span class="account-badge">' + escapeHtml(text(account.badge, "")) + "</span>" +
        "</div>" +
        '<p class="account-meta">' + escapeHtml(text(account.meta, "")) + "</p>" +
        '<p class="account-traffic">' + escapeHtml(text(account.trafficText, "")) + "</p>" +
        noteHtml +
        '<div class="quota-grid">' + renderQuotaLines(account.windows || []) + "</div>" +
      "</article>"
    );
  }

  target.innerHTML = htmlParts.join("");
}

function renderListItems(targetId, items, emptyMessage) {
  var target = document.getElementById(targetId);
  var safeItems = items && items.length ? items : [];
  var htmlParts = [];

  if (!safeItems.length) {
    target.innerHTML = '<article class="list-item"><p class="empty">' + escapeHtml(emptyMessage) + "</p></article>";
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

  target.innerHTML = htmlParts.join("");
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

function renderSnapshot(snapshot) {
  var safeSnapshot = snapshot || {};
  var summary = safeSnapshot.summary || {};
  var tabs = safeSnapshot.tabs || {};
  var statusPanel = document.getElementById("status-panel");

  setText("gateway-pill", summary.gatewayPill, "Gateway unknown");
  setText("five-hour-pill", summary.fiveHourPill, "5h unknown");
  setText("weekly-pill", summary.weeklyPill, "Weekly unknown");
  setText("alerts-pill", summary.alertsPill, "Alerts unknown");
  setText("hero-subline", summary.subline, "Waiting for usage totals.");

  setText("source-text", safeSnapshot.sourceText, "No snapshot");
  setText("sampled-at", safeSnapshot.sampledAtText, "No sample yet");
  setText("status-text", safeSnapshot.statusText, "No status available");

  if (!safeSnapshot.available || safeSnapshot.source !== "live") {
    statusPanel.className = "panel status-panel is-alert";
  } else {
    statusPanel.className = "panel status-panel";
  }

  renderPoolTab(tabs.pool || {});
  renderTrafficTab(tabs.traffic || {});
  renderAlertsTab(tabs.alerts || {});
  setActiveTab(tabFromHash(), false);
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
        document.getElementById("status-panel").className = "panel status-panel is-alert";
        document.getElementById("status-text").textContent =
          "Refresh returned unreadable data. The page kept the previous snapshot.";
      }
      return;
    }

    document.getElementById("status-panel").className = "panel status-panel is-alert";
    document.getElementById("status-text").textContent =
      "Refresh failed. The page will keep the previous snapshot until the next retry.";
  };
  request.send(null);
}

window.onhashchange = function () {
  setActiveTab(tabFromHash(), false);
};

renderSnapshot(INITIAL_SNAPSHOT);
setActiveTab(tabFromHash(), false);
window.setInterval(refreshSnapshot, REFRESH_MS);
