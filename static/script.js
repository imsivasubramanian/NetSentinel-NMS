/* NetPulse front-end. Talks to the Flask API; all data shown is SIMULATED. */
(function () {
  "use strict";
  var $ = function (id) { return document.getElementById(id); };
  var data = null;            // latest API payload
  var charts = {};
  var chartsOk = typeof Chart !== "undefined";
  var TITLES = { overview: "Overview", devices: "Devices", analytics: "Performance analytics", alerts: "Alerts", about: "Settings & info" };
  var COLORS = { ok: "#34d399", warn: "#fbbf24", crit: "#f87171", off: "#94a3b8", accent: "#2dd4bf", blue: "#60a5fa", grid: "#243350", text: "#93a3bd" };

  function esc(s) { var d = document.createElement("div"); d.textContent = String(s); return d.innerHTML; }

  /* ---------- API ---------- */
  function api(path, method) {
    return fetch(path, { method: method || "GET", headers: { "Accept": "application/json" } })
      .then(function (r) { return r.json().then(function (j) { if (!r.ok || !j.success) { throw new Error(j.message || "Request failed"); } return j; }); });
  }
  function load(path, method) {
    $("loading").hidden = false;
    var btns = document.querySelectorAll(".btn"); btns.forEach(function (b) { b.disabled = true; });
    return api(path, method).then(function (res) {
      data = res.data; render(); $("errorBox").hidden = true;
      if (method === "POST") { toast(res.message); }
    }).catch(function (e) {
      $("errorBox").hidden = false;
      $("errorBox").textContent = "Could not reach the backend: " + e.message + ". Make sure 'python app.py' is running.";
      toast("Error: " + e.message, true);
    }).then(function () {
      $("loading").hidden = true; btns.forEach(function (b) { b.disabled = false; });
    });
  }
  function toast(msg, isErr) {
    var t = $("toast"); t.textContent = msg; t.className = "toast show" + (isErr ? " err" : "");
    clearTimeout(toast.t); toast.t = setTimeout(function () { t.className = "toast"; }, 2800);
  }

  /* ---------- rendering ---------- */
  function sevOfScore(s) { return s >= 75 ? "ok" : s >= 50 ? "warning" : "critical"; }
  function card(title, value, desc, sev) {
    return '<div class="card ' + sev + '"><h3>' + esc(title) + '</h3><div class="val">' + esc(value) + '</div><div class="desc">' + esc(desc) + '</div></div>';
  }
  function renderCards() {
    var s = data.summary, t = data.thresholds;
    var issues = s.devices_with_issues;
    var html = "";
    html += card("Total devices", s.total_devices, "Simulated inventory", "ok");
    html += card("Online devices", s.online_devices + " / " + s.total_devices, s.offline_devices ? s.offline_devices + " offline" : "All reachable", s.offline_devices ? "critical" : "ok");
    html += card("Devices with issues", issues, issues ? s.critical_alerts + " critical, " + s.warning_alerts + " warning alerts" : "No active alerts", s.critical_alerts ? "critical" : issues ? "warning" : "ok");
    html += card("Average latency", s.avg_latency + " ms", "Warning > " + t.latency.warning + " ms", s.avg_latency > t.latency.critical ? "critical" : s.avg_latency > t.latency.warning ? "warning" : "ok");
    html += card("Bandwidth utilization", s.avg_bandwidth + "%", "Warning > " + t.bandwidth.warning + "%", s.avg_bandwidth > t.bandwidth.warning ? "warning" : "ok");
    html += card("Packet loss", s.avg_packet_loss + "%", "Warning > " + t.packet_loss.warning + "%", s.avg_packet_loss > t.packet_loss.critical ? "critical" : s.avg_packet_loss > t.packet_loss.warning ? "warning" : "ok");
    html += card("Health score", s.health_score + " / 100", s.health_label, sevOfScore(s.health_score));
    $("cards").innerHTML = html;
  }
  function renderHealth() {
    var h = data.health, sev = sevOfScore(h.score);
    $("healthScore").textContent = h.score; $("healthLabel").textContent = h.label;
    var fg = $("ringFg");
    fg.style.strokeDashoffset = 326.7 * (1 - h.score / 100);
    fg.style.stroke = sev === "ok" ? COLORS.ok : sev === "warning" ? COLORS.warn : COLORS.crit;
    var names = { latency: "Latency", packet_loss: "Packet loss", cpu: "CPU", memory: "Memory", bandwidth: "Bandwidth", availability: "Availability" };
    $("breakdown").innerHTML = Object.keys(names).map(function (k) {
      return "<li><span>" + names[k] + "</span><b>" + h.breakdown[k] + "</b></li>";
    }).join("");
  }
  function renderRecs() {
    var html = data.recommendations.map(function (r) {
      return '<div class="rec ' + r.severity + '"><b>' + esc(r.title) + "</b><small>" + esc(r.detail) + "</small><small>Next step: " + esc(r.action) + "</small></div>";
    }).join("");
    $("recsOverview").innerHTML = html; $("recsAlerts").innerHTML = html;
  }
  function cellClass(key, v) {
    var t = data.thresholds[key]; if (!t) { return ""; }
    if (t.critical !== null && v > t.critical) { return "crit-v"; }
    return v > t.warning ? "warn-v" : "";
  }
  function renderDevices() {
    var q = $("search").value.trim().toLowerCase(), f = $("statusFilter").value;
    var rows = data.devices.filter(function (d) {
      var hit = !q || (d.name + " " + d.type + " " + d.ip).toLowerCase().indexOf(q) !== -1;
      return hit && (f === "all" || d.status === f);
    });
    $("rowCount").textContent = "Showing " + rows.length + " of " + data.devices.length + " devices";
    if (!rows.length) { $("deviceRows").innerHTML = '<tr><td colspan="9" class="empty">No devices match your search or filter.</td></tr>'; return; }
    $("deviceRows").innerHTML = rows.map(function (d) {
      var dash = function (v, u, k) { return d.offline ? '<td>--</td>' : '<td class="' + cellClass(k, v) + '">' + v + u + "</td>"; };
      return "<tr><td>" + esc(d.name) + "</td><td>" + esc(d.type) + "</td><td>" + esc(d.ip) + '</td><td><span class="pill ' + d.status + '">' + d.status + "</span></td>" +
        dash(d.cpu, "%", "cpu") + dash(d.memory, "%", "memory") + dash(d.latency, " ms", "latency") + dash(d.packet_loss, "%", "packet_loss") +
        "<td>" + esc(d.last_updated) + "</td></tr>";
    }).join("");
  }
  function renderAlerts() {
    var a = data.alerts, n = $("navAlertCount");
    n.textContent = a.length; n.className = "count" + (a.length ? "" : " zero");
    if (!a.length) { $("alertRows").innerHTML = '<tr><td colspan="7" class="empty">No active alerts. All simulated metrics are within thresholds.</td></tr>'; return; }
    $("alertRows").innerHTML = a.map(function (x) {
      return '<tr><td><span class="pill ' + x.severity + '">' + x.severity + "</span></td><td>" + esc(x.device) + "</td><td>" + esc(x.description) + "</td><td>" + esc(x.value) +
        "</td><td>" + esc(x.threshold) + "</td><td>" + esc(x.timestamp) + '</td><td class="wrap">' + esc(x.action) + "</td></tr>";
    }).join("");
  }
  function renderThresholds() {
    var t = data.thresholds;
    $("thresholdRows").innerHTML = Object.keys(t).map(function (k) {
      return "<tr><td>" + esc(t[k].label) + "</td><td>" + t[k].warning + t[k].unit + "</td><td>" + (t[k].critical === null ? "n/a" : t[k].critical + t[k].unit) + "</td></tr>";
    }).join("") + "<tr><td>Device offline</td><td>n/a</td><td>Always critical</td></tr>";
  }

  /* ---------- charts ---------- */
  function opts(yTitle, extra) {
    var o = { responsive: true, maintainAspectRatio: false, animation: { duration: 300 },
      plugins: { legend: { labels: { color: COLORS.text } } },
      scales: { x: { ticks: { color: COLORS.text }, grid: { color: COLORS.grid } },
                y: { beginAtZero: true, title: { display: true, text: yTitle, color: COLORS.text }, ticks: { color: COLORS.text }, grid: { color: COLORS.grid } } } };
    if (extra) { Object.keys(extra).forEach(function (k) { o.scales.y[k] = extra[k]; }); }
    return o;
  }
  function upsert(id, config) {
    if (charts[id]) {
      charts[id].data = config.data; charts[id].update();
    } else {
      charts[id] = new Chart($(id).getContext("2d"), config);
    }
  }
  function barColors(values, key) {
    var t = data.thresholds[key];
    return values.map(function (v) { return t.critical !== null && v > t.critical ? COLORS.crit : v > t.warning ? COLORS.warn : COLORS.ok; });
  }
  function renderCharts() {
    if (!chartsOk) { $("chartError").hidden = false; return; }
    var names = data.devices.map(function (d) { return d.name; });
    var hist = data.history, labels = hist.map(function (h) { return h.time; });
    upsert("chLatency", { type: "line", data: { labels: labels, datasets: [{ label: "Average latency (ms, simulated)", data: hist.map(function (h) { return h.avg_latency; }), borderColor: COLORS.accent, backgroundColor: "rgba(45,212,191,.15)", fill: true, tension: .3 }] }, options: opts("Latency (ms)") });
    upsert("chTraffic", { type: "line", data: { labels: labels, datasets: [
      { label: "Inbound (Mbps, simulated)", data: hist.map(function (h) { return h.inbound; }), borderColor: COLORS.blue, tension: .3 },
      { label: "Outbound (Mbps, simulated)", data: hist.map(function (h) { return h.outbound; }), borderColor: COLORS.warn, tension: .3 }] }, options: opts("Traffic (Mbps)") });
    var bw = data.devices.map(function (d) { return d.bandwidth; });
    upsert("chBandwidth", { type: "bar", data: { labels: names, datasets: [{ label: "Bandwidth utilization (%)", data: bw, backgroundColor: barColors(bw, "bandwidth") }] }, options: opts("Utilization (%)", { max: 100 }) });
    var cpu = data.devices.map(function (d) { return d.cpu; });
    upsert("chCpu", { type: "bar", data: { labels: names, datasets: [{ label: "CPU utilization (%)", data: cpu, backgroundColor: barColors(cpu, "cpu") }] }, options: opts("Utilization (%)", { max: 100 }) });
    var sc = data.summary.status_counts;
    upsert("chStatus", { type: "doughnut", data: { labels: ["Online", "Warning", "Critical", "Offline"], datasets: [{ data: [sc.Online, sc.Warning, sc.Critical, sc.Offline], backgroundColor: [COLORS.ok, COLORS.warn, COLORS.crit, COLORS.off], borderColor: "#121c2e" }] },
      options: { responsive: true, maintainAspectRatio: false, animation: { duration: 300 }, plugins: { legend: { position: "bottom", labels: { color: COLORS.text } }, title: { display: true, text: "Devices by status", color: COLORS.text } } } });
  }

  function render() {
    $("scenarioName").textContent = data.scenario;
    renderCards(); renderHealth(); renderRecs(); renderDevices(); renderAlerts(); renderThresholds(); renderCharts();
  }

  /* ---------- navigation, buttons, clock ---------- */
  function show(view) {
    if (!TITLES[view]) { view = "overview"; }
    document.querySelectorAll(".view").forEach(function (v) { v.classList.toggle("active", v.id === "view-" + view); });
    document.querySelectorAll("nav a").forEach(function (a) { a.classList.toggle("active", a.dataset.view === view); });
    $("viewTitle").textContent = TITLES[view];
    $("sidebar").classList.remove("open");
    // Chart.js sizes canvases badly while hidden, so resize after the view appears.
    Object.keys(charts).forEach(function (k) { charts[k].resize(); });
  }
  window.addEventListener("hashchange", function () { show(location.hash.slice(1)); });
  $("menuBtn").addEventListener("click", function () { $("sidebar").classList.toggle("open"); });
  $("search").addEventListener("input", function () { if (data) { renderDevices(); } });
  $("statusFilter").addEventListener("change", function () { if (data) { renderDevices(); } });
  document.querySelectorAll("[data-action]").forEach(function (b) {
    b.addEventListener("click", function () {
      var a = b.dataset.action;
      load(a === "refresh" ? "/api/refresh" : "/api/simulate/" + a, "POST");
    });
  });
  function tick() { $("clock").textContent = new Date().toLocaleString(); }
  tick(); setInterval(tick, 1000);

  show(location.hash.slice(1));
  load("/api/metrics");
})();
