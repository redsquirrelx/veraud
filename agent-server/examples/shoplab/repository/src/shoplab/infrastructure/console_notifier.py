from shoplab.domain.models import Order
from shoplab.domain.ports import Notifier


class ConsoleNotifier(Notifier):
    def send(self, order: Order, message: str) -> None:
        print(f"[{order.order_id}] {message}")
