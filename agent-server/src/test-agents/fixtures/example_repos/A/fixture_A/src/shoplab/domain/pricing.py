from shoplab.domain.models import Order


def order_total(order: Order) -> int:
    return order.total
