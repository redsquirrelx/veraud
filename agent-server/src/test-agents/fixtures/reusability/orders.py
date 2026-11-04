from policy import PricePolicy


def order_total(amounts):
    return PricePolicy().total(amounts)
