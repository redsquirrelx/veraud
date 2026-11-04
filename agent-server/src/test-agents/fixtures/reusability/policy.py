from backend import ProductionClient


class PricePolicy:
    def __init__(self):
        self.client = ProductionClient("postgresql://production/reports")

    def total(self, amounts):
        return self.client.save(sum(amounts))

    def aggregate(self, items):
        return self.client.save(sum(items))
