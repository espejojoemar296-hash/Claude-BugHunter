import json
import threading
import unittest
from http.server import ThreadingHTTPServer
from urllib.request import Request, urlopen
from urllib.error import HTTPError

from cbh.api import make_handler


class LocalApiTests(unittest.TestCase):
    def setUp(self):
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), make_handler("test-secret"))
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base = "http://127.0.0.1:" + str(self.server.server_port)

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)

    def request(self, path, token="test-secret"):
        req = Request(self.base + path, headers={"Authorization": "Bearer " + token})
        with urlopen(req, timeout=3) as response:
            return response.status, json.loads(response.read().decode("utf-8"))

    def test_health_requires_token(self):
        self.assertEqual(self.request("/health")[1]["service"], "claude-bughunter")
        req = Request(self.base + "/health")
        with self.assertRaises(HTTPError) as caught:
            urlopen(req, timeout=3)
        self.assertEqual(caught.exception.code, 401)

    def test_unknown_route_is_not_found(self):
        req = Request(self.base + "/missing", headers={"Authorization": "Bearer test-secret"})
        with self.assertRaises(HTTPError) as caught:
            urlopen(req, timeout=3)
        self.assertEqual(caught.exception.code, 404)
        payload = json.loads(caught.exception.read().decode("utf-8"))
        self.assertEqual(payload["error"], "not_found")

    def test_engagement_status_requires_token_and_is_available(self):
        status, payload = self.request("/engagement/status")
        self.assertEqual(status, 200)
        self.assertIn(payload["status"], ("idle", "running", "completed", "failed"))

    def test_engagement_run_rejects_path_traversal(self):
        body = json.dumps({"config": "../outside.json"}).encode("utf-8")
        req = Request(
            self.base + "/engagement/run", data=body, method="POST",
            headers={"Authorization": "Bearer test-secret", "Content-Type": "application/json"},
        )
        with self.assertRaises(HTTPError) as caught:
            urlopen(req, timeout=3)
        self.assertEqual(caught.exception.code, 400)

    def test_api_refuses_non_loopback_binding(self):
        from cbh.api import serve
        with self.assertRaises(ValueError):
            serve(host="0.0.0.0", port=8765)


if __name__ == "__main__":
    unittest.main()
