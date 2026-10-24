from policy import PricePolicy


def report_total(items):
    return PricePolicy().aggregate(items)
