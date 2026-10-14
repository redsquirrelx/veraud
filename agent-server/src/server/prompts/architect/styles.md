Structural definitions of architectural styles. A style holds when its
criteria hold; a deviation is a failed criterion of the intended style.

- layered: horizontal layers such as presentation, application, domain and
  infrastructure. Dependencies point strictly downward toward infrastructure,
  never upward. Execution enters through the top layer.
- hexagonal: a domain core with no outward dependencies. The core exposes
  ports (interfaces) and infrastructure provides adapters implementing them.
  Every dependency points inward toward the domain.
- mvc: models holding state and logic, views rendering it, controllers
  mediating a request and response cycle. Controllers stay thin; views never
  touch storage directly.
- modular_monolith: one deployable unit with clear module boundaries. Modules
  expose explicit public APIs and depend on each other little. No network
  calls between modules.
- microservices: independently deployable services, each with its own
  datastore, communicating over the network. A shared database disqualifies it.
- serverless: stateless handlers triggered by platform events. No managed
  servers, no long-lived processes, no local state assumed across calls.
- plugin: a stable core plus extensions discovered and loaded at runtime
  through a plugin interface. The core never imports extensions directly.
