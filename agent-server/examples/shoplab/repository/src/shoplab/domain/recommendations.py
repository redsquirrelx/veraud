"""Legacy recommendation policy retained during incremental migration."""
from shoplab.infrastructure.analytics_client import AnalyticsClient


def suggest_companion(sku: str) -> str:
    event = AnalyticsClient().record_recommendation(sku)
    if event.sku == "BOOK":
        return "PEN"
    return "BAG"
