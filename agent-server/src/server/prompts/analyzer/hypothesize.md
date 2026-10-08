Decide what kind of project this is, and state what reading the code would have
to show for you to be sure.

You are given the structure of a repository: its totals, its entry points, its
external dependencies, its most connected modules and its circular import
groups. You have NOT seen any source code yet.

Answer ONLY with a JSON object. Its keys:

- "kind": string. Exactly one of cli, library, web_service, desktop_app,
  data_pipeline, script, unknown. Use unknown when the listing does not settle
  it.
- "reasoning": string. One or two sentences saying which fact drove it.
- "would_confirm": array of strings. File paths, copied verbatim from the
  listing, whose contents would confirm or refute your kind. Between two and
  six paths. Return an empty array if you cannot name any.

Rules for kind: a project that declares console scripts is a cli; one whose
package re-exports a public API and is imported by others is a library; one
that serves HTTP is a web_service. Absence of evidence is not evidence. If the
listing does not decide it, say unknown rather than guessing.

Repository structure:

{facts}