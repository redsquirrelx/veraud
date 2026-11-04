"""Public error text is host-controlled, not a filtered provider response."""

import json
import re
from datetime import datetime

MESSAGES = {
    "execution_cancelled": "La ejecución fue cancelada.",
    "execution_failed": "The execution failed. Additional internal details are not public.",
    "execution_timeout": "The execution exceeded its allowed time.",
    "child_execution_error": "An agent could not complete its execution.",
    "result_contract_invalid": "The received response did not satisfy the expected contract.",
    "backend_dispatch_failed": "The backend could not dispatch or finalize the execution.",
    "audit_outcome_unconfirmed": "Communication was interrupted; the audit outcome is unconfirmed, not a confirmed agent failure.",
}
HIDDEN_ERROR = "Error details withheld because their safety could not be verified."
CONFIGURATION_ERRORS = {name: f"{name}: The configured hierarchy budget is insufficient." for name in (
    "coordinator_call_budget_too_small", "coordinator_tool_budget_too_small", "manager_call_budget_too_small", "manager_tool_budget_too_small")}
EXCEPTIONS = {"Error", "CancelledError", "ValueError", "RuntimeError", "TimeoutError", "ValidationError", "TypeError",
    "AgentTransportError", "AgentInvocationError", "AuditRunUnavailableError", "InvalidConfigError"}


def public_error_code(value):
    return value if isinstance(value, str) and value in MESSAGES else "execution_failed"


def public_error_text(value):
    if isinstance(value, str) and value.strip() in {"CancelledError", "asyncio.CancelledError", "concurrent.futures.CancelledError"}:
        return MESSAGES["execution_cancelled"]
    if value is None or isinstance(value, str) and not value.strip():
        return None
    if not isinstance(value, str):
        return HIDDEN_ERROR
    code = value.partition(":")[0] if isinstance(value, str) else ""
    if code in CONFIGURATION_ERRORS:
        return CONFIGURATION_ERRORS[code]
    return value if value in {*MESSAGES.values(), HIDDEN_ERROR} else HIDDEN_ERROR


def public_identifier(value):
    return value if isinstance(value, str) and re.fullmatch(r"[a-zA-Z0-9_.:-]{1,128}", value) and not re.match(
        r"(?:sk-|AIza|gh[pousr]_|github_pat_|AKIA|eyJ)", value) else None


def public_error_fields(value):
    if isinstance(value, list):
        return [public_error_fields(item) for item in value]
    if not isinstance(value, dict):
        return value
    result = {}
    for key, item in value.items():
        if key == "error" and isinstance(item, str):
            result[key] = public_error_text(item)
        elif key == "error" and isinstance(item, (dict, list)):
            result[key] = {"message": HIDDEN_ERROR}
        elif key == "result" and isinstance(item, str):
            result[key] = public_error_result(item)
        elif key == "execution_issues" and isinstance(item, list):
            result[key] = [{**{name: public_identifier(issue[name]) or "unknown"
                for name in ("id", "agent_id", "invocation_id", "stage", "category", "status") if isinstance(issue.get(name), str)},
                "termination_reason": public_error_code(issue.get("termination_reason")),
                "source_record_ids": [public_identifier(ref) for ref in issue.get("source_record_ids", []) if public_identifier(ref)]
                if isinstance(issue.get("source_record_ids"), list) else [],
                "explanation": MESSAGES[public_error_code(issue.get("termination_reason"))],
                **({"message": MESSAGES[public_error_code(issue.get("termination_reason"))]} if "message" in issue else {}),
                "diagnostics": [], "incidents": []} for issue in item if isinstance(issue, dict)]
        elif key in {"errorDetail", "error_detail"} and isinstance(item, dict):
            code = public_error_code(item.get("code"))
            date = item.get("occurredAt", item.get("occurred_at"))
            try:
                date = datetime.fromisoformat(date).isoformat() if isinstance(date, str) else None
            except ValueError:
                date = None
            result[key] = {"agentId": public_identifier(item.get("agentId", item.get("agent_id"))),
                "invocationId": public_identifier(item.get("invocationId", item.get("invocation_id"))),
                "occurredAt": date, "code": code,
                "exceptionType": item.get("exceptionType", item.get("exception_type"))
                if isinstance(item.get("exceptionType", item.get("exception_type")), str)
                and item.get("exceptionType", item.get("exception_type")) in EXCEPTIONS else None,
                "message": MESSAGES[code]}
        elif key == "failure" and isinstance(item, dict):
            code = public_error_code(item.get("code"))
            result[key] = {"code": code, "summary": MESSAGES[code], "diagnostics": [],
                "stage": item.get("stage") if item.get("stage") in ("execute", "invoke_child", "validate_result", "publish_result", "reserve_invocation") else "execute",
                "resources": [{"resource": r.get("resource") if r.get("resource") in ("tokens", "calls", "tools", "time", "seconds") else "resource",
                    "available": r.get("available") if isinstance(r.get("available"), (float, int)) else None,
                    "required": r.get("required") if isinstance(r.get("required"), (float, int)) else None}
                    for r in (item.get("resources") if isinstance(item.get("resources"), list) else []) if isinstance(r, dict)],
                "exception_type": item.get("exception_type") if isinstance(item.get("exception_type"), str)
                and item.get("exception_type") in EXCEPTIONS else None}
        else:
            result[key] = public_error_fields(item)
    return result


def public_error_result(value):
    if value is None:
        return None
    try:
        parsed = json.loads(value)
    except (ValueError, TypeError):
        return value
    except RecursionError:
        return None
    try:
        return json.dumps(public_error_fields(parsed), ensure_ascii=False)
    except (ValueError, TypeError, RecursionError):
        return None
