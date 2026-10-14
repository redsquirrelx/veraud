Decide which files to read to confirm the architectural reading.

You are given the frame: the observed style ({style}), what the repository
seems to try to be ({intended}), and the deviations found so far. You are also
given the key components carrying most of the code and the entry points.

Answer ONLY with a JSON object. Its keys:

- "paths": array of strings. File paths, copied verbatim from the listing,
  to read next. At most {max_paths}. Prefer, in this order: the evidence
  behind each deviation (what breaks the pattern is the most rentable to
  read), the entry points, then the top key components. Return an empty array
  if nothing is worth reading.

Key components still undescribed (these are why you are reading again, so
they outrank everything but deviation evidence):

{undescribed}

Repository structure:

{facts}

Directory profiles:

{directory_profiles}

Frame:

{frame}
