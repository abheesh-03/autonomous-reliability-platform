#!/usr/bin/env python3
"""Phase 16 Gate 9: a disposable, standalone sample external
application -- deliberately separate from this repository's own
checkout/payment/inventory/notification demonstration services, and
NOT part of the platform's own Docker Compose stack (it runs
standalone, outside that network, exactly as a real customer's own
external application would).

Pure Python standard library only -- no new project dependency, and
deliberately NOT the official OpenTelemetry Python SDK. This is a
minimal, hand-built OTLP/HTTP JSON client, not a vendor SDK
integration -- it emits exactly the bounded, documented export shape
services/control-plane/src/control_plane/domain/telemetry.py accepts
(see that module's own docstring). This is the ONE path actually
validated end-to-end this round (see
docs/architecture/phase-16-secure-telemetry-onboarding.md's own
honesty note about SDK language coverage) -- the real, official
OpenTelemetry SDKs for Python/Node/Java/Go are a SEPARATE, real,
documented integration path (see the in-app setup instructions this
platform's own web console shows after generating a credential), not
exercised by this specific sample this round.

Usage:
  OTEL_INGEST_ENDPOINT=http://127.0.0.1:8000/api/v1/telemetry/otlp/v1/metrics \\
  OTEL_BEARER_TOKEN=cred_xxx.yyy \\
  python3 app.py

Then:
  curl http://127.0.0.1:9100/work          # a real, successful request
  curl -X POST http://127.0.0.1:9100/fail-mode -d '{"enabled": true}'
  curl http://127.0.0.1:9100/work          # now a real, failing request
"""

from __future__ import annotations

import json
import os
import random
import threading
import time
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

LISTEN_PORT = int(os.environ.get("OTEL_SAMPLE_APP_PORT", "9100"))
INGEST_ENDPOINT = os.environ.get("OTEL_INGEST_ENDPOINT", "http://127.0.0.1:8000/api/v1/telemetry/otlp/v1/metrics")
BEARER_TOKEN = os.environ.get("OTEL_BEARER_TOKEN", "")
EXPORT_INTERVAL_SECONDS = float(os.environ.get("OTEL_EXPORT_INTERVAL_SECONDS", "2"))

_lock = threading.Lock()
_fail_mode = False
# One aggregated bucket per (method, route, status_code) since the
# last export -- mirrors a real OTel SDK's own histogram aggregation
# behavior within one export interval (see domain/telemetry.py's own
# "HONEST MODELING NOTE").
_pending: dict[tuple[str, str, int], dict[str, float]] = {}
# Correction round (item 1): this app always behaves as a real DELTA
# exporter -- it clears `_pending` after every export, so each export
# already represents "since the last export," never a running total.
# The PREVIOUS round declared `aggregationTemporality: 2` (CUMULATIVE)
# on this exact DELTA data -- a mislabeling that, against a server
# that (also incorrectly) treated every export as delta, happened to
# work by coincidence, but would double-count against any spec-correct
# CUMULATIVE-aware consumer. `_window_start_nanos` tracks the real
# start of the CURRENT open delta interval, so each export's
# `startTimeUnixNano` is the time since the previous real export (or
# app start, for the first one) -- not a fixed, never-advancing value.
_window_start_nanos = int(time.time() * 1_000_000_000)


def record_observation(method: str, route: str, status_code: int, duration_seconds: float) -> None:
    key = (method, route, status_code)
    with _lock:
        bucket = _pending.setdefault(key, {"count": 0, "sum": 0.0})
        bucket["count"] += 1
        bucket["sum"] += duration_seconds


