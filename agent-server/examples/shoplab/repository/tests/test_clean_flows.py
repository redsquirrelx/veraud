"""Functional checks: intentionally not an architectural conformance gate."""
import io
import json
import unittest
from shoplab.application.quote_order import QuoteRequest, QuoteError
from shoplab.bootstrap import build_services
from shoplab.domain.catalog import Product
from shoplab.domain.promotions import Promotion
from shoplab.domain.shipping import DeliveryZone, Parcel
from shoplab.presentation.cli import main as cli_main
from shoplab.presentation.http_api import make_app


class TestDomain(unittest.TestCase):
    def test_product_value_constraints(self):
        with self.assertRaises(ValueError):
            Product("", "item", 10, 1)
        with self.assertRaises(ValueError):
            Product("A", "item", -1, 1)

    def test_discount_floor_and_cap(self):
        promo = Promotion("PROMO", 50, 1000, 300)
        self.assertEqual(promo.discount_for(200), 0)
        self.assertEqual(promo.discount_for(2000), 300)

    def test_rounded_shipping_weight(self):
        self.assertEqual(Parcel(1001, DeliveryZone.LOCAL).billable_kilograms, 2)
        with self.assertRaises(ValueError):
            Parcel(0, DeliveryZone.LOCAL)


class TestUseCases(unittest.TestCase):
    def setUp(self):
        self.services = build_services()

    def test_catalog_filters_inactive(self):
        products = self.services.list_products.execute()
        self.assertEqual({p.sku for p in products}, {"BOOK", "PEN", "BAG"})

    def test_quote_without_promotion(self):
        result = self.services.quote_order.execute(QuoteRequest("BOOK", 2, DeliveryZone.LOCAL))
        self.assertEqual((result.subtotal_cents, result.discount_cents,
                          result.delivery_cents, result.total_cents), (3000, 0, 500, 3500))
        self.assertEqual(self.services.get_quote.execute(result.quote_id).total_cents, 3500)

    def test_quote_with_promotion(self):
        result = self.services.quote_order.execute(QuoteRequest(
            "BOOK", 2, DeliveryZone.NATIONAL, "WELCOME10"))
        self.assertEqual(result.discount_cents, 300)
        self.assertEqual(result.delivery_cents, 1000)
        self.assertEqual(result.total_cents, 3700)

    def test_capped_promotion(self):
        result = self.services.quote_order.execute(QuoteRequest(
            "BAG", 1, DeliveryZone.REMOTE, "SAVE20"))
        self.assertEqual(result.discount_cents, 700)
        self.assertEqual(result.delivery_cents, 1900)

    def test_unavailable_product(self):
        with self.assertRaises(QuoteError):
            self.services.quote_order.execute(QuoteRequest("ARCHIVE", 1, DeliveryZone.LOCAL))

    def test_unknown_product(self):
        with self.assertRaises(QuoteError):
            self.services.quote_order.execute(QuoteRequest("MISSING", 1, DeliveryZone.LOCAL))

    def test_bad_quantity(self):
        with self.assertRaises(QuoteError):
            self.services.quote_order.execute(QuoteRequest("PEN", 0, DeliveryZone.LOCAL))

    def test_bad_promotion(self):
        with self.assertRaises(QuoteError):
            self.services.quote_order.execute(QuoteRequest("PEN", 1, DeliveryZone.LOCAL, "NO"))

    def test_quotes_do_not_cross_service_instances(self):
        result = self.services.quote_order.execute(QuoteRequest("PEN", 1, DeliveryZone.LOCAL))
        self.assertIsNone(build_services().get_quote.execute(result.quote_id))


class TestInboundAdapters(unittest.TestCase):
    def test_cli_catalog(self):
        from contextlib import redirect_stdout
        buffer = io.StringIO()
        with redirect_stdout(buffer):
            status = cli_main(["catalog"])
        self.assertEqual(status, 0)
        self.assertEqual(len(json.loads(buffer.getvalue())), 3)

    def test_cli_invalid_quote(self):
        from contextlib import redirect_stdout
        buffer = io.StringIO()
        with redirect_stdout(buffer):
            status = cli_main(["quote", "--sku", "NO", "--quantity", "1"])
        self.assertEqual(status, 2)

    def wsgi_request(self, method, path, body=b""):
        response = {}
        def start(status, headers):
            response["status"] = status
            response["headers"] = headers
        environ = {"REQUEST_METHOD": method, "PATH_INFO": path,
                   "CONTENT_LENGTH": str(len(body)), "wsgi.input": io.BytesIO(body)}
        response["body"] = b"".join(make_app()(environ, start))
        return response

    def test_http_health(self):
        result = self.wsgi_request("GET", "/health")
        self.assertEqual(result["status"], "200 OK")

    def test_http_catalog(self):
        result = self.wsgi_request("GET", "/catalog")
        self.assertEqual(len(json.loads(result["body"])), 3)

    def test_http_quote(self):
        payload = json.dumps({"sku": "PEN", "quantity": 2, "zone": "local"}).encode()
        result = self.wsgi_request("POST", "/quotes", payload)
        self.assertEqual(result["status"], "201 Created")
        self.assertEqual(json.loads(result["body"])["total_cents"], 1000)

    def test_http_malformed(self):
        result = self.wsgi_request("POST", "/quotes", b"not json")
        self.assertEqual(result["status"], "400 Bad Request")

    def test_http_unknown_route(self):
        result = self.wsgi_request("GET", "/nope")
        self.assertEqual(result["status"], "404 Not Found")


class TestLegacyExtensions(unittest.TestCase):
    def test_recommendation_feature_still_executes(self):
        from shoplab.domain.recommendations import suggest_companion
        self.assertEqual(suggest_companion("BOOK"), "PEN")

    def test_discount_preview_still_executes(self):
        from shoplab.application.discount_preview import preview_discount
        self.assertEqual(preview_discount("WELCOME10", 1000), 100)

    def test_legacy_receipt_channel(self):
        from shoplab.infrastructure.receipt_delivery import LocalReceiptSender
        self.assertIn("500 cents", LocalReceiptSender().send("ORD-9", 500))

    def test_admin_catalog_snapshot(self):
        from shoplab.presentation.admin_catalog import raw_catalog_snapshot
        from shoplab.infrastructure.memory_catalog import MemoryProductCatalog
        self.assertEqual(raw_catalog_snapshot(MemoryProductCatalog())["BOOK"], 1500)
