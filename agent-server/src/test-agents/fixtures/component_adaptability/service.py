from backend import ProductionClient


class ReportService:
    def __init__(self):
        self.client = ProductionClient("postgresql://production/reports")

    def publish(self, record):
        return self.client.save({"schema": "v1", "payload": record})
