"""Documentary graph shared by the production agent and development runner."""

import asyncio
import inspect
from functools import partial

from langgraph.graph import END, START, StateGraph

from server.runtimes.investigation.structured import safe_diagnostic

from .discovery import discover_documents
from .extraction import extract_knowledge
from .finalization import validate_and_finalize
from .planning import plan_retrieval
from .retrieval import retrieve_documents
from .routing import route_after_extraction, route_after_plan
from .schemas import RetrievalPlan
from .state import ArchitectureContextState


async def run_node(state, *, name, node, schema=None, **kwargs):
    """Retain prior evidence when a later node fails; never fabricate coverage."""
    try:
        if inspect.iscoroutinefunction(node):
            return await node(state, **kwargs)
        return await asyncio.to_thread(node, state, **kwargs)
    except Exception as error:
        if name == "validate_and_finalize":
            raise
        diagnostic = safe_diagnostic(error, schema)
        update = {"context_stop_reason": f"{name}_failed", "execution_error": diagnostic}
        if name == "plan_retrieval":
            update["retrieval_plan"] = RetrievalPlan(tasks=[])
        elif name == "discover_documents":
            update.update(documents=[], document_discovery_status="error",
                          document_discovery_error=diagnostic)
        return update


def build_workflow(service, managed, retrieval_budget, *, node_runner=run_node,
                   discovery_only=False, trace=None, nodes=None, discovery_router=None):
    graph = StateGraph(ArchitectureContextState)

    def add(name, node, **kwargs):
        node = (nodes or {}).get(name, node)
        graph.add_node(name, partial(node_runner, name=name, node=node, **kwargs))

    add("validate_and_finalize", validate_and_finalize)
    graph.add_edge("validate_and_finalize", END)
    add("discover_documents", discover_documents, indexing_service=service)
    graph.add_edge(START, "discover_documents")
    if discovery_only:
        graph.add_edge("discover_documents", "validate_and_finalize")
        return graph.compile()

    add("plan_retrieval", plan_retrieval, model=managed, schema=RetrievalPlan)
    graph.add_conditional_edges(
        "discover_documents",
        discovery_router or (lambda state: "plan_retrieval" if state["document_discovery_status"] == "ready"
                             else "validate_and_finalize"),
    )
    add("retrieve_documents", retrieve_documents, indexing_service=service,
        budget=retrieval_budget, timing=managed.timing if managed else None, trace=trace)
    add("extract_knowledge", extract_knowledge, model=managed)
    graph.add_conditional_edges("plan_retrieval", partial(route_after_plan, trace=trace),
                               {END: "validate_and_finalize", "retrieve_documents": "retrieve_documents"})
    graph.add_conditional_edges(
        "retrieve_documents",
        lambda state: "validate_and_finalize" if state.get("context_stop_reason") else "extract_knowledge",
    )
    graph.add_conditional_edges("extract_knowledge", partial(route_after_extraction, trace=trace),
                               {END: "validate_and_finalize", "plan_retrieval": "plan_retrieval"})
    return graph.compile()
