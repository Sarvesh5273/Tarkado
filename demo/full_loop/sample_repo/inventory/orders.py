from .stock import StockError, reserve, ship


class Order:
    def __init__(self, order_id, lines):
        if not lines:
            raise ValueError("An order needs at least one line.")
        self.order_id = order_id
        self.lines = dict(lines)
        self.status = "open"

    def total_units(self):
        return sum(self.lines.values())


def allocate(order, bins):
    reserved = []
    try:
        for sku, amount in order.lines.items():
            reserve(bins[sku], amount, order.order_id)
            reserved.append(sku)
    except (KeyError, StockError):
        for sku in reserved:
            bins[sku].reserved -= order.lines[sku]
        order.status = "backordered"
        return False
    order.status = "allocated"
    return True


def fulfil(order, bins):
    if order.status != "allocated":
        raise StockError("Only allocated orders can be fulfilled.")
    for sku, amount in order.lines.items():
        ship(bins[sku], amount, order.order_id)
    order.status = "shipped"
    return order.status
