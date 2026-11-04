"""Application-level failures translated by the HTTP adapters."""


class InvalidConfigError(ValueError):
    pass


class InvalidInputError(ValueError):
    pass
