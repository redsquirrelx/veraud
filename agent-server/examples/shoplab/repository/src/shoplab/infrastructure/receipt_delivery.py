"""Legacy outbound receipt gateway."""
from shoplab.presentation.email_templates import render_receipt


class LocalReceiptSender:
    def send(self, order_id: str, total_cents: int) -> str:
        return render_receipt(order_id, total_cents)
