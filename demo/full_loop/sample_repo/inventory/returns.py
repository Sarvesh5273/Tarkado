from .stock import receive

REASONS = ("damaged", "wrong_item", "unwanted")


def accept_return(bin_, amount, reason, order_id):
    if reason not in REASONS:
        raise ValueError("Unknown return reason.")
    if reason == "damaged":
        return 0
    return receive(bin_, amount, "return:" + order_id)


def refund_amount(paid, reason, restocking_percent=15):
    if reason == "wrong_item":
        return paid
    if reason == "damaged":
        return paid
    return round(paid * (100 - restocking_percent) / 100, 2)
