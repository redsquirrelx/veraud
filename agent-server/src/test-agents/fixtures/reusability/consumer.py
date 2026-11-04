from policy import PricePolicy


def publish_report(amounts):
    return PricePolicy().total(amounts)
