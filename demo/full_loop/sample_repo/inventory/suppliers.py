from datetime import date, timedelta


class Supplier:
    def __init__(self, name, lead_time_days, minimum_order):
        self.name = name
        self.lead_time_days = lead_time_days
        self.minimum_order = minimum_order

    def arrival(self, ordered_on):
        return ordered_on + timedelta(days=self.lead_time_days)


def reorder_quantity(available, target, minimum_order):
    shortfall = max(0, target - available)
    if shortfall == 0:
        return 0
    return max(shortfall, minimum_order)


def fastest(suppliers):
    if not suppliers:
        raise ValueError("No suppliers to choose from.")
    return min(suppliers, key=lambda supplier: (supplier.lead_time_days, supplier.name))


def schedule(suppliers, ordered_on=None):
    ordered_on = ordered_on or date(2026, 1, 1)
    return {supplier.name: supplier.arrival(ordered_on) for supplier in suppliers}
