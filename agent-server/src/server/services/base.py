from abc import ABC, abstractmethod

from pydantic import BaseModel


class BaseRepresentationService[RepresentationInput: BaseModel, RepresentationOutput: BaseModel](ABC):
    """Base class for representation services.

    A representation service takes an analysis result and builds one concrete
    representation of it: a text report, a markdown summary, a diagram, etc.
    Each subclass owns exactly one representation_type.

    Lifecycle: built once then run once per input. Services must be stateless.
    """

    representation_type: str
    output_schema: type[RepresentationOutput]

    @abstractmethod
    async def create(self, input_data: RepresentationInput) -> RepresentationOutput:
        """Build the representation and return it."""
        raise NotImplementedError