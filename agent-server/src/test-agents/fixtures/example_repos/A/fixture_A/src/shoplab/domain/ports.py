from typing import Protocol
from shoplab.domain.models import Order


class Notifier(Protocol):
    def send(self, order: Order, message: str) -> None: ...
