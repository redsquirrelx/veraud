Write the description of this repository. The architecture specialist runs
next and judges whether it is well built, so they need an accurate picture of
what it is and how it is put together before they start.

Answer ONLY with a JSON object. Its keys:

- "kind": string. Exactly one of cli, library, web_service, desktop_app,
  data_pipeline, script, unknown. Use unknown when the evidence does not settle
  it.
- "summary": string. Two or three plain sentences. Say what the project is FOR,
  not what files it has. Use the source you read to make it concrete.
- "primary_language": string. The dominant language, for example python.
- "entrypoints": array of strings. Repository paths where execution starts. Use
  the package path, such as src/mypkg, when the project exposes a library API,
  and the file path when there is a main or cli module.
- "key_components": array of strings. Repository paths carrying most of the
  code, copied verbatim from the listing. Never list third-party libraries
  here. Prefer four to eight entries over a long list.
- "confidence": string. low, medium or high. Use high only if the source you
  read backs the kind and the components you named. When the excerpts were
  truncated, or you could not read what you needed, say so with a lower
  confidence.

If you could not read enough to be sure, say so in the summary. A description
that admits its gaps is more useful to the next agent than one that hides them.

How the run went: you read {rounds} round(s) of source, {files_read} files in
total, and your hypothesis was {verdict} by the code. Weigh your confidence
accordingly, and correct the hypothesis if the code refuted it.

Files you read:

{read_paths}

Repository structure:

{facts}

Source you read:

{excerpts}