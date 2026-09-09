# Delta Spec: code-quality

## ADDED Requirements

### Requirement: code-quality/linter-execution — Verificación estática con Ruff
The system MUST provide an automated static analysis configuration using Ruff that validates code hygiene without executing the runtime.

#### Scenario: Clean code verification
- GIVEN a codebase adhering to project import and syntax rules
- WHEN the linter command `python -m ruff check .` is executed
- THEN it exits with return code 0 and reports no diagnostic errors.

#### Scenario: Catching undeclared variables and broken imports
- GIVEN a Python file containing undefined symbols or syntax errors
- WHEN `python -m ruff check .` is executed
- THEN it flags the exact line and file with an error code (such as F821 or F401) and returns a nonzero exit status.

### Requirement: code-quality/coverage-reporting — Medición de cobertura de pruebas
The system MUST enable test coverage reporting across backend packages using `pytest-cov`.

#### Scenario: Coverage calculation during test run
- GIVEN test suites executed with `python -m pytest --cov=.`
- WHEN tests complete
- THEN a terminal summary table of statement coverage per module is generated.
