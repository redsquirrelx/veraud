"""Fixture only: a flag couples formatting and mutation across calls."""


class Processor:
    def __init__(self):
        self.mode = False
        self.total = 0

    def process(self, value):
        if self.mode:
            self.mode = False
            return str(self.total)
        self.total += value
        self.mode = True
        return self.total
