# Installed Package Consumer Testbed Rules

This directory is an isolated consumer project used to test an installed package by conversing
with an agent.

## Hard boundary

- Treat every package under evaluation as a complete third-party distribution installed in this
  testbed with the declared environment manager.
- Use package-provided skills when available and only documented public interfaces, including
  installed CLIs, help, schemas, examples, error guidance, and public Python imports explicitly
  described by those resources.
- Do not read, search, import, or modify the evaluated package's implementation source, tests,
  repository-only documentation, examples, showcases, experiments, configuration, or generated
  state outside this `testbed/` directory.
- Do not inspect or change parent-repository paths to learn how an evaluated package works.
- Keep all user-project data, configuration, state, research records, extensions, and outputs
  inside this directory.
- If package-provided skills or public interfaces are insufficient, report the missing public
  capability as a product finding. Do not bypass the boundary by inspecting internals.

## Working style

- Begin package tasks from the package-provided skill selected for the request, when one is
  installed.
- Inspect user inputs read-only before proposing mappings, transformations, or configuration.
- Do not infer ambiguous domain, identifier, time, availability, unit, or schema semantics.
- Show the files and assumptions that a mutating action will use, then validate through documented
  public commands.


<!-- qlibx:managed:start -->
Use `qlibx --help`, `qlibx data requirements`, and the generated qlibx skill. Treat project source data as read-only; use only public qlibx APIs; never edit installed qlibx or Qlib.
<!-- qlibx:managed:end -->
