import unittest

from inventory.orders import Order, allocate, fulfil
from inventory.stock import Bin, StockError, receive, release, reserve, ship


class StockTests(unittest.TestCase):
    def test_receive_reserve_ship(self):
        bin_ = Bin("A-1")
        self.assertEqual(receive(bin_, 10, "po-1"), 10)
        self.assertEqual(reserve(bin_, 4, "o-1"), 6)
        self.assertEqual(ship(bin_, 4, "o-1"), 6)
        self.assertEqual(bin_.reserved, 0)

    def test_release_and_errors(self):
        bin_ = Bin("A-2", quantity=5)
        reserve(bin_, 3, "o-2")
        self.assertEqual(release(bin_, 2, "o-2"), 4)
        with self.assertRaises(StockError):
            reserve(bin_, 10, "o-3")
        with self.assertRaises(StockError):
            ship(bin_, 2, "o-2")

    def test_order_allocation_rolls_back(self):
        bins = {"A": Bin("A", quantity=2), "B": Bin("B", quantity=1)}
        order = Order("o-9", {"A": 2, "B": 5})
        self.assertFalse(allocate(order, bins))
        self.assertEqual(bins["A"].reserved, 0)
        ok = Order("o-10", {"A": 1})
        self.assertTrue(allocate(ok, bins))
        self.assertEqual(fulfil(ok, bins), "shipped")
