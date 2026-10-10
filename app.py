"""
NetSentinel / NetPulse - simulation-based network performance dashboard.

ALL DATA IS SIMULATED. No real device is polled, pinged or monitored.

Code layout (each concern is a separate function):
  1. THRESHOLDS / SCENARIOS  - configuration and deterministic scenario data
  2. generate_devices()      - Network Simulation Engine
  3. calculate_health()      - health score algorithm
  4. generate_alerts()       - threshold-based alert detection
  5. build_recommendations() - recommendation engine
  6. Flask routes            - REST API returning JSON
"""
from datetime import datetime
import random
import threading

from flask import Flask, jsonify, render_template

app = Flask(__name__)
lock = threading.Lock()          # protects the shared simulation state

# ---------------------------------------------------------------- 1. CONFIG
# (warning, critical) limits. None = no critical limit for that metric.
THRESHOLDS = {
    "cpu":         {"label": "CPU utilization",       "unit": "%",  "warning": 80,  "critical": 95},
    "memory":      {"label": "Memory utilization",    "unit": "%",  "warning": 85,  "critical": 95},
    "latency":     {"label": "Latency",               "unit": "ms", "warning": 100, "critical": 200},
    "packet_loss": {"label": "Packet loss",           "unit": "%",  "warning": 2,   "critical": 5},
    "bandwidth":   {"label": "Bandwidth utilization", "unit": "%",  "warning": 80,  "critical": None},
}

ACTIONS = {
    "cpu": "Investigate processes or services consuming CPU resources; consider load balancing or scaling.",
    "memory": "Review memory utilization and application load; look for leaks and consider adding memory.",
    "latency": "Investigate congestion or overloaded network paths; check routing and QoS settings.",
    "packet_loss": "Investigate link quality, cabling and interface errors (CRC, drops, duplex mismatch).",
    "bandwidth": "Review traffic usage by application and consider traffic prioritization or a link upgrade.",
    "offline": "Check device power, availability and connectivity (cables, uplink port, management access).",
}

# Static device inventory. IPs are from the documentation range 192.0.2.0/24 (RFC 5737).
INVENTORY = [
    {"id": 1, "name": "Core Router",        "type": "Router",   "ip": "192.0.2.1",  "capacity": 1000},
    {"id": 2, "name": "Access Switch",      "type": "Switch",   "ip": "192.0.2.10", "capacity": 1000},
    {"id": 3, "name": "Application Server", "type": "Server",   "ip": "192.0.2.21", "capacity": 1000},
    {"id": 4, "name": "Database Server",    "type": "Server",   "ip": "192.0.2.22", "capacity": 1000},
    {"id": 5, "name": "Firewall",           "type": "Firewall", "ip": "192.0.2.254", "capacity": 1000},
    {"id": 6, "name": "Wireless AP",        "type": "Access Point", "ip": "192.0.2.40", "capacity": 300},
]

# Base metrics per scenario, in inventory order: cpu, memory, latency(ms), packet_loss(%), bandwidth(%)
# None = device is offline in that scenario.
SCENARIOS = {
    "normal": [
        (32, 45, 12, 0.1, 48), (24, 38, 8, 0.0, 35), (41, 58, 22, 0.2, 52),
        (47, 63, 18, 0.1, 44), (36, 52, 15, 0.3, 57), (28, 41, 25, 0.4, 39),
    ],
    "warning": [
        (84, 60, 60, 0.5, 83), (30, 45, 12, 0.2, 86), (78, 89, 120, 1.0, 70),
        (70, 70, 40, 2.8, 60), (55, 60, 35, 0.5, 65), (40, 50, 45, 1.0, 55),
    ],
    "critical": [
        (98, 90, 230, 6.5, 92), None, (88, 93, 150, 3.5, 85),
        (92, 97.5, 210, 5.8, 88), (70, 70, 60, 1.0, 82), (50, 55, 40, 0.8, 50),
    ],
}
# Maximum random wobble added to each base value: cpu, memory, latency(fraction), loss, bandwidth.
JITTER = (1.5, 1.5, 0.03, 0.1, 1.5)

# Health score weights (sum = 1.0) and the (good, bad) range used for sub-scores.
WEIGHTS = {"latency": 0.20, "packet_loss": 0.25, "cpu": 0.15, "memory": 0.10,
           "bandwidth": 0.15, "availability": 0.15}
RANGES = {"latency": (20, 200), "packet_loss": (0.5, 6), "cpu": (40, 100),
          "memory": (50, 100), "bandwidth": (50, 100)}

