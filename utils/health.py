import threading, time
from http.server import BaseHTTPRequestHandler, HTTPServer

try:
    from prometheus_client import generate_latest, CONTENT_TYPE_LATEST  # type: ignore
except Exception:  # pragma: no cover
    generate_latest = None  # type: ignore
    CONTENT_TYPE_LATEST = "text/plain; version=0.0.4; charset=utf-8"


class _H(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/healthz":
            self.send_response(200); self.end_headers(); self.wfile.write(b"ok")
        elif self.path == "/readyz":
            self.send_response(200); self.end_headers(); self.wfile.write(b"ready")
        elif self.path == "/metrics" and generate_latest is not None:
            try:
                output = generate_latest()
                self.send_response(200)
                self.send_header("Content-Type", CONTENT_TYPE_LATEST)
                self.end_headers()
                self.wfile.write(output)
            except Exception:
                self.send_response(500); self.end_headers()
        else:
            self.send_response(404); self.end_headers()

def start_health_server(host="0.0.0.0", port=9108):
    t = threading.Thread(target=lambda: HTTPServer((host, port), _H).serve_forever(), daemon=True)
    t.start()
    return t
