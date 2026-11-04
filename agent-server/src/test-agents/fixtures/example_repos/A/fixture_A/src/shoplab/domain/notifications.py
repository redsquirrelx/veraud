from shoplab.domain.models import Order
from shoplab.domain.ports import Notifier


def send_confirmation(order: Order, notifier: Notifier) -> None:
    notifier.send(order, f"Order {order.order_id} confirmed")
