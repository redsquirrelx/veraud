from backend import ProductionClient


class FlexibleService:
    def __init__(self, client=None):
        self.client = client if client is not None else ProductionClient("postgresql://production/reports")

    def publish(self, record):
        return self.client.save({"schema": "v1", "payload": record})
