Compare implementation, not names:
- Layered: entry, application/business, persistence roles and dependency direction.
- Hexagonal: a use case consumes a port, an adapter implements that port, and composition selects the implementation. Inspect domain responsibilities and dependency inversion. Clean architecture is a related but separate interpretation, not a mandatory ideal for every hexagonal project.
- MVC: model/view/controller responsibilities and interaction, not framework choice.
- Modular: functional boundaries and controlled cross-module access, not folders.
- Distributed/event-driven: execution boundaries, communication, producers/consumers;
  containers, Redis, or a broker dependency alone establish neither.
Allow mixed/partial/other styles. Check boundaries and counterexamples; do not infer
global compliance from a few files or self-description.

For a supported closest_architecture, supply observed_paths: one or two arrays of
supported ArchitectureConnection objects forming continuous responsibility chains.
Follow an actual entry -> coordination -> domain/infrastructure path as applicable;
do not invent missing layers. Cite the initiating call/wiring and receiving contract
or implementation for each edge, and describe the concrete connection mechanism.
Show responsibility and dependency direction, not just imports or folder names.
Assessment evidence must overlap the inspected path. Use scope_kind=local with a
precise assessment.scope by default. Repository scope requires a second independent
path with different implementation files; this still does not prove global compliance.

Supply contrast_question (a specific possible contradiction to this pattern) and
contrast_result (a supported claim citing inspected source). Inspect a likely boundary
exception or alternate connection; report what it shows and its limited scope. A
negative finding only concerns inspected code, never proves repository-wide absence.
An exception can weaken the classification or become a deviation; it is not necessarily
a defect. If path or contrast evidence is missing, use hypothesis/unresolved with
explicit limitations instead of forcing a supported classification.

For infrastructure, distinguish configuration, initialization and an implementation
use site. Connect these where inspected; configuration alone establishes only configured.
Use remaining tools for missing endpoints or contrast, prioritizing symbol/range reads.

Dependency inversion is not a linear runtime chain. For hexagonal interpretation,
you may supply observed_dependencies instead of observed_paths: supported links such
as UseCase -> Port and Adapter -> Port (and composition wiring where inspected).
Preserve the real dependency direction; do not invent a Port -> Adapter import to
force a continuous path. Cite both responsibilities for each link and declare
core/port/adapter organization units, rather than only one deployment-wide unit.
For local scope, source-backed port use, adapter implementation, and wiring when
available can support the observed pattern without proving isolation of every module.
Framework decorators or an imperfect boundary can be scoped deviations, not automatic
reasons to downgrade the entire pattern to hypothesis. A contrast can inspect the same
source for direct concrete-adapter dependency versus the consumed port; no separate
repository-wide absence proof is required. Distinguish pattern presence from compliance.
