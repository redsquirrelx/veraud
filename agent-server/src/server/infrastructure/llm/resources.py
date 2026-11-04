"""Best-effort cleanup for provider-owned SDK clients."""

async def close_model_clients(model):
    """Release runner-owned clients on success, timeout, error, or cancellation."""
    failures = []
    client = getattr(model, "client", None)
    llm = getattr(model, "llm", None)
    operations = []
    if client is not None and hasattr(client, "aio"):
        operations.extend(((client.aio, "aclose"), (client, "close")))
    if llm is not None:
        operations.extend(
            (
                (getattr(llm, "root_async_client", None), "close"),
                (getattr(llm, "root_client", None), "close"),
                (getattr(llm, "async_client", None), "aclose"),
                (getattr(llm, "client", None), "close"),
            )
        )
    closed = set()
    for resource, name in operations:
        if resource is None or not hasattr(resource, name):
            continue
        key = (id(resource), name)
        if key in closed:
            continue
        closed.add(key)
        try:
            value = getattr(resource, name)()
            if hasattr(value, "__await__"):
                await value
        except Exception as error:  # noqa: BLE001 - attempt every cleanup without hiding the run result
            failures.append(type(error).__name__)
    return tuple(failures)
