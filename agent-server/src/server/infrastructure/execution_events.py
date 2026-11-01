"""Task-local, content-free history for every shared execution abstraction.

LangChain's public configure hook instruments graphs and native models without
rewriting agents. Repository tools and imperative phases use the same delivery buffer.
"""

import asyncio
import inspect
from contextlib import contextmanager
from contextvars import ContextVar
from functools import wraps
from time import monotonic
from uuid import uuid4, uuid5

from langchain_core.callbacks import BaseCallbackHandler
from langchain_core.tracers.context import register_configure_hook

from .execution_event_buffer import execution_event_buffer

_session = ContextVar("execution_event_session", default=None)
_identity = ContextVar("execution_event_identity", default=None)
_target = ContextVar("execution_event_target", default=None)
_handler = ContextVar("execution_event_callback", default=None)
_action = ContextVar("execution_event_action", default=None)
_unset = object()
register_configure_hook(_handler, inheritable=True)


def record_event(kind, *, action_id=None, parent_action_id=None, source_id=None, name=None, status=None, metadata=None, identity=None, execution_id=_unset):
    session = _session.get()
    if session is None:
        return None
    target = _target.get() if execution_id is _unset else execution_id
    if target is None:
        return None  # History requires a backend-owned execution; do not retain standalone runs.
    context = dict((_identity.get() or {}) if identity is None else identity)
    return session[1].append(target, str(uuid5(session[0], str(target))), kind=kind,
        action_id=str(action_id or uuid4()), parent_action_id=str(parent_action_id) if parent_action_id else None,
        source_id=source_id, name=name, status=status, metadata=metadata or {}, **context)


@contextmanager
def action_event(category, *, name=None, source_id=None):
    action = str(uuid4())
    parent = _action.get()
    started = monotonic()
    state = {"status": "completed", "metadata": {}}
    record_event(category + ".started", action_id=action, parent_action_id=parent, source_id=source_id, name=name, status="running")
    token = _action.set(action)
    try:
        yield state
    except BaseException as error:
        state["status"] = "cancelled" if isinstance(error, asyncio.CancelledError) else "timeout" if isinstance(error, TimeoutError) else "failed"
        raise
    finally:
        _action.reset(token)
        record_event(category + ".finished", action_id=action, parent_action_id=parent, source_id=source_id, name=name,
            status=state["status"], metadata={**state["metadata"], "seconds": monotonic() - started})


def record_action(category, *, name=None):
    def decorate(operation):
        @wraps(operation)
        async def observed(*args, **kwargs):
            with action_event(category, name=name):
                return await operation(*args, **kwargs)
        return observed
    return decorate


def provider_event(event, values):
    kinds = {"provider_request": "provider.request", "provider_wait": "provider.wait",
        "provider_error": "provider.error", "provider_retry_skipped": "provider.retry_skipped"}
    if event in kinds:
        record_event(kinds[event], action_id=_action.get(), metadata=values)


def bind_execution(execution_id):
    _target.set(execution_id)


def capture_event_recorder(identity):
    """Carry only history routing into external lifecycle/cancellation callbacks."""
    session, target = _session.get(), _target.get()

    def emit(kind, **values):
        token = _session.set(session)
        try:
            return record_event(kind, identity=identity, execution_id=target, **values)
        finally:
            _session.reset(token)
    return emit


class ObservedComponent:
    """One adapter for legacy synchronous/async components, not per-agent rewrites."""
    def __init__(self, component, agent_id):
        object.__setattr__(self, "_component", component)
        object.__setattr__(self, "_agent_id", agent_id)

    def __setattr__(self, name, value):
        setattr(self._component, name, value)

    def __getattr__(self, name):
        operation = getattr(self._component, name)
        if not callable(operation):
            return operation

        @contextmanager
        def invocation():
            parent = _identity.get() or {}
            invocation_id = str(uuid4())
            receipt = {"run_id": parent.get("run_id"), "invocation_id": invocation_id,
                "parent_invocation_id": parent.get("invocation_id"), "agent_id": self._agent_id}
            with invocation_event_context(receipt), action_event("invocation", name=self._agent_id), action_event("tool", name=name):
                yield

        if inspect.iscoroutinefunction(operation):
            @wraps(operation)
            async def async_call(*args, **kwargs):
                with invocation():
                    return await operation(*args, **kwargs)
            return async_call

        @wraps(operation)
        def sync_call(*args, **kwargs):
            with invocation():
                return operation(*args, **kwargs)
        return sync_call


def observe_components(owner, components):
    for attribute, agent_id in components.items():
        component = getattr(owner, attribute)
        if not isinstance(component, ObservedComponent):
            setattr(owner, attribute, ObservedComponent(component, agent_id))


