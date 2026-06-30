#!/usr/bin/env python3
import json
import os
import sys
import time
import threading
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

NVIDIA_API_KEY = os.environ.get("NVIDIA_API_KEY", "").strip()
RPM = int(os.environ.get("NVIDIA_PROXY_RPM", "20"))
PORT = int(os.environ.get("NVIDIA_PROXY_PORT", "18001"))
UPSTREAM_BASE = os.environ.get("NVIDIA_UPSTREAM_BASE", "https://integrate.api.nvidia.com").rstrip("/")
MIN_INTERVAL = 60.0 / max(RPM, 1)
MAX_RETRIES = int(os.environ.get("NVIDIA_PROXY_MAX_RETRIES", "5"))

lock = threading.Lock()
next_allowed_time = 0.0


def wait_for_slot():
    global next_allowed_time
    with lock:
        now = time.monotonic()
        wait_s = max(0.0, next_allowed_time - now)
        if wait_s > 0:
            print(f"[rate-limit] sleeping {wait_s:.2f}s", flush=True)
            time.sleep(wait_s)

        next_allowed_time = time.monotonic() + MIN_INTERVAL


def parse_retry_after(headers):
    value = headers.get("Retry-After")
    if not value:
        return None
    try:
        return float(value)
    except Exception:
        return None


class ProxyHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *args):
        print("[%s] %s" % (self.log_date_time_string(), fmt % args), flush=True)

    def _send(self, status, body, content_type="application/json"):
        if isinstance(body, str):
            body = body.encode("utf-8")

        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Connection", "close")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path == "/healthz":
            self._send(
                200,
                json.dumps(
                    {
                        "ok": True,
                        "rpm": RPM,
                        "minIntervalSeconds": MIN_INTERVAL,
                        "upstream": UPSTREAM_BASE,
                    }
                ),
            )
            return
        self._proxy()

    def do_POST(self):
        self._proxy()

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "authorization,content-type")
        self.send_header("Access-Control-Allow-Methods", "GET,POST,OPTIONS")
        self.end_headers()

    def _proxy(self):
        length = int(self.headers.get("Content-Length", "0"))
        body = self.rfile.read(length) if length > 0 else b""
        target = UPSTREAM_BASE + self.path

        headers = {}
        incoming_authorization = self.headers.get("Authorization", "").strip()
        for key, value in self.headers.items():
            lk = key.lower()
            if lk in ("host", "content-length", "connection", "authorization"):
                continue
            headers[key] = value

        if NVIDIA_API_KEY:
            headers["Authorization"] = f"Bearer {NVIDIA_API_KEY}"
        elif incoming_authorization:
            headers["Authorization"] = incoming_authorization
        else:
            self._send(
                401,
                json.dumps(
                    {
                        "error": {
                            "message": "NVIDIA_API_KEY is missing and request had no Authorization header",
                            "type": "proxy_auth_error",
                        }
                    }
                ),
            )
            return

        if "Content-Type" not in headers and body:
            headers["Content-Type"] = "application/json"

        for attempt in range(MAX_RETRIES + 1):
            wait_for_slot()

            req = urllib.request.Request(
                target,
                data=body if self.command != "GET" else None,
                headers=headers,
                method=self.command,
            )

            try:
                with urllib.request.urlopen(req, timeout=900) as resp:
                    resp_body = resp.read()
                    content_type = resp.headers.get("Content-Type", "application/json")
                    self._send(resp.status, resp_body, content_type)
                    return

            except urllib.error.HTTPError as e:
                err_body = e.read()
                status = e.code
                retry_after = parse_retry_after(e.headers)
                retryable = status in (429, 500, 502, 503, 504)

                print(
                    f"[upstream] HTTP {status}, attempt {attempt + 1}/{MAX_RETRIES + 1}",
                    flush=True,
                )

                if retryable and attempt < MAX_RETRIES:
                    sleep_s = retry_after if retry_after is not None else min(120, 15 * (attempt + 1))
                    print(f"[retry] waiting {sleep_s:.1f}s before retry", flush=True)
                    time.sleep(sleep_s)
                    continue

                content_type = e.headers.get("Content-Type", "application/json")
                self._send(status, err_body, content_type)
                return

            except Exception as e:
                print(f"[proxy-error] {repr(e)}", flush=True)
                if attempt < MAX_RETRIES:
                    sleep_s = min(120, 10 * (attempt + 1))
                    print(f"[retry] waiting {sleep_s:.1f}s before retry", flush=True)
                    time.sleep(sleep_s)
                    continue

                error_body = json.dumps(
                    {
                        "error": {
                            "message": f"NVIDIA proxy failed after retries: {repr(e)}",
                            "type": "proxy_error",
                        }
                    }
                )
                self._send(502, error_body)
                return


def main():
    if not NVIDIA_API_KEY:
        print("NVIDIA_API_KEY is not set; proxy will forward incoming Authorization headers", flush=True)

    server = ThreadingHTTPServer(("127.0.0.1", PORT), ProxyHandler)
    print(f"NVIDIA rate-limit proxy listening on http://127.0.0.1:{PORT}/v1", flush=True)
    print(f"RPM limit: {RPM}", flush=True)
    print(f"Upstream: {UPSTREAM_BASE}", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(0)
