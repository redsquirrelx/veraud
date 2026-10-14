class ProductionClient:
    def __init__(self, endpoint):
        self.endpoint = endpoint

    def save(self, amount):
        return {"endpoint": self.endpoint, "amount": amount}
