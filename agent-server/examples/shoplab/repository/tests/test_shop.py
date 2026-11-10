import unittest
from shoplab.application.checkout import process_order
from shoplab.domain.models import Order
from shoplab.inventory import available_stock
from shoplab.inventory._store import STOCK


class TestShop(unittest.TestCase):
    def setUp(self):
        STOCK.clear()
        STOCK.update({"BOOK": 10, "PEN": 20})

    def test_successful_purchase(self):
        ok, total = process_order(Order("ORD-001", "BOOK", 2, 15))
        self.assertTrue(ok)
        self.assertEqual(total, 30)
        self.assertEqual(available_stock("BOOK"), 8)

    def test_disallowed_order(self):
        ok, remaining = process_order(Order("ORD-002", "BLOCKED", 1, 15))
        self.assertFalse(ok)
        self.assertEqual(remaining, 0)


if __name__ == "__main__":
    unittest.main()
