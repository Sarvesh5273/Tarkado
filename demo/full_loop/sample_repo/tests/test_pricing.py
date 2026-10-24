import unittest
from decimal import Decimal

from inventory.pricing import bulk_discount, line_total, unit_price, with_tax


class PricingTests(unittest.TestCase):
    def test_unit_price_and_tax(self):
        self.assertEqual(unit_price("10.00", 15), Decimal("8.50"))
        self.assertEqual(with_tax("8.50", 18), Decimal("10.03"))

    def test_bulk_tiers(self):
        tiers = [(10, 5), (50, 10)]
        self.assertEqual(bulk_discount(9, tiers), 0)
        self.assertEqual(bulk_discount(60, tiers), 10)
        self.assertEqual(line_total("2.00", 50, tiers), Decimal("90.00"))