def export_loop() -> None:
    global _window_start_nanos
    while True:
        time.sleep(EXPORT_INTERVAL_SECONDS)
        with _lock:
            if not _pending:
                # No observations since the last export -- leave
                # `_window_start_nanos` where it is; the delta interval
                # simply stays open until there is something real to
                # report, which is correct DELTA semantics (never
                # export an empty/fabricated interval).
                continue
            window_start_nanos = _window_start_nanos
            data_points = []
            now_nanos = int(time.time() * 1_000_000_000)
            for (method, route, status_code), bucket in _pending.items():
                data_points.append(
                    {
                        "attributes": [
                            {"key": "http.request.method", "value": {"stringValue": method}},
                            {"key": "http.route", "value": {"stringValue": route}},
                            {"key": "http.response.status_code", "value": {"intValue": str(status_code)}},
                        ],
                        "startTimeUnixNano": str(window_start_nanos),
                        "timeUnixNano": str(now_nanos),
                        "count": str(int(bucket["count"])),
                        "sum": bucket["sum"],
                    }
                )
            _pending.clear()
            _window_start_nanos = now_nanos

        payload = {
            "resourceMetrics": [
                {
                    "resource": {"attributes": [{"key": "service.name", "value": {"stringValue": "otel-sample-app"}}]},
                    "scopeMetrics": [
                        {
                            "metrics": [
                                {
                                    "name": "http.server.request.duration",
                                    "unit": "s",
                                    # DELTA (1) -- this export's count/sum
                                    # are since `startTimeUnixNano` above
                                    # (the previous real export, or app
                                    # start), never a running total. The
                                    # backend now requires this exact
                                    # value and rejects CUMULATIVE/
                                    # unspecified outright.
                                    "histogram": {"dataPoints": data_points, "aggregationTemporality": 1},
                                }
                            ]
                        }
                    ],
                }
            ]
        }
        body = json.dumps(payload).encode("utf-8")
        request = urllib.request.Request(
            INGEST_ENDPOINT,
            data=body,
            method="POST",
            headers={"Content-Type": "application/json", "Authorization": f"Bearer {BEARER_TOKEN}"},
        )
        try:
            with urllib.request.urlopen(request, timeout=10) as response:
                print(f"[otel-sample-app] exported {len(data_points)} data point(s) -> HTTP {response.status}")
        except urllib.error.HTTPError as exc:
            print(f"[otel-sample-app] export REJECTED: HTTP {exc.code} {exc.read().decode('utf-8', 'replace')}")
        except urllib.error.URLError as exc:
            print(f"[otel-sample-app] export FAILED: could not reach {INGEST_ENDPOINT}: {exc}")


class Handler(BaseHTTPRequestHandler):
    def log_message(self, format: str, *args) -> None:  # noqa: A002 - BaseHTTPRequestHandler's own signature
        pass  # quiet; export_loop's own prints are the signal that matters

    def do_GET(self) -> None:
        if self.path == "/work":
            self._handle_work()
            return
        if self.path == "/healthz":
            self._respond(200, {"status": "ok"})
            return
        self._respond(404, {"error": "not found"})

    def do_POST(self) -> None:
        if self.path == "/fail-mode":
            global _fail_mode
            length = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(length) or b"{}")
            with _lock:
                _fail_mode = bool(body.get("enabled", False))
            self._respond(200, {"fail_mode": _fail_mode})
            return
        self._respond(404, {"error": "not found"})

    def _handle_work(self) -> None:
        start = time.monotonic()
        # A real, small, variable amount of work -- never instant,
        # never suspiciously uniform.
        time.sleep(random.uniform(0.01, 0.08))
        with _lock:
            should_fail = _fail_mode
        status_code = 500 if should_fail else 200
        duration = time.monotonic() - start
        record_observation("GET", "/work", status_code, duration)
        if should_fail:
            self._respond(500, {"error": "simulated downstream failure"})
        else:
            self._respond(200, {"result": "ok", "duration_seconds": round(duration, 4)})

    def _respond(self, status: int, body: dict) -> None:
        payload = json.dumps(body).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)


def main() -> None:
    if not BEARER_TOKEN:
        print("WARNING: OTEL_BEARER_TOKEN is not set -- every export will be rejected with 401.")
    threading.Thread(target=export_loop, daemon=True).start()
    server = ThreadingHTTPServer(("0.0.0.0", LISTEN_PORT), Handler)
    print(f"[otel-sample-app] listening on :{LISTEN_PORT}, exporting to {INGEST_ENDPOINT} every {EXPORT_INTERVAL_SECONDS}s")
    server.serve_forever()


if __name__ == "__main__":
    main()
