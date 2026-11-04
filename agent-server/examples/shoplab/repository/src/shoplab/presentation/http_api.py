"""Small WSGI adapter; optional HTTP surface without third-party packages."""
import json
from dataclasses import asdict
from wsgiref.simple_server import make_server
from shoplab.application.quote_order import QuoteError, QuoteRequest
from shoplab.bootstrap import ShopServices, build_services
from shoplab.domain.shipping import DeliveryZone


def make_app(services: ShopServices | None = None):
    services = services or build_services()

    def app(environ, start_response):
        route = environ.get("PATH_INFO", "/")
        method = environ.get("REQUEST_METHOD", "GET")
        status = "200 OK"
        try:
            if method == "GET" and route == "/health":
                payload = {"status": "ok", "persistence": "memory"}
            elif method == "GET" and route == "/catalog":
                payload = [asdict(p) for p in services.list_products.execute()]
            elif method == "POST" and route == "/quotes":
                length = int(environ.get("CONTENT_LENGTH") or 0)
                if length < 1 or length > 8192:
                    raise ValueError("request body size must be between 1 and 8192 bytes")
                obj = json.loads(environ["wsgi.input"].read(length))
                if not isinstance(obj, dict):
                    raise ValueError("JSON object required")
                request = QuoteRequest(
                    sku=str(obj["sku"]), quantity=int(obj["quantity"]),
                    zone=DeliveryZone(obj.get("zone", "local")),
                    promotion_code=obj.get("promotion_code"),
                )
                payload = asdict(services.quote_order.execute(request))
                status = "201 Created"
            else:
                payload = {"error": "route not found"}
                status = "404 Not Found"
        except (ValueError, KeyError, TypeError, QuoteError, json.JSONDecodeError) as error:
            payload = {"error": str(error)}
            status = "400 Bad Request"
        body = json.dumps(payload, sort_keys=True).encode("utf-8")
        start_response(status, [("Content-Type", "application/json; charset=utf-8"),
                                ("Content-Length", str(len(body)))])
        return [body]
    return app


def main() -> None:
    # Development-only service: bind to loopback by default.
    with make_server("127.0.0.1", 8765, make_app()) as server:
        print("ShopLab HTTP adapter: http://127.0.0.1:8765")
        server.serve_forever()


if __name__ == "__main__":
    main()
