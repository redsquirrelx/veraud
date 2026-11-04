from typing import Annotated

from fastapi import Depends, Request

from ..blackboard.interface import Blackboard


def get_blackboard(request: Request) -> Blackboard:
    return request.app.state.blackboard


BlackboardDep = Annotated[Blackboard, Depends(get_blackboard)]
