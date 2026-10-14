"""Role-local usage accounting over a caller-owned provider measurement ledger."""

from .schemas import BudgetUsage
from .telemetry import execution_telemetry
from .token_budget import account_tokens


def execution_results(tools, generate, calls, issues, objective=None):
    records = tuple(
        record
        for record in generate.measurements
        if objective is None or record.objective_id == objective
    )
    unknown = sum(record.unknown_usage_attempts for record in records)

    def total(field):
        return (
            sum(getattr(record, field) for record in records)
            if records
            and not unknown
            and all(getattr(record, field) is not None for record in records)
            else None
        )

    accounted, estimated = account_tokens(
        generate, tools.context.input.budget, objective
    )
    usage = BudgetUsage(
        model_calls=calls,
        tool_calls=tools.budget_usage.tool_calls,
        retrieved_characters=tools.budget_usage.retrieved_characters,
        elapsed_seconds=tools.context.elapsed_seconds,
        input_tokens=total("input_tokens"),
        output_tokens=total("output_tokens"),
        reported_input_tokens=sum(record.input_tokens or 0 for record in records),
        reported_output_tokens=sum(record.output_tokens or 0 for record in records),
        unknown_usage_attempts=unknown,
        provider_attempts=sum(record.attempts for record in records),
        provider_retries=sum(max(0, record.attempts - 1) for record in records),
        provider_wait_seconds=sum(record.wait_seconds for record in records),
        accounted_tokens=accounted,
        estimated_tokens=estimated,
        token_budget_exhausted=any(
            item.category == "token_budget_exhausted" for item in issues
        ),
    )
    return usage, execution_telemetry(records, tools.tool_measurements)
