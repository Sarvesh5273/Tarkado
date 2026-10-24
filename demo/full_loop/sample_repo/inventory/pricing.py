from decimal import ROUND_HALF_UP, Decimal

CENT = Decimal("0.01")


def unit_price(list_price, discount_percent=0):
    if not 0 <= discount_percent <= 100:
        raise ValueError("Discount must be between 0 and 100 percent.")
    price = Decimal(str(list_price)) * (Decimal(100) - Decimal(str(discount_percent))) / Decimal(100)
    return price.quantize(CENT, rounding=ROUND_HALF_UP)


def bulk_discount(quantity, tiers):
    best = 0
    for minimum, percent in sorted(tiers):
        if quantity >= minimum:
            best = percent
    return best


def line_total(list_price, quantity, tiers=()):
    if quantity < 0:
        raise ValueError("Quantity cannot be negative.")
    return (unit_price(list_price, bulk_discount(quantity, tiers)) * quantity).quantize(CENT, rounding=ROUND_HALF_UP)


def with_tax(amount, rate_percent):
    amount = Decimal(str(amount))
    return (amount + amount * Decimal(str(rate_percent)) / Decimal(100)).quantize(CENT, rounding=ROUND_HALF_UP)
