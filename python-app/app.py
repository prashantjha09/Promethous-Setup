"""Small Python service for the Prometheus lab.

GET /metrics is the page Prometheus scrapes.
The prometheus_client library also publishes process memory and CPU on that page.
"""

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse
import time

from prometheus_client import (
    CONTENT_TYPE_LATEST,
    Counter,
    Gauge,
    Histogram,
    generate_latest,
)

REQUESTS = Counter(
    "python_requests_total",
    "HTTP requests handled by this process",
    ["path"],
)
WORK_SECONDS = Histogram(
    "python_work_seconds",
    "Seconds spent inside POST /work",
)
QUEUE_DEPTH = Gauge(
    "python_queue_depth",
    "Items this process is holding",
)

queue_depth = 0


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        path = urlparse(self.path).path
        if path == "/metrics":
            body = generate_latest()
            self.send_response(200)
            self.send_header("Content-Type", CONTENT_TYPE_LATEST)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        if path == "/health":
            self._text(200, "ok")
            return
        self._text(404, "not found")

    def do_POST(self):
        global queue_depth
        parsed = urlparse(self.path)
        query = parse_qs(parsed.query)
        REQUESTS.labels(path=parsed.path).inc()

        if parsed.path == "/work":
            seconds = _number(query, "seconds", 0.2, upper=5)
            with WORK_SECONDS.time():
                time.sleep(seconds)
            self._text(200, f"worked {seconds}s")
            return

        if parsed.path == "/queue/add":
            queue_depth += int(_number(query, "n", 1, upper=100))
            QUEUE_DEPTH.set(queue_depth)
            self._text(200, f"depth {queue_depth}")
            return

        if parsed.path == "/queue/clear":
            queue_depth = 0
            QUEUE_DEPTH.set(0)
            self._text(200, "depth 0")
            return

        self._text(404, "not found")

    def _text(self, status, body):
        data = body.encode()
        self.send_response(status)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, fmt, *args):
        return


def _number(query, name, default, upper):
    raw = query.get(name, [str(default)])[0]
    try:
        value = float(raw)
    except ValueError:
        value = default
    return min(max(value, 0), upper)


if __name__ == "__main__":
    server = ThreadingHTTPServer(("0.0.0.0", 8000), Handler)
    print("listening on 8000", flush=True)
    server.serve_forever()
