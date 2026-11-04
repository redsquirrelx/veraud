"""Conservative request admission; reported counts remain distinct from estimates."""

import math

from ...config.token_budget import token_budget_exceeded


class TokenBudgetExceeded(RuntimeError):
    category = "token_budget_exhausted"


def input_ratio(generate):
    samples = [
        record.input_tokens / record.prompt_characters
        for record in getattr(generate, "measurements", ())
        if record.input_tokens is not None and record.prompt_characters
    ]
    return max(0.45, max(samples, default=0) * 1.15)


def account_tokens(generate, budget, objective_id=None):
    accounted = estimated = 0
    for record in getattr(generate, "measurements", ()):
        if objective_id is not None and record.objective_id != objective_id:
            continue
        known = (record.input_tokens or 0) + (record.output_tokens or 0)
        unknown = record.unknown_usage_attempts
        reserve = (
            math.ceil(record.prompt_characters * input_ratio(generate))
            + budget.max_output_tokens_per_call
        )
        estimate = unknown * reserve
        accounted += known + estimate
        estimated += estimate
    return accounted, estimated


def admit_request(generate, budget, prompt, objective_id, previous_attempts=0):
    estimated_input = math.ceil(len(prompt) * input_ratio(generate))
    if estimated_input > budget.max_input_tokens_per_call:
        raise TokenBudgetExceeded(
            "Estimated input exceeds the per-call context budget."
        )
    reserve = estimated_input + budget.max_output_tokens_per_call
    total, _ = account_tokens(generate, budget)
    target, _ = account_tokens(generate, budget, objective_id)
    if token_budget_exceeded(total + reserve * (previous_attempts + 1), budget.max_total_tokens):
        raise TokenBudgetExceeded(
            "Remaining total token budget cannot fund another attempt."
        )
    if token_budget_exceeded(target + reserve * (previous_attempts + 1), budget.max_tokens_per_objective):
        raise TokenBudgetExceeded(
            "Remaining objective token budget cannot fund another attempt."
        )
    return estimated_input
