"""Shared context fitting that prioritizes code over navigation metadata."""

import json
from copy import deepcopy


class WorkingContext:
    def __init__(self, representation, responses, *, protected_file_ids=()):
        self.representation = deepcopy(representation)
        self.responses = list(responses)
        self.omitted_results = 0
        self.protected_file_ids = set(protected_file_ids)

    def reduce(self):
        """Shrink metadata first; never remove the last two distinct source files."""
        view = self.representation
        omissions = view.setdefault("prompt_metadata_omissions", {})
        for key, floor in (
            ("relationship_signals", 0),
            ("entrypoints", 0),
            ("technologies", 0),
            ("infrastructure_signals", 0),
            ("configuration_files", 0),
            ("candidate_files", 2),
            ("projects", 1),
        ):
            if len(view.get(key, [])) > floor:
                view[key] = list(view[key])[:-1]
                omissions[key] = omissions.get(key, 0) + 1
                return True
        for index, item in enumerate(view.get("candidate_files", [])):
            if item.get("symbols"):
                item["symbols"] = list(item["symbols"])[:-1]
                omissions["candidate_symbols"] = (
                    omissions.get("candidate_symbols", 0) + 1
                )
                return True
        if view.get("orientation_guidance") is not None:
            view["orientation_guidance"] = None
            omissions["orientation_guidance"] = 1
            return True
        if view.get("limitations"):
            view["limitations"] = list(view["limitations"])[:-1]
            omissions["representation_limitations"] = (
                omissions.get("representation_limitations", 0) + 1
            )
            return True
        # Once code has been delivered, its ledger provides file navigation.
        # The initial candidate/project floors must not block admission of code.
        if any(
            (json.loads(item["content"]).get("data") or {}).get("content") is not None
            for item in self.responses
        ):
            for key in ("candidate_files", "projects"):
                if view.get(key):
                    view[key] = list(view[key])[:-1]
                    omissions[key] = omissions.get(key, 0) + 1
                    return True
        protected = set()
        protected_files = set()
        recent_files = set()
        for index in range(len(self.responses) - 1, -1, -1):
            response = json.loads(self.responses[index]["content"])
            data = response.get("data") or {}
            if (
                data.get("content") is not None
                and data.get("file_id") not in protected_files
            ):
                protected_files.add(data.get("file_id"))
                if (
                    len(recent_files) < 2
                    or data.get("file_id") in self.protected_file_ids
                ):
                    protected.add(index)
                if len(recent_files) < 2:
                    recent_files.add(data.get("file_id"))
        removable = next(
            (index for index in range(len(self.responses)) if index not in protected),
            None,
        )
        if removable is None:
            return False
        self.responses.pop(removable)
        self.omitted_results += 1
        return True


def source_arguments(tools, name, arguments, max_characters=1400):
    """Bound actual retrieval ranges, not the text of already registered evidence."""
    if name != "get_source_excerpt":
        return arguments, None
    source = next(
        (
            item
            for item in tools.accessible_snapshot.files
            if item.path == arguments.get("path")
        ),
        None,
    )
    start = arguments.get("start_line", 1)
    end = arguments.get("end_line")
    if (
        source is None
        or source.content is None
        or type(start) is not int
        or start < 1
        or (end is not None and type(end) is not int)
    ):
        return arguments, None
    lines = source.content.splitlines()
    requested_end = end if end is not None else len(lines)
    if requested_end < start or requested_end > len(lines) or start > len(lines):
        return arguments, None
    stop, size = start - 1, 0
    while stop < requested_end:
        added = len(lines[stop]) + (1 if stop >= start else 0)
        if stop >= start and size + added > max_characters:
            break
        size += added
        stop += 1
    return arguments | {"end_line": stop}, requested_end


def source_view(tools, response, requested_end=None):
    view = tools.model_view(response)
    if response.status == "ok" and (view.get("data") or {}).get("content") is not None:
        view["data"].pop("content_hash", None)
        if requested_end is not None:
            view["data"]["requested_end_line"] = requested_end
            view["data"]["truncated"] = view["data"]["end_line"] < requested_end
        view["evidence"] = [
            {
                key: value
                for key, value in record.items()
                if key in {"id", "kind", "file_id"}
            }
            for record in view["evidence"]
        ]
    return view


def rejection_details(generate, budget, prompt, objective_id):
    from math import ceil

    from .token_budget import account_tokens, input_ratio

    accounted, _ = account_tokens(generate, budget)
    target, _ = account_tokens(generate, budget, objective_id)
    return {
        "objective": objective_id,
        "prompt_characters": len(prompt),
        "estimated_input_tokens": ceil(len(prompt) * input_ratio(generate)),
        "max_input_tokens": budget.max_input_tokens_per_call,
        "remaining_total_tokens": max(0, budget.max_total_tokens - accounted),
        "remaining_objective_tokens": max(0, budget.max_tokens_per_objective - target),
        "reserved_output_tokens": budget.max_output_tokens_per_call,
        "context_characters": {
            part.category: part.characters for part in prompt.measurement.context
        },
    }
