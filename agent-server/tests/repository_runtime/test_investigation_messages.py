"""Removing empty AI turns must preserve native tool-call/response adjacency."""

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from server.runtimes.investigation.messages import provider_history


def test_empty_turn_filter_preserves_calls_responses_and_original_history():
    call = AIMessage(content="", tool_calls=[{"id": "read-1", "name": "get_source_excerpt", "args": {"path": "main.py"}}])
    response = ToolMessage(content="source", tool_call_id="read-1")
    history = [HumanMessage(content="inspect"), AIMessage(content=""), call, response,
        AIMessage(content=[{"type": "text", "text": "  "}]), AIMessage(content="Done")]
    filtered = provider_history(history)
    assert filtered == [history[0], call, response, history[-1]]
    assert len(history) == 6 and filtered[1] is call and filtered[2] is response
