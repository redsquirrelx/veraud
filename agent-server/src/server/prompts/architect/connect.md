Trace how execution flows through this repository, in prose.

You are given the architectural frame (observed style, intended style),
the entry points, the key components, and source you have read. Describe the
path execution takes from each entry point through the components it reaches.
Name the exact files at each step.

Answer ONLY with a JSON object. Its keys:

- "data_flow": string. Two to five sentences. One per entry point when there
  are several. Say what calls what, using paths copied verbatim. If the reads
  do not show the flow, say what is missing instead of inventing it.

Frame:

{frame}

Entry points:

{entrypoints}

Key components:

{components}

Source you read:

{excerpts}