@contextmanager
def invocation_event_context(receipt):
    identity = {key: receipt.get(key) for key in ("run_id", "invocation_id", "parent_invocation_id", "agent_id")}
    token = _identity.set(identity)
    try:
        yield
    finally:
        _identity.reset(token)


class ExecutionHistoryCallback(BaseCallbackHandler):
    """Only identities/timings are retained, never inputs, outputs or exceptions."""
    run_inline = True
    raise_error = True

    def __init__(self):
        self.runs = {}

    def start(self, category, run_id, parent_run_id=None, name=None, metadata=None):
        identity = dict(_identity.get() or {})
        self.runs[str(run_id)] = (category, name, identity, _target.get(), monotonic())
        record_event(category + ".started", action_id=run_id, parent_action_id=parent_run_id,
            name=name, status="running", identity=identity)

    def finish(self, run_id, status, parent_run_id=None, metadata=None):
        category, name, identity, target, started = self.runs.pop(str(run_id), ("node", None, dict(_identity.get() or {}), _target.get(), monotonic()))
        record_event(category + ".finished", action_id=run_id, parent_action_id=parent_run_id,
            name=name, status=status, identity=identity, execution_id=target, metadata={**(metadata or {}), "seconds": monotonic() - started})

    def on_chain_start(self, serialized, inputs, *, run_id, parent_run_id=None, **kwargs):
        self.start("node", run_id, parent_run_id, kwargs.get("name"))

    def on_chain_end(self, outputs, *, run_id, parent_run_id=None, **kwargs):
        self.finish(run_id, "completed", parent_run_id)

    def on_chain_error(self, error, *, run_id, parent_run_id=None, **kwargs):
        self.finish(run_id, "cancelled" if isinstance(error, asyncio.CancelledError) else "timeout" if isinstance(error, TimeoutError) else "failed", parent_run_id)

    def on_chat_model_start(self, serialized, messages, *, run_id, parent_run_id=None, **kwargs):
        self.start("model", run_id, parent_run_id, "chat_model")

    def on_llm_start(self, serialized, prompts, *, run_id, parent_run_id=None, **kwargs):
        self.start("model", run_id, parent_run_id, "text_model")

    def on_llm_end(self, response, *, run_id, parent_run_id=None, **kwargs):
        from .llm.usage import response_usage

        counts = [response_usage(getattr(item, "message", None)) for batch in getattr(response, "generations", ()) for item in batch]
        usage = {key: sum(item[key] for item in counts) for key in ("input_tokens", "output_tokens")
            if counts and all(item[key] is not None for item in counts)}
        self.finish(run_id, "completed", parent_run_id, usage)

    def on_llm_error(self, error, *, run_id, parent_run_id=None, **kwargs):
        self.on_chain_error(error, run_id=run_id, parent_run_id=parent_run_id)

    # RepositoryToolset records the authoritative tool attempt (including early
    # rejection). Also observe non-repository native tools at their own boundary.
    def on_tool_start(self, serialized, input_str, *, run_id, parent_run_id=None, **kwargs):
        self.start("tool", run_id, parent_run_id, serialized.get("name") if serialized else None)

    def on_tool_end(self, output, *, run_id, parent_run_id=None, **kwargs):
        self.finish(run_id, "completed", parent_run_id)

    def on_tool_error(self, error, *, run_id, parent_run_id=None, **kwargs):
        self.on_chain_error(error, run_id=run_id, parent_run_id=parent_run_id)


@contextmanager
def execution_event_scope(execution_id=None, *, buffer=None):
    """Independent audit contexts are inherited by child tasks and tool threads."""
    if _session.get() is not None:
        yield
        return
    tokens = (_session.set((uuid4(), buffer or execution_event_buffer())),
        _target.set(execution_id), _identity.set({}), _handler.set(ExecutionHistoryCallback()), _action.set(None))
    action = str(uuid4())
    try:
        record_event("execution.started", action_id=action, status="running", execution_id=execution_id)
        yield
    except BaseException as error:
        record_event("execution.finished", action_id=action, execution_id=execution_id,
            status="cancelled" if isinstance(error, asyncio.CancelledError) else "timeout" if isinstance(error, TimeoutError) else "failed")
        raise
    else:
        record_event("execution.finished", action_id=action, status="completed", execution_id=execution_id)
    finally:
        _handler.reset(tokens[3])
        _action.reset(tokens[4])
        _identity.reset(tokens[2])
        _target.reset(tokens[1])
        _session.reset(tokens[0])


def record_execution(operation):
    """Composition-boundary decorator, not a dependency on concrete agents."""
    signature = inspect.signature(operation)

    @wraps(operation)
    async def observed(*args, **kwargs):
        arguments = signature.bind(*args, **kwargs).arguments
        identifiers = arguments.get("execution_ids") or {}
        target = arguments.get("execution_id") or next(iter(identifiers.values()), None)
        with execution_event_scope(target):
            return await operation(*args, **kwargs)
    return observed
