class ProductionClient:
    def __init__(self, endpoint):
        self.endpoint = endpoint

    def save(self, record):
        return {"endpoint": self.endpoint, "record": record}
