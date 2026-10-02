from abc import ABC, abstractmethod

from ...config.schemas import ModelCredentials, ModelSettings


class Model(ABC):
    def __init__(self, settings: ModelSettings, credentials: ModelCredentials):
        self.settings = settings
        self.credentials = credentials

    @abstractmethod
    async def generate(message: str) -> any:
        raise NotImplementedError