state = {"scenario": "normal", "counter": 0, "history": []}


def now_str():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


# ------------------------------------------------- 2. SIMULATION ENGINE
def generate_devices(scenario, counter):
    """Create device metrics = deterministic base values + small seeded jitter.
    The same (scenario, counter) always yields the same numbers."""
    rng = random.Random(f"{scenario}-{counter}")
    ts, devices = now_str(), []
    for inv, base in zip(INVENTORY, SCENARIOS[scenario]):
        d = dict(inv, last_updated=ts, offline=base is None)
        if base is None:
            d.update(cpu=0, memory=0, latency=0, packet_loss=0, bandwidth=0, inbound=0, outbound=0)
        else:
            cpu, mem, lat, loss, bw = base
            cpu = min(100, max(0, cpu + rng.uniform(-JITTER[0], JITTER[0])))
            mem = min(100, max(0, mem + rng.uniform(-JITTER[1], JITTER[1])))
            lat = max(1, lat * (1 + rng.uniform(-JITTER[2], JITTER[2])))
            loss = max(0, loss + rng.uniform(-JITTER[3], JITTER[3]))
            bw = min(100, max(0, bw + rng.uniform(-JITTER[4], JITTER[4])))
            used = bw / 100 * inv["capacity"]          # Mbps in use
            share = rng.uniform(0.55, 0.65)            # inbound share of traffic
            d.update(cpu=round(cpu, 1), memory=round(mem, 1), latency=round(lat, 1),
                     packet_loss=round(loss, 2), bandwidth=round(bw, 1),
                     inbound=round(used * share, 1), outbound=round(used * (1 - share), 1))
        devices.append(d)
    return devices


# ------------------------------------------------- 4. ALERT DETECTION
def generate_alerts(devices):
    """One alert per device per metric. Critical is checked first so a metric never
    produces both a critical and a warning alert. An offline device gets ONE alert."""
    alerts, ts = [], now_str()
    for d in devices:
        if d["offline"]:
            alerts.append({"severity": "critical", "device": d["name"], "device_id": d["id"],
                           "metric": "offline", "description": "Device is offline / unreachable (simulated)",
                           "value": "Offline", "threshold": "Must be reachable", "timestamp": ts,
                           "action": ACTIONS["offline"]})
            continue
        for key, t in THRESHOLDS.items():
            value, sev, limit = d[key], None, None
            if t["critical"] is not None and value > t["critical"]:
                sev, limit = "critical", t["critical"]
            elif value > t["warning"]:
                sev, limit = "warning", t["warning"]
            if sev:
                alerts.append({"severity": sev, "device": d["name"], "device_id": d["id"], "metric": key,
                               "description": f'{t["label"]} is {sev}',
                               "value": f'{value}{t["unit"]}', "threshold": f'> {limit}{t["unit"]}',
                               "timestamp": ts, "action": ACTIONS[key]})
    alerts.sort(key=lambda a: (a["severity"] != "critical", a["device_id"]))
    return alerts


def apply_status(devices, alerts):
    """Device status comes from its alerts: Offline > Critical > Warning > Online."""
    for d in devices:
        sevs = {a["severity"] for a in alerts if a["device_id"] == d["id"]}
        d["status"] = ("Offline" if d["offline"] else "Critical" if "critical" in sevs
                       else "Warning" if "warning" in sevs else "Online")


# ------------------------------------------------- 3. HEALTH SCORE
def sub_score(value, good, bad):
    """100 when value <= good, 0 when value >= bad, linear in between."""
    if value <= good:
        return 100.0
    if value >= bad:
        return 0.0
    return 100.0 * (bad - value) / (bad - good)


def label_for(score):
    return ("Excellent" if score >= 90 else "Good" if score >= 75
            else "Warning" if score >= 50 else "Critical")


def calculate_health(devices):
    """Weighted score 0-100 built from network-wide sub-scores.
    Metric sub-scores are scored per device and averaged over the reachable devices
    (a 70/30 blend of average and worst device, so one bad device is not hidden)."""
    online = [d for d in devices if not d["offline"]]
    parts = {}
    for key, (good, bad) in RANGES.items():
        scores = [sub_score(d[key], good, bad) for d in online] or [0]
        parts[key] = 0.7 * (sum(scores) / len(scores)) + 0.3 * min(scores)
    parts["availability"] = 100.0 * len(online) / len(devices)
    score = round(sum(parts[k] * w for k, w in WEIGHTS.items()))
    score = max(0, min(100, score))
    return {"score": score, "label": label_for(score),
            "breakdown": {k: round(v, 1) for k, v in parts.items()}}


