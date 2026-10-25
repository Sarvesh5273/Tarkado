from .stock import Bin


def low_stock(bins, threshold):
    return sorted(bin_.sku for bin_ in bins if bin_.available() < threshold)


def stock_value(bins, prices):
    total = 0
    for bin_ in bins:
        total += bin_.quantity * prices.get(bin_.sku, 0)
    return total


def movement_summary(bin_):
    summary = {}
    for kind, amount, _reference in bin_.history:
        summary[kind] = summary.get(kind, 0) + amount
    return summary


def snapshot(bins):
    return [Bin(bin_.sku, bin_.quantity, bin_.reserved) for bin_ in bins]
