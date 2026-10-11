Group the repository's important files into containers: deployable or
runnable units that a newcomer would recognize (a web frontend, an API
service, a worker, a shared core). You have read source excerpts, so group
by what the code does together, not by directory names alone.

You are given the repository structure, the key components and the source
you have read. Name at most {max_containers} containers: fewer, larger
units beat a file listing with new names. No business actors, no external
systems, no users: containers hold repository files only.

Answer ONLY with a JSON object. Its keys:

- "containers": array of objects. Each has "name" (string, short, lowercase
  words like "api service"), "responsibility" (string, one line on what this
  container does) and "files" (array of strings: repository paths copied
  verbatim from the listing below that belong in it).
- "externals": array of objects. Third-party dependencies grouped by the
  architectural role the system uses them for: persistence, HTTP serving,
  AI providers, and so on. Each has "name" (string, the role, like
  "persistence") and "members" (array of strings copied verbatim from the
  third-party list below). One catch-all group (name it "third-party") when
  no roles emerge; an empty array when there are no third-party dependencies
  at all. Never invent a dependency: a member not on the list poisons the
  whole group, so leave it out. At most {max_external_groups} groups: roles
  that matter, not one box per dependency.

Key components to place:

{components}

Third-party dependencies to group:

{third_party}

Source you read:

{excerpts}

Repository structure:

{facts}

Directory profiles:

{directory_profiles}
