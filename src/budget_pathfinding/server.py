"""A local-only standard-library simulator API; animation is outside measured search."""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import webbrowser
from .agent import Budget, METHODS, run_agent
from .controller import Rules
from .experiments import optimal_cost
from .grid import Grid, generate_grid

WEB_ROOT = Path(__file__).parent / "web"


def simulate(payload: dict) -> dict:
    size = int(payload.get("size", 20))
    if not 5 <= size <= 100:
        raise ValueError("Simulator size must be 5..100")
    if payload.get("grid"):
        data = payload["grid"]
        if int(data["width"]) > 100 or int(data["height"]) > 100:
            raise ValueError("Custom grid cannot exceed 100×100")
        grid = Grid.from_dict(data)
    else:
        grid = generate_grid(size, float(payload.get("density", .2)), int(payload.get("seed", 42)),
                             payload.get("structure", "random"), bool(payload.get("weighted", False)))
    if payload.get("generate_only"):
        return {"grid": grid.to_dict()}
    cap = int(payload.get("budget", 1000))
    if not 0 <= cap <= 10000:
        raise ValueError("Simulator expansion budget must be 0..10000")
    method = payload.get("method", "adaptive")
    if method not in METHODS:
        raise ValueError("Unknown method")
    rules = Rules()
    result = run_agent(grid, method, Budget(cap), rules, trace=True)
    comparisons = []
    for name in dict.fromkeys((method, "adaptive", "astar", "weighted_3", "ara")):
        compared = result if name == method else run_agent(grid, name, Budget(cap), rules)
        comparisons.append({"method": name, "status": compared.status, "cost": compared.cost,
                            "expansions": compared.expansions, "seconds": compared.elapsed_seconds,
                            "switches": compared.switches})
    return {"grid": grid.to_dict(), "result": result.to_dict(), "comparisons": comparisons,
            "optimal_cost_evaluation_only": optimal_cost(grid), "rules": rules.to_dict()}


class Handler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        pass

    def send_json(self, code: int, payload: dict):
        encoded = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(encoded)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(encoded)

    def do_GET(self):
        if self.path == "/api/health":
            return self.send_json(200, {"status": "ok", "methods": METHODS})
        paths = {"/": ("index.html", "text/html"), "/app.js": ("app.js", "text/javascript"),
                 "/styles.css": ("styles.css", "text/css")}
        if self.path not in paths:
            return self.send_json(404, {"error": "Not found"})
        filename, mime = paths[self.path]
        encoded = (WEB_ROOT / filename).read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", mime + "; charset=utf-8")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)

    def do_POST(self):
        if self.path != "/api/run":
            return self.send_json(404, {"error": "Not found"})
        # Prevent cross-origin pages from invoking expensive local experiments.
        origin = self.headers.get("Origin")
        allowed = {f"http://127.0.0.1:{self.server.server_port}", f"http://localhost:{self.server.server_port}"}
        if origin and origin not in allowed:
            return self.send_json(403, {"error": "Local simulator origin required"})
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if not 0 < length <= 1_000_000:
                raise ValueError("Request too large or empty")
            payload = json.loads(self.rfile.read(length))
            if not isinstance(payload, dict):
                raise ValueError("JSON object required")
            self.send_json(200, simulate(payload))
        except (ValueError, KeyError, TypeError, OverflowError) as exc:
            self.send_json(400, {"error": str(exc)})


def serve(port: int = 8765, open_browser: bool = True):
    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    url = f"http://127.0.0.1:{server.server_port}"
    print(f"Simulator: {url}  (Ctrl+C to stop)", flush=True)
    if open_browser:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
