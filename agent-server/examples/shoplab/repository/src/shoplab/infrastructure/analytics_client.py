"""Local analytics adapter used by a legacy recommendation feature."""
from dataclasses import dataclass


@dataclass(frozen=True)
class RecommendationEvent:
    sku: str
    reason: str


class AnalyticsClient:
    def record_recommendation(self, sku: str) -> RecommendationEvent:
        return RecommendationEvent(sku=sku, reason="co-viewed")
