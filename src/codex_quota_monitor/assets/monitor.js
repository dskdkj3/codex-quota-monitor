var BOOTSTRAP = window.CODEX_QUOTA_MONITOR_BOOTSTRAP || {};
var INITIAL_SNAPSHOT = BOOTSTRAP.initialSnapshot || {};
var REFRESH_MS = BOOTSTRAP.refreshMs || 15000;
var TAB_NAMES = ["pool", "resets", "trends", "traffic", "audit", "alerts"];
var ACTIVE_TAB_NAME = null;
var LAST_TAB_SIGNATURES = {
  pool: null,
  resets: null,
  trends: null,
  traffic: null,
  audit: null,
  alerts: null
};
var SUMMARY_CARD_VARIANTS = {
  "five-hour-card": "summary-card-primary",
  "weekly-card": "summary-card-primary",
  "alerts-card": "summary-card-compact",
  "gateway-card": "summary-card-compact",
  "fast-card": "summary-card-compact"
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

function setSummaryTone(id, tone) {
  var variant = SUMMARY_CARD_VARIANTS[id] || "";
  setClassName(id, "summary-card" + (variant ? " " + variant : "") + " is-" + safeTone(tone, "unknown"));
}

function lastDisplayNumber(value) {
  var matches = text(value, "").match(/-?\d+(?:\.\d+)?/g);
  if (!matches || !matches.length) {
    return null;
  }
  var number = Number(matches[matches.length - 1]);
  return isNaN(number) ? null : number;
}

function summaryTone(kind, value) {
  var lower = text(value, "").toLowerCase();
  if (!lower || lower.indexOf("loading") !== -1 || lower.indexOf("unknown") !== -1 || lower.indexOf("unavailable") !== -1) {
    return "unknown";
  }
  if (kind === "gateway") {
    return lower.indexOf("ok") !== -1 ? "good" : "bad";
  }
  if (kind === "alerts") {
    return lower.indexOf("clean") !== -1 || lower === "0 alert" || lower === "0 alerts" ? "good" : "bad";
  }
  if (kind === "fast") {
    if (lower.indexOf("on") !== -1) {
      return "good";
    }
    return "unknown";
  }
  var number = lastDisplayNumber(lower);
  if (number === null) {
    return "unknown";
  }
  return number <= 0 ? "bad" : "good";
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

function safeTone(value, fallback) {
  var tone = text(value, fallback || "good");
  return tone === "good" || tone === "warn" || tone === "bad" || tone === "unknown" ? tone : fallback || "good";
}

function renderAccountSignals(account) {
  var parts = [];
  var status = text(account.statusLabel, text(account.summary, ""));

  if (status) {
    parts.push(
      '<span class="account-chip is-' + safeTone(account.tone, "good") + '">' +
        escapeHtml(status) +
      "</span>"
    );
  }

  return parts.join("");
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
    setHtml(targetId, '<article class="capacity-card"><p class="empty">No tracked capacity windows are available yet.</p></article>');
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
    var resetText = text(windowData.remainingText, "");
    if (resetText && text(windowData.beijingTimeText, "")) {
      resetText = resetText + " / " + text(windowData.beijingTimeText, "");
    }
    var resetHtml = resetText ? '<div class="quota-reset">' + escapeHtml(resetText) + "</div>" : "";
    if (!compact && shouldShowWindowNote(windowData)) {
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
        resetHtml +
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
    htmlParts.push(
      '<article class="account account-' + safeTone(account.tone, "good") + '">' +
        '<div class="account-head">' +
          '<div class="account-title-wrap">' +
            '<h3 class="account-title" title="' + escapeHtml(title) + '">' + escapeHtml(title) + "</h3>" +
          '</div>' +
          badgeHtml +
        "</div>" +
        '<div class="account-signals">' + signalsHtml + "</div>" +
        '<div class="quota-grid">' + renderQuotaLines(account.windows || [], true) + "</div>" +
      "</article>"
    );
  }

  setHtml(targetId, htmlParts.join(""));
}

function renderRecommendationGroups(targetId, recommendations) {
  var groups = (recommendations || {}).groups || [];
  var htmlParts = [];

  if (!groups.length) {
    setHtml(targetId, "");
    return;
  }

  for (var groupIndex = 0; groupIndex < groups.length; groupIndex += 1) {
    var group = groups[groupIndex] || {};
    var items = group.items && group.items.length ? group.items : [];
    var itemParts = [];
    if (!items.length) {
      itemParts.push('<p class="empty">No accounts in this group.</p>');
    }
    for (var itemIndex = 0; itemIndex < items.length; itemIndex += 1) {
      var item = items[itemIndex] || {};
      itemParts.push(
        '<div class="recommendation-item recommendation-item-' + safeTone(item.tone, "unknown") + '">' +
          '<div class="recommendation-head">' +
            '<span class="recommendation-title">' + escapeHtml(text(item.title, "Unknown account")) + "</span>" +
            '<span class="recommendation-badge">' + escapeHtml(text(item.badge, "")) + "</span>" +
          "</div>" +
          '<div class="recommendation-summary">' + escapeHtml(text(item.summary, "")) + "</div>" +
        "</div>"
      );
    }
    htmlParts.push(
      '<article class="recommendation-group recommendation-group-' + escapeHtml(text(group.id, "unknown")) + '">' +
        '<div class="recommendation-group-head">' +
          '<h3 class="recommendation-group-title">' + escapeHtml(text(group.title, "Group")) + "</h3>" +
          '<span class="recommendation-group-summary">' + escapeHtml(text(group.summary, "")) + "</span>" +
        "</div>" +
        '<div class="recommendation-items">' + itemParts.join("") + "</div>" +
      "</article>"
    );
  }

  setHtml(targetId, htmlParts.join(""));
}

function renderUsageCharts(targetId, charts) {
  var safeCharts = charts && charts.length ? charts : [];
  var htmlParts = [];

  if (!safeCharts.length) {
    setHtml(targetId, '<article class="usage-chart"><p class="empty">No usage buckets are available yet.</p></article>');
    return;
  }

  for (var chartIndex = 0; chartIndex < safeCharts.length; chartIndex += 1) {
    var chart = safeCharts[chartIndex] || {};
    var rows = chart.items && chart.items.length ? chart.items : [];
    var rowParts = [];

    if (!rows.length) {
      rowParts.push('<div class="usage-bar-row"><p class="empty">No buckets yet.</p></div>');
    }

    for (var rowIndex = 0; rowIndex < rows.length; rowIndex += 1) {
      var row = rows[rowIndex] || {};
      rowParts.push(
        '<div class="usage-bar-row">' +
          '<span class="usage-bar-label">' + escapeHtml(text(row.label, "")) + "</span>" +
          '<span class="usage-bar-track" aria-hidden="true">' +
            '<span class="usage-bar-fill" style="width:' + clampPercent(row.barPercent) + '%"></span>' +
          "</span>" +
          '<span class="usage-bar-value">' + escapeHtml(text(row.valueText, "")) + "</span>" +
        "</div>"
      );
    }

    htmlParts.push(
      '<article class="usage-chart">' +
        '<div class="usage-chart-head">' +
          '<h3 class="usage-chart-title">' + escapeHtml(text(chart.title, "Usage")) + "</h3>" +
          '<span class="usage-chart-summary">' + escapeHtml(text(chart.summary, "")) + "</span>" +
        "</div>" +
        '<div class="usage-bars">' + rowParts.join("") + "</div>" +
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
      '<article class="list-item list-item-' + safeTone(item.tone, "good") + '">' +
        '<div class="list-head">' +
          '<div class="list-title-wrap">' +
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
  renderRecommendationGroups("pool-recommendations", (window.LAST_SNAPSHOT || {}).recommendations || {});
  renderMetricCards("pool-stats", safeTab.stats || []);
  renderCapacityCards("pool-capacity", safeTab.capacityWindows || []);
  renderPoolAccounts("pool-accounts", safeTab.accounts || []);
}

function renderTrendWindows(targetId, windows) {
  var safeWindows = windows && windows.length ? windows : [];
  var htmlParts = [];

  if (!safeWindows.length) {
    setHtml(targetId, '<article class="trend-card"><p class="empty">No trend history is available yet.</p></article>');
    return;
  }

  for (var index = 0; index < safeWindows.length; index += 1) {
    var windowData = safeWindows[index] || {};
    var points = windowData.points && windowData.points.length ? windowData.points : [];
    var pointParts = [];
    for (var pointIndex = 0; pointIndex < points.length; pointIndex += 1) {
      var point = points[pointIndex] || {};
      pointParts.push(
        '<div class="trend-point">' +
          '<span>' + escapeHtml(text(point.label, "")) + "</span>" +
          '<strong>' + escapeHtml(text(point.valueText, "Unknown")) + "</strong>" +
        "</div>"
      );
    }
    htmlParts.push(
      '<article class="trend-card">' +
        '<div class="trend-head">' +
          '<h3 class="trend-title">' + escapeHtml(text(windowData.label, "Window")) + "</h3>" +
          '<span class="trend-current">' + escapeHtml(text(windowData.currentUnitsText, "Unknown")) + "</span>" +
        "</div>" +
        '<div class="trend-metrics">' +
          '<span>Burn ' + escapeHtml(text(windowData.burnText, "Unknown")) + "</span>" +
          '<span>ETA ' + escapeHtml(text(windowData.etaText, "Unknown")) + "</span>" +
        "</div>" +
        '<p class="trend-summary">' + escapeHtml(text(windowData.summary, "")) + "</p>" +
        '<div class="trend-points">' + pointParts.join("") + "</div>" +
      "</article>"
    );
  }

  setHtml(targetId, htmlParts.join(""));
}

function renderTrendsTab(tabData) {
  var safeTab = tabData || {};
  var benchmark = safeTab.benchmark || {};
  setText("tab-title-trends", safeTab.title, "Trends & ETA");
  setText("tab-summary-trends", safeTab.summary, "");
  setText("tab-footnote-trends", safeTab.footnote, "");
  setText("benchmark-summary", benchmark.summary, "");
  renderMetricCards("trends-metrics", safeTab.metrics || []);
  renderTrendWindows("trends-windows", safeTab.windows || []);
  renderMetricCards("benchmark-metrics", benchmark.metrics || []);
}

function renderTrafficTab(tabData) {
  var safeTab = tabData || {};
  setText("tab-title-traffic", safeTab.title, "Usage Statistics");
  setText("tab-summary-traffic", safeTab.summary, "");
  setText("tab-footnote-traffic", safeTab.footnote, "");
  setText("usage-load-title", safeTab.distributionTitle, "Pool Load");
  setText("usage-models-title", safeTab.modelsTitle, "Model Breakdown");
  renderMetricCards("traffic-metrics", safeTab.metrics || []);
  renderUsageCharts("usage-charts", safeTab.charts || []);
  renderListItems("traffic-distribution", safeTab.distribution || [], "No pool load is available yet.");
  renderListItems("usage-models", safeTab.models || [], "No model breakdown is available yet.");
}

function renderResetColumns(targetId, columns) {
  var safeColumns = columns && columns.length ? columns : [];
  var htmlParts = [];

  if (!safeColumns.length) {
    setHtml(targetId, '<article class="reset-list"><p class="empty">No direct quota samples are available yet.</p></article>');
    return;
  }

  for (var columnIndex = 0; columnIndex < safeColumns.length; columnIndex += 1) {
    var column = safeColumns[columnIndex] || {};
    var rows = column.items && column.items.length ? column.items : [];
    var rowParts = [];

    if (!rows.length) {
      rowParts.push('<div class="reset-row reset-row-unknown"><p class="empty">No reset times yet.</p></div>');
    }

    for (var rowIndex = 0; rowIndex < rows.length; rowIndex += 1) {
      var row = rows[rowIndex] || {};
      var known = typeof row.resetsInSeconds === "number" && row.resetAt;
      var rowClass = known ? "reset-row reset-row-" + safeTone(row.tone, "good") : "reset-row reset-row-unknown";
      var account = text(row.account, "Unknown account");
      rowParts.push(
        '<div class="' + rowClass + '">' +
          '<div class="reset-main">' +
            '<span class="reset-remaining">' + escapeHtml(text(row.remainingText, "Unknown")) + "</span>" +
            '<span class="reset-time">' + escapeHtml(text(row.beijingTimeText, "Unknown")) + "</span>" +
          "</div>" +
          '<div class="reset-meta">' +
            '<span class="reset-account" title="' + escapeHtml(account) + '">' + escapeHtml(account) + "</span>" +
            '<span>' + escapeHtml(text(row.meta, "")) + "</span>" +
            '<span>' + escapeHtml(text(row.valueText, "Unknown")) + "</span>" +
          "</div>" +
        "</div>"
      );
    }

    htmlParts.push(
      '<article class="reset-list">' +
        '<div class="reset-list-head">' +
          '<h3 class="reset-list-title">' + escapeHtml(text(column.title, "Window")) + "</h3>" +
          '<span class="reset-list-summary">' + escapeHtml(text(column.summary, "")) + "</span>" +
        "</div>" +
        '<div class="reset-items">' + rowParts.join("") + "</div>" +
      "</article>"
    );
  }

  setHtml(targetId, htmlParts.join(""));
}

function renderResetsTab(tabData) {
  var safeTab = tabData || {};
  setText("tab-title-resets", safeTab.title, "Reset Schedule");
  setText("tab-summary-resets", safeTab.summary, "");
  setText("tab-footnote-resets", safeTab.footnote, "");
  renderResetColumns("resets-columns", safeTab.columns || []);
}

function renderAlertsTab(tabData) {
  var safeTab = tabData || {};
  setText("tab-title-alerts", safeTab.title, "Intervention Only");
  setText("tab-summary-alerts", safeTab.summary, "");
  setText("tab-footnote-alerts", safeTab.footnote, "");
  renderMetricCards("alerts-metrics", safeTab.metrics || []);
  renderListItems("alerts-items", safeTab.items || [], "No active alerts.");
}

function renderAuditTab(tabData) {
  var safeTab = tabData || {};
  setText("tab-title-audit", safeTab.title, "Audit Trail");
  setText("tab-summary-audit", safeTab.summary, "");
  setText("tab-footnote-audit", safeTab.footnote, "");
  renderListItems("audit-items", safeTab.items || [], "No audit events yet.");
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
  window.LAST_SNAPSHOT = safeSnapshot;
  var summary = safeSnapshot.summary || {};
  var tabs = safeSnapshot.tabs || {};

  setText("gateway-pill", summary.gatewayPill, "Gateway unknown");
  setText("five-hour-pill", summary.fiveHourPill, "5h unknown");
  setText("weekly-pill", summary.weeklyPill, "Weekly unknown");
  setText("alerts-pill", summary.alertsPill, "Alerts unknown");
  setText("fast-pill", summary.fastPill, "Fast unknown");
  setSummaryTone("gateway-card", summaryTone("gateway", summary.gatewayPill));
  setSummaryTone("five-hour-card", summaryTone("quota", summary.fiveHourPill));
  setSummaryTone("weekly-card", summaryTone("quota", summary.weeklyPill));
  setSummaryTone("alerts-card", summaryTone("alerts", summary.alertsPill));
  setSummaryTone("fast-card", summaryTone("fast", summary.fastPill));
  setText("hero-subline", summary.subline, "Waiting for usage totals.");

  setText("source-text", safeSnapshot.sourceText, "No snapshot");
  setText("sampled-at", safeSnapshot.sampledAtText, "No sample yet");
  setText("status-text", safeSnapshot.statusText, "No status available");

  if (!safeSnapshot.available) {
    setClassName("status-panel", "panel status-panel is-bad");
  } else if (safeSnapshot.source !== "live") {
    setClassName("status-panel", "panel status-panel is-warn");
  } else {
    setClassName("status-panel", "panel status-panel is-good");
  }

  renderTabIfChanged("pool", tabs.pool, renderPoolTab);
  renderTabIfChanged("resets", tabs.resets, renderResetsTab);
  renderTabIfChanged("trends", tabs.trends, renderTrendsTab);
  renderTabIfChanged("traffic", tabs.traffic, renderTrafficTab);
  renderTabIfChanged("audit", tabs.audit, renderAuditTab);
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
        setClassName("status-panel", "panel status-panel is-bad");
        setText("status-text", "Refresh returned unreadable data. The page kept the previous snapshot.", "");
      }
      return;
    }

    setClassName("status-panel", "panel status-panel is-bad");
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
