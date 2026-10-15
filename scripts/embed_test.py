"""Serve a throw-away host page that embeds the chat widget, to test it from this machine.

    python -m scripts.embed_test                      # the VPS demo widget on http://localhost:8080
    python -m scripts.embed_test --widget http://localhost:3000 --port 9000

The widget only lets sites listed in its WIDGET_ALLOWED_PARENTS frame it, so that
list must contain the origin printed below (scheme, host and port must match).
"""

import argparse
from http.server import BaseHTTPRequestHandler, HTTPServer

DEFAULT_WIDGET_URL = "https://chat.tringhiatech.vn:5010"
DEFAULT_PORT = 8080
LAUNCHER_LABEL = "Trợ lý ảo"
LAUNCHER_COLOR = "#0B5FFF"

PAGE_TEMPLATE = """<!doctype html>
<html lang="vi">
<meta charset="utf-8">
<title>Widget embed test</title>
<h1>Host page</h1>
<p>Widget: <code>{widget_url}</code>. The launcher should appear bottom-right.</p>
<script src="{widget_url}/embed.js" defer
        data-color="{color}" data-position="right" data-label="{label}"></script>
</html>
"""


class EmbedTestServer:
    """Serves one HTML page that loads the widget's embed.js."""

    def __init__(self, widget_url: str, port: int) -> None:
        self._port = port
        self._page = PAGE_TEMPLATE.format(
            widget_url=widget_url.rstrip("/"), color=LAUNCHER_COLOR, label=LAUNCHER_LABEL
        ).encode("utf-8")

    def serve(self) -> None:
        """Block serving the page until interrupted with Ctrl+C."""
        page = self._page

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self) -> None:  # noqa: N802 - http.server API
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(page)))
                self.end_headers()
                self.wfile.write(page)

        with HTTPServer(("0.0.0.0", self._port), Handler) as server:
            print(f"Open http://localhost:{self._port}/ and add that origin to WIDGET_ALLOWED_PARENTS.")
            try:
                server.serve_forever()
            except KeyboardInterrupt:
                print("Stopped.")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--widget", default=DEFAULT_WIDGET_URL, help="Widget base URL")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT, help="Port for this test page")
    args = parser.parse_args()
    EmbedTestServer(args.widget, args.port).serve()


if __name__ == "__main__":
    main()
