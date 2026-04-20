var BOOTSTRAP = window.CPA_MONITOR_BOOTSTRAP || {};
var INITIAL_SNAPSHOT = BOOTSTRAP.initialSnapshot || {};
var REFRESH_MS = BOOTSTRAP.refreshMs || 15000;
var TAB_NAMES = ["pool", "traffic", "alerts"];
var ACTIVE_TAB = "pool";

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
  ACTIVE_TAB = name;
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

function renderStats(targetId, stats) {
  var target = document.getElementById(targetId);
  var safeStats = stats && stats.length ? stats : [];
  var htmlParts = [];

  if (!safeStats.length) {
    target.innerHTML = "";
    return;
  }

  for (var index = 0; index < safeStats.length; index += 1) {
    var stat = safeStats[index] || {};
    htmlParts.push(
      '<article class="stat">' +
        '<div class="stat-label">' + escapeHtml(text(stat.label, "Metric")) + "</div>" +
        '<div class="stat-value">' + escapeHtml(text(stat.value, "n/a")) + "</div>" +
      "</article>"
    );
  }

  target.innerHTML = htmlParts.join("");
}

function renderItems(targetId, items, emptyMessage) {
  var target = document.getElementById(targetId);
  var safeItems = items && items.length ? items : [];
  var htmlParts = [];

  if (!safeItems.length) {
    target.innerHTML = '<article class="item"><p class="empty">' + escapeHtml(emptyMessage) + "</p></article>";
    return;
  }

  for (var index = 0; index < safeItems.length; index += 1) {
    var item = safeItems[index] || {};
    var tone = text(item.tone, "neutral");
    var noteHtml = item.note ? '<p class="item-note">' + escapeHtml(item.note) + "</p>" : "";
    var detailHtml = item.detail ? '<p class="item-detail">' + escapeHtml(item.detail) + "</p>" : "";
    var barHtml = "";

    if (typeof item.barPercent === "number") {
      var width = item.barPercent;
      if (width < 0) {
        width = 0;
      }
      if (width > 100) {
        width = 100;
      }
      barHtml =
        '<div class="bar" aria-hidden="true">' +
          '<div class="bar-fill" style="width: ' + width + '%"></div>' +
        "</div>";
    }

    htmlParts.push(
      '<article class="item item-' + escapeHtml(tone) + '">' +
        '<div class="item-head">' +
          '<h3 class="item-title">' + escapeHtml(text(item.title, "Untitled")) + "</h3>" +
          '<span class="badge">' + escapeHtml(text(item.badge, "")) + "</span>" +
        "</div>" +
        '<p class="item-meta">' + escapeHtml(text(item.meta, "")) + "</p>" +
        detailHtml +
        noteHtml +
        barHtml +
      "</article>"
    );
  }

  target.innerHTML = htmlParts.join("");
}

function renderTab(tabName, tabData) {
  var safeTab = tabData || {};
  document.getElementById("tab-title-" + tabName).textContent = text(safeTab.title, "Unavailable");
  document.getElementById("tab-summary-" + tabName).textContent = text(safeTab.summary, "");
  document.getElementById("tab-footnote-" + tabName).textContent = text(safeTab.footnote, "");
  renderStats("tab-stats-" + tabName, safeTab.stats || []);
  renderItems("tab-items-" + tabName, safeTab.items || [], "Nothing to show in this tab yet.");
}

function renderSnapshot(snapshot) {
  var safeSnapshot = snapshot || {};
  var summary = safeSnapshot.summary || {};
  var tabs = safeSnapshot.tabs || {};
  var statusPanel = document.getElementById("status-panel");

  document.getElementById("health-pill").textContent = text(summary.gatewayPill, "Gateway unknown");
  document.getElementById("pool-pill").textContent = text(summary.poolPill, "Pool unavailable");
  document.getElementById("alerts-pill").textContent = text(summary.alertsPill, "Alerts unknown");
  document.getElementById("hero-subline").textContent = text(summary.subline, "Waiting for usage totals.");

  document.getElementById("source-text").textContent = text(safeSnapshot.sourceText, "No snapshot");
  document.getElementById("sampled-at").textContent = text(safeSnapshot.sampledAtText, "No sample yet");
  document.getElementById("status-text").textContent = text(safeSnapshot.statusText, "No status available");

  if (!safeSnapshot.available || safeSnapshot.source !== "live") {
    statusPanel.className = "panel status-panel is-alert";
  } else {
    statusPanel.className = "panel status-panel";
  }

  renderTab("pool", tabs.pool || {});
  renderTab("traffic", tabs.traffic || {});
  renderTab("alerts", tabs.alerts || {});
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
