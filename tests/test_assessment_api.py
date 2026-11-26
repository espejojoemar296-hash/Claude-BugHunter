import json
import threading
import unittest
from http.server import ThreadingHTTPServer
from urllib.request import Request, urlopen
from urllib.error import HTTPError
from unittest.mock import patch

from cbh.api import make_handler


class AssessmentApiTests(unittest.TestCase):
    def setUp(self):
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), make_handler("test-secret"))
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base = "http://127.0.0.1:" + str(self.server.server_port)

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)

    def call(self, path, body=None, method=None):
        data = None if body is None else json.dumps(body).encode("utf-8")
        req = Request(
            self.base + path, data=data, method=method,
            headers={"Authorization": "Bearer test-secret", "Content-Type": "application/json"},
        )
        with urlopen(req, timeout=3) as response:
            return response.status, json.loads(response.read().decode("utf-8"))

    def test_status_and_history_are_authenticated_get_routes(self):
        status, payload = self.call("/assessment/status")
        self.assertEqual(status, 200)
        self.assertIn(payload["status"], ("idle", "queued", "running", "completed", "stopped", "failed"))
        status, payload = self.call("/assessment/history")
        self.assertEqual(status, 200)
        self.assertIn("assessments", payload)

    def test_start_accepts_only_local_only_mode(self):
        with patch("cbh.assessment.start", return_value=(True, {"id": "unit-test", "status": "queued"})) as start:
            status, payload = self.call("/assessment/start", {"mode": "local_only", "program": "Demo"}, "POST")
        self.assertEqual(status, 202)
        self.assertTrue(payload["started"])
        start.assert_called_once()

        req = Request(
            self.base + "/assessment/start",
            data=json.dumps({"mode": "network"}).encode("utf-8"),
            method="POST",
            headers={"Authorization": "Bearer test-secret", "Content-Type": "application/json"},
        )
        with self.assertRaises(HTTPError) as caught:
            urlopen(req, timeout=3)
        self.assertEqual(caught.exception.code, 400)
        self.assertIn("live testing is blocked", caught.exception.read().decode("utf-8"))

    def test_emergency_stop_calls_backend_stop(self):
        with patch("cbh.assessment.stop", return_value=(True, {"status": "running", "stop_requested": True})) as stop:
            status, payload = self.call("/assessment/stop", {}, "POST")
        self.assertEqual(status, 200)
        self.assertTrue(payload["stop_requested"])
        stop.assert_called_once()


if __name__ == "__main__":
    unittest.main()
