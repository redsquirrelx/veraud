VIOLATING = {
    "src/urbanmesh/application/inventory/allocator.py": (
        '"""Reserve depot stock."""\n'
        "from urbanmesh.infrastructure.storage.memory import MemoryInventoryCatalog\n\n"
        "class StockAllocator:\n"
        "    def __init__(self, inventory: MemoryInventoryCatalog): self.inventory = inventory\n"
    ),
    "src/urbanmesh/infrastructure/storage/memory.py": (
        '"""In-memory adapters."""\n'
        "class MemoryInventoryCatalog:\n"
        "    pass\n"
    ),
    "src/urbanmesh/domain/recommendations.py": (
        '"""Suggested parts."""\n'
        "from urbanmesh.infrastructure.gateways.analytics import AnalyticsClient\n\n"
        "def suggested_parts(asset_type: str) -> list[str]:\n"
        "    client = AnalyticsClient()\n"
        "    return client.top_parts(asset_type)\n"
    ),
    "src/urbanmesh/infrastructure/gateways/analytics.py": (
        '"""Analytics adapter."""\n'
        "class AnalyticsClient:\n"
        "    def top_parts(self, asset_type: str) -> list[str]:\n"
        '        return ["FILTER-01"]\n'
    ),
    "src/urbanmesh/modules/billing/service.py": (
        '"""Legacy invoice summary."""\n'
        "from urbanmesh.modules.inventory import _store\n\n"
        "def receipt_stock_snapshot(order) -> int:\n"
        "    return _store.STOCK.get(order.sku, 0)\n"
    ),
    "src/urbanmesh/modules/inventory/_store.py": '"""Private stock."""\nSTOCK = {}\n',
    "src/urbanmesh/modules/inventory/api.py": (
        '"""Public stock API."""\n'
        "def available_stock(sku: str) -> int:\n"
        "    return 0\n"
    ),
    "src/urbanmesh/infrastructure/gateways/email.py": (
        '"""Email gateway."""\n'
        "from urbanmesh.presentation.email_templates import render_notice\n\n"
        "class EmailGateway:\n"
        "    def send(self, recipient: str, text: str) -> None:\n"
        "        render_notice(text)\n"
    ),
    "src/urbanmesh/presentation/email_templates.py": (
        '"""HTML-like mail rendering."""\n'
        "def render_notice(text: str) -> str:\n"
        '    return f"<p>{text}</p>"\n'
    ),
    "src/urbanmesh/domain/models.py": (
        '"""Value objects."""\n'
        "from dataclasses import dataclass\n"
        "from datetime import datetime\n\n"
        "@dataclass(frozen=True)\n"
        "class SensorReading:\n"
        "    sensor_id: str\n"
        "    value: float\n"
        "    unit: str\n"
        "    captured_at: datetime\n"
    ),
    "src/urbanmesh/domain/policies/quality.py": (
        '"""Quality policies."""\n'
        "from urbanmesh.domain.models import SensorReading\n\n"
        "class ThresholdQualityRule:\n"
        "    def assess(self, reading: SensorReading) -> str:\n"
        '        return "accepted"\n\n'
        "class AlwaysClearQualityRule:\n"
        "    def assess(self, reading: SensorReading) -> str:\n"
        '        return "accepted"\n\n'
        "class VendorQualityRule:\n"
        "    def assess(self, reading: SensorReading) -> str:\n"
        '        return "PASS" if reading.value < 50 else "FAIL"\n'
    ),
}

FIXED = {
    "src/urbanmesh/application/inventory/allocator.py": (
        '"""Reserve depot stock."""\n'
        "from urbanmesh.domain.errors import NotFound, Conflict\n\n"
        "class StockAllocator:\n"
        "    def __init__(self, inventory): self.inventory = inventory\n"
    ),
    "src/urbanmesh/domain/recommendations.py": (
        '"""Suggested parts."""\n\n'
        "def suggested_parts(asset_type: str) -> list[str]:\n"
        '    return ["FILTER-01"]\n'
    ),
    "src/urbanmesh/modules/billing/service.py": (
        '"""Legacy invoice summary."""\n'
        "from urbanmesh.modules.inventory import api\n\n"
        "def receipt_stock_snapshot(order) -> int:\n"
        "    return api.available_stock(order.sku)\n"
    ),
    "src/urbanmesh/infrastructure/gateways/email.py": (
        '"""Email gateway."""\n\n'
        "class EmailGateway:\n"
        "    def send(self, recipient: str, text: str) -> None:\n"
        '        payload = f"<p>{text}</p>"\n'
    ),
    "src/urbanmesh/domain/policies/quality.py": (
        '"""Quality policies."""\n'
        "from urbanmesh.domain.models import SensorReading\n\n"
        "class ThresholdQualityRule:\n"
        "    def assess(self, reading: SensorReading) -> str:\n"
        '        return "accepted"\n\n'
        "class AlwaysClearQualityRule:\n"
        "    def assess(self, reading: SensorReading) -> str:\n"
        '        return "accepted"\n\n'
        "class VendorQualityRule:\n"
        "    def assess(self, reading: SensorReading) -> str:\n"
        '        return "accepted" if reading.value < 50 else "rejected"\n'
    ),
}


