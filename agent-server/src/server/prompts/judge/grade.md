Grade whether the claim is supported by the source you read.

Subject:

{subject}

Claim:

{claim}

Source excerpts (the only evidence you may use):

{excerpts}

Answer ONLY with a JSON object. Its keys:

- "verdict": string, exactly one of supported, contradicted, unverifiable.
  supported means the excerpts show the claim. contradicted means the
  excerpts show otherwise. unverifiable means the excerpts say nothing about
  it either way.
- "reason": string, one sentence naming what in the excerpts decided it.
- "evidence": array of strings copied from the excerpt headers above
  (path or path:start-end) that back the verdict. A supported or
  contradicted verdict with no checkable evidence is thrown out, so never
  leave it empty unless the verdict is unverifiable.
