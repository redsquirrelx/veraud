Decide what this repository TRIES to be architecturally, and why it does
not fully get there.

You are given the structure of a repository: its totals, its entry points,
its external dependencies, its most connected modules and its circular import
groups. You have NOT seen any source code yet. You are also given what the
analyzer concluded: the project kind ({kind}) and its summary ({summary}).

Answer ONLY with a JSON object. Its keys:

- "style": string. What the organization most looks like today. Exactly one
  of layered, hexagonal, mvc, modular_monolith, microservices, serverless,
  plugin, unknown. Use unknown when the listing does not settle it.
- "intended_style": string. What the repository seems to TRY to be: the
  architecture its layout points at even where the code falls short. Same
  vocabulary as style. Often equals style; when they differ, that gap is the
  interesting finding. Use unknown when the evidence does not support any
  intention.
- "reasoning": string. One or two sentences saying which fact drove it.
- "would_confirm": array of strings. File paths, copied verbatim from the
  listing, whose contents would confirm or refute your reading. Between two
  and six paths: prefer entry points and the most connected modules, since
  organization shows where the code holds together. Return an empty array if
  you cannot name any.
- "deviations": array of objects. Each has "observation" (string: one concrete
  structural reason the code falls short of the intended style) and "evidence"
  (array of strings: paths from the listing proving it, possibly empty when
  the deviation is an absence, such as a missing boundary). Empty array when
  style already matches intention or nothing supports a deviation.

Rules for style: decide against the style definitions below. Quote which
criteria hold and which fail; a deviation is exactly a failed criterion of
the intended style. Typical deviations: handlers importing infrastructure
adapters directly (skipped port), business logic inside controllers or
scripts, circular imports between supposed layers, infrastructure names
inside the domain. Absence of evidence is not evidence: never invent an
intention. An "unknown" intention with no deviations beats a guessed one,
and a deviation without evidence is just a suspicion — leave it out.

Style definitions:

{styles}

Repository structure:

{facts}