def summarize(devices, alerts, health):
    online = [d for d in devices if not d["offline"]]
    avg = lambda k: round(sum(d[k] for d in online) / len(online), 1) if online else 0
    problem_ids = {a["device_id"] for a in alerts}
    return {"total_devices": len(devices), "online_devices": len(online),
            "offline_devices": len(devices) - len(online),
            "devices_with_issues": len(problem_ids),
            "avg_latency": avg("latency"), "avg_bandwidth": avg("bandwidth"),
            "avg_packet_loss": avg("packet_loss"), "avg_cpu": avg("cpu"),
            "total_inbound": round(sum(d["inbound"] for d in devices), 1),
            "total_outbound": round(sum(d["outbound"] for d in devices), 1),
            "health_score": health["score"], "health_label": health["label"],
            "critical_alerts": sum(a["severity"] == "critical" for a in alerts),
            "warning_alerts": sum(a["severity"] == "warning" for a in alerts),
            "status_counts": {s: sum(d["status"] == s for d in devices)
                              for s in ("Online", "Warning", "Critical", "Offline")}}


# ------------------------------------------------- 5. RECOMMENDATIONS
def build_recommendations(alerts):
    if not alerts:
        return [{"severity": "ok", "title": "Network is healthy",
                 "detail": "All simulated metrics are within their thresholds.",
                 "action": "No action required. Continue routine monitoring."}]
    return [{"severity": a["severity"], "title": f'{a["device"]}: {a["description"]}',
             "detail": f'Detected {a["value"]} (threshold {a["threshold"]}).',
             "action": a["action"]} for a in alerts]


# ------------------------------------------------- state + snapshot
def record_history(devices, summary):
    state["history"].append({"time": datetime.now().strftime("%H:%M:%S"),
                             "avg_latency": summary["avg_latency"],
                             "inbound": summary["total_inbound"], "outbound": summary["total_outbound"],
                             "health_score": summary["health_score"]})
    state["history"] = state["history"][-20:]


def snapshot(record=True):
    devices = generate_devices(state["scenario"], state["counter"])
    alerts = generate_alerts(devices)
    apply_status(devices, alerts)
    health = calculate_health(devices)
    summary = summarize(devices, alerts, health)
    if record:
        record_history(devices, summary)
    return {"scenario": state["scenario"], "simulated": True, "generated_at": now_str(),
            "devices": devices, "summary": summary, "health": health,
            "alerts": alerts, "recommendations": build_recommendations(alerts),
            "history": state["history"], "thresholds": THRESHOLDS}


def seed_history():
    """Start with 10 normal data points so the time-series charts are not empty."""
    state.update(scenario="normal", counter=0, history=[])
    for i in range(10):
        state["counter"] = i
        snapshot()
    state["counter"] = 10


def ok(message, data):
    return jsonify({"success": True, "message": message, "data": data})


def fail(message, code):
    return jsonify({"success": False, "message": message, "data": None}), code


# ------------------------------------------------- 6. ROUTES
@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/metrics")
def api_metrics():
    with lock:
        return ok("Current simulated metrics", snapshot(record=False))


@app.route("/api/alerts")
def api_alerts():
    with lock:
        snap = snapshot(record=False)
        return ok("Current alerts", {"alerts": snap["alerts"], "recommendations": snap["recommendations"]})


@app.route("/api/thresholds")
def api_thresholds():
    return ok("Alert thresholds", THRESHOLDS)


@app.route("/api/refresh", methods=["POST"])
def api_refresh():
    with lock:
        state["counter"] += 1
        return ok("Metrics refreshed (new simulated sample)", snapshot())


@app.route("/api/simulate/<name>", methods=["POST"])
def api_simulate(name):
    if name not in ("normal", "warning", "critical", "reset"):
        return fail(f"Unknown scenario '{name}'. Use normal, warning, critical or reset.", 404)
    with lock:
        if name == "reset":
            seed_history()
            return ok("Dashboard reset to the initial normal scenario", snapshot(record=False))
        state["scenario"] = name
        state["counter"] += 1
        return ok(f"{name.capitalize()} scenario activated", snapshot())


@app.errorhandler(404)
def not_found(_):
    return fail("Resource not found", 404)


@app.errorhandler(405)
def bad_method(_):
    return fail("Method not allowed for this endpoint", 405)


@app.errorhandler(500)
def server_error(_):
    return fail("Internal server error", 500)


seed_history()

if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000, debug=False)
