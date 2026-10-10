"""Run with:  python -m unittest -v   (uses Flask's test client, no server needed)"""
import unittest
import app as netapp


class NetSentinelTests(unittest.TestCase):
    def setUp(self):
        self.c = netapp.app.test_client()
        self.c.post("/api/simulate/reset")

    def post(self, name):
        r = self.c.post(f"/api/simulate/{name}")
        self.assertEqual(r.status_code, 200)
        return r.get_json()["data"]

    def test_home_page(self):
        r = self.c.get("/")
        self.assertEqual(r.status_code, 200)
        self.assertIn(b"NetPulse", r.data)

    def test_metrics_structure(self):
        j = self.c.get("/api/metrics").get_json()
        self.assertTrue(j["success"])
        d = j["data"]
        self.assertGreaterEqual(len(d["devices"]), 5)
        for k in ("summary", "health", "alerts", "recommendations", "history"):
            self.assertIn(k, d)

    def test_normal_is_healthy(self):
        d = self.post("normal")
        self.assertEqual(d["alerts"], [])
        self.assertGreaterEqual(d["health"]["score"], 90)
        self.assertEqual(d["recommendations"][0]["severity"], "ok")

    def test_warning_scenario(self):
        d = self.post("warning")
        sev = {a["severity"] for a in d["alerts"]}
        self.assertEqual(sev, {"warning"})
        self.assertTrue(50 <= d["health"]["score"] <= 74)

    def test_critical_scenario(self):
        d = self.post("critical")
        self.assertTrue(any(a["severity"] == "critical" for a in d["alerts"]))
        self.assertTrue(any(x["status"] == "Offline" for x in d["devices"]))
        self.assertLess(d["health"]["score"], 50)

    def test_score_order(self):
        n, w, c = (self.post(s)["health"]["score"] for s in ("normal", "warning", "critical"))
        self.assertTrue(n > w > c)

    def test_no_duplicate_alerts(self):
        d = self.post("critical")
        keys = [(a["device_id"], a["metric"]) for a in d["alerts"]]
        self.assertEqual(len(keys), len(set(keys)))

    def test_label_matches_score(self):
        for s in ("normal", "warning", "critical"):
            h = self.post(s)["health"]
            self.assertEqual(h["label"], netapp.label_for(h["score"]))

    def test_refresh_and_reset(self):
        self.post("critical")
        self.assertEqual(self.c.post("/api/refresh").status_code, 200)
        d = self.c.post("/api/simulate/reset").get_json()["data"]
        self.assertEqual(d["scenario"], "normal")
        self.assertEqual(d["alerts"], [])

    def test_errors_are_json(self):
        r = self.c.post("/api/simulate/bogus")
        self.assertEqual(r.status_code, 404)
        self.assertFalse(r.get_json()["success"])
        self.assertEqual(self.c.get("/api/simulate/normal").status_code, 405)


if __name__ == "__main__":
    unittest.main()
