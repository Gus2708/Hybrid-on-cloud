# Delta Spec: continuous-integration

## ADDED Requirements

### Requirement: continuous-integration/workflow-trigger — GitHub Actions CI Triggering
The system MUST execute the Continuous Integration workflow automatically upon code updates targeted at the primary branch and allow on-demand manual dispatch.

#### Scenario: Code pushed or PR opened against main branch
- GIVEN a commit pushed to `main` or a pull request opened targeting `main`
- WHEN the GitHub Actions runner evaluates the repository event triggers
- THEN the CI workflow job MUST be queued and run on `windows-latest`.

#### Scenario: Manual trigger via workflow dispatch
- GIVEN an authorized user on GitHub Actions UI or via GitHub CLI
- WHEN the user dispatches the CI workflow manually
- THEN the workflow MUST run without requiring a new git commit.

### Requirement: continuous-integration/quality-and-tests — Automated Linter and Test Gate
The system MUST validate code quality via Ruff and execute the entire test suite via Pytest with coverage reporting, failing the job if any check does not pass.

#### Scenario: All tests pass and linter reports zero errors
- GIVEN the repository codebase in a compliant state
- WHEN the CI job executes `python -m ruff check .` and `python -m pytest`
- THEN both commands MUST exit with code 0, coverage report MUST be generated, and the job status MUST be green (success).

#### Scenario: Regression introduced in tests or linter
- GIVEN a code change containing a broken test or undeclared variable
- WHEN the CI job runs the validation step
- THEN the step MUST exit with a non-zero code, the workflow run MUST be marked as failed, and subsequent release actions MUST NOT proceed.
