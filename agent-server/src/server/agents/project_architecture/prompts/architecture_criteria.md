Compare implementation, not names:
- Layered: entry, application/business, persistence roles and dependency direction.
- Hexagonal/clean: isolated core, ports/adapters, inward dependencies; interfaces alone are insufficient.
- MVC: model/view/controller responsibilities and interaction, not framework choice.
- Modular: functional boundaries and controlled cross-module access, not folders.
- Distributed/event-driven: execution boundaries, communication, producers/consumers;
  containers, Redis, or a broker dependency alone establish neither.
Allow mixed/partial/other styles. Check boundaries and counterexamples; do not infer
global compliance from a few files or self-description.
