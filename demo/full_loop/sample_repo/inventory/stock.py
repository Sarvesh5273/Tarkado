from dataclasses import dataclass, field


class StockError(ValueError):
    pass


@dataclass
class Bin:
    sku: str
    quantity: int = 0
    reserved: int = 0
    history: list = field(default_factory=list)

    def available(self):
        return self.quantity - self.reserved


def receive(bin_, amount, reference):
    if amount <= 0:
        raise StockError("Received amount must be positive.")
    bin_.quantity += amount
    bin_.history.append(("receive", amount, reference))
    return bin_.quantity


def reserve(bin_, amount, order_id):
    if amount <= 0:
        raise StockError("Reserved amount must be positive.")
    if amount > bin_.available():
        raise StockError("Not enough available stock to reserve.")
    bin_.reserved += amount
    bin_.history.append(("reserve", amount, order_id))
    return bin_.available()


def release(bin_, amount, order_id):
    if amount <= 0 or amount > bin_.reserved:
        raise StockError("Released amount must be positive and already reserved.")
    bin_.reserved -= amount
    bin_.history.append(("release", amount, order_id))
    return bin_.available()


def ship(bin_, amount, order_id):
    if amount <= 0 or amount > bin_.reserved:
        raise StockError("Only reserved stock can be shipped.")
    bin_.reserved -= amount
    bin_.quantity -= amount
    bin_.history.append(("ship", amount, order_id))
    return bin_.quantity
