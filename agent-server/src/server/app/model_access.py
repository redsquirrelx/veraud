"""Safe classification of access-probe failures, without provider payloads."""

import httpx

from ..infrastructure.llm.diagnostics import causes, provider_status
from ..infrastructure.llm.quota import RequestTokenQuotaExceeded


def access_failure(error):
    if any(isinstance(cause, RequestTokenQuotaExceeded) for cause in causes(error)):
        return 429, "Verification request exceeds the configured global provider token quota"
    status = provider_status(error)
    if status in (408, 504) or any(isinstance(cause, (TimeoutError, httpx.TimeoutException))
            or type(cause).__name__ == "APITimeoutError" for cause in causes(error)):
        return 504, "Model access verification timed out; access was not confirmed"
    if status in (401, 403):
        return 403, "Provider rejected the credential or its permissions"
    if status == 404:
        return 404, "Model not found or unavailable for this credential"
    if status == 429:
        return 429, "Provider rate limit or quota exceeded; access was not confirmed"
    if status is not None and 500 <= status <= 599:
        return 503, "Provider temporarily unavailable; access was not confirmed"
    if status in (400, 422):
        return 422, "Provider rejected the verification request; check model and credential configuration"
    return 502, "Model access verification could not be completed; access was not confirmed"
