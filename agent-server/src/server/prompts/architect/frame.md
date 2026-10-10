Decide how this repository is organized, and state what reading the code
would have to show for you to be sure.

You are given the structure of a repository: its totals, its entry points,
its external dependencies, its most connected modules and its circular import
groups. You have NOT seen any source code yet. You are also given what the
analyzer concluded: the project kind ({kind}) and its summary ({summary}).

Answer ONLY with a JSON object. Its keys:

- "style": string. Exactly one of layered, hexagonal, mvc, modular_monolith,
  microservices, serverless, plugin, unknown. Use unknown when the listing
  does not settle it.
- "reasoning": string. One or two sentences saying which fact drove it.
- "would_confirm": array of strings. File paths, copied verbatim from the
  listing, whose contents would confirm or refute your style. Between two and
  six paths: prefer entry points and the most connected modules, since
  organization shows where the code holds together. Return an empty array if
  you cannot name any.

Rules for style: separate interface, application and infrastructure directories
with dependencies pointing inward suggest hexagonal or layered; views plus
controllers plus models suggest mvc; independently deployable services suggest
microservices; one deployable with clear module boundaries is a modular
monolith. Absence of evidence is not evidence. If the listing does not decide
it, say unknown rather than guessing.

Repository structure:

{facts}
