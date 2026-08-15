# Repository instructions

## Project direction

- Read `PLAN.md` before making architectural or behavioral changes. Treat it as
  the current product specification unless the user explicitly changes a
  decision.
- Target the geninit runtime at Python 3.15 and newer only. Do not add runtime
  compatibility code, syntax fallbacks, or tests for earlier Python versions.
  Continue generating eager imports for target projects that support Python
  versions earlier than 3.15.
- Keep the implementation small, direct, and elegant. Prefer a clear function
  or dataclass over a framework, abstraction layer, or speculative extension
  point.
- Do not broaden scope beyond the requested behavior. Avoid infrastructure,
  configuration, or generalization that has no current use case.

## Dependency and environment policy

- Use `uv` for Python versions, environments, dependency changes, locking, and
  command execution. Do not use `pip` directly.
- Use the latest available Ruff release compatible with this project.
- Retain uv's security-oriented `first-index` behavior. Never configure
  `unsafe-first-match`, `unsafe-best-match`, an insecure host, or disabled TLS
  verification.
- Run normal validation through the checked-in lockfile with
  `uv run --locked ...`. Change dependencies explicitly with `uv add`,
  `uv remove`, or `uv lock`, and review both `pyproject.toml` and `uv.lock`.
- Do not introduce Git, URL, local-path, or alternate-index dependencies
  without explicit user approval.
- Before implementing a feature that could reasonably use a third-party
  package, present the package and its tradeoffs to the user. Do not silently
  reinvent substantial third-party functionality or silently add a dependency.
- Keep runtime dependencies limited to the user-approved Click and packaging
  libraries. Development dependencies for the agreed toolchain are allowed.

## Python style and design

- Use Ruff as both formatter and linter, with the checked-in line length,
  Python 3.15 as the target, and `lint.select = ["ALL"]`.
- Prefer double-quoted strings and Google-style docstrings. Document every
  public module, class, function, method, and exception where its purpose is
  not self-evident.
- Fully annotate public APIs. Keep internal annotations precise enough for
  Pyrefly to check without suppressions or broad `Any` types.
- Use modern Python 3.15 language and standard-library features when they make
  the code simpler. In generated files, use native `lazy` imports only when the
  target project's Python constraint permits them, as specified in `PLAN.md`.
- Prefer immutable data, pure analysis functions, explicit inputs and outputs,
  and deterministic ordering. Keep filesystem writes separated from discovery,
  parsing, validation, and rendering.
- Never import a target package merely to inspect it. Source analysis must
  remain static and must not execute user code.
- Catch specific exceptions and preserve actionable context such as the path,
  declaration, or conflicting names. Do not hide programming errors behind a
  broad catch.
- Keep Ruff ignores narrow and justified beside the configuration or code that
  requires them. Do not use blanket `noqa`, file-wide ignores, or type-checker
  suppressions to make checks pass.

## Tests and documentation

- Use `pytest`. Every behavior change and bug fix must include focused tests;
  bug fixes require a regression test that fails without the fix.
- Exercise public behavior through both the library API and CLI where
  applicable. Use temporary directories for filesystem tests and never write
  fixtures into the repository during a test run.
- Cover successful generation, idempotency, deterministic output, invalid
  input, collisions, managed-block preservation, all-or-nothing validation,
  and CLI exit codes. On Python 3.15, test eager output for target projects
  supporting earlier versions and native lazy-import behavior for 3.15-only
  target projects.
- Keep coverage as high as reasonably possible. Do not add low-value tests that
  only mirror implementation details, and do not exclude reachable production
  code merely to increase the percentage.
- Update `README.md` whenever public behavior, configuration, commands, error
  handling, or supported APIs change. Update `PLAN.md` only when the user
  changes the product specification.

## Required validation

- Configure `prek` as the repository's pre-commit runner and keep its hooks
  reproducible through the uv-locked development environment.
- Before declaring a change complete, run the repository's full configured
  gate. At minimum it must cover:

  ```text
  uv run --locked ruff format --check .
  uv run --locked ruff check .
  uv run --locked pyrefly check
  uv run --locked pytest
  uv run --locked prek run --all-files
  ```

- Run focused tests while iterating, then run the full suite before handoff.
  Report any check that could not run, including the reason; do not imply that
  unavailable Python 3.15 checks passed.
- Do not bypass hooks with `--no-verify`. Fix the failure or ask the user about
  a genuine exception.

## Change discipline

- Preserve unrelated user changes and avoid destructive Git operations.
- Do not create commits, tags, releases, or external changes unless the user
  explicitly requests them.
- Keep generated output changes separate from handwritten code. Never edit
  content inside a geninit-managed block by hand when it can be regenerated.
- Review the final diff for accidental files, secrets, debug output, stale
  placeholders, unnecessary abstractions, and changes outside the requested
  scope.
