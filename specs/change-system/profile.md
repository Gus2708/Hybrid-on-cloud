project: backend serrucho
stack:
  languages: [python]
  frameworks: [flask]
  runtime: [python 3.14, windows]
architecture:
  app_type: hybrid-backend-sync-rpa
  main_areas: [api, sync, hybrid_writeback, watchdog]
conventions:
  branching: null
  testing_style: tdd
  spec_style: delta
testing:
  unit: python -m pytest
  integration: null
  e2e: null
  default_command: python -m pytest
quality:
  lint_command: python -m ruff check .
  typecheck_command: null
ci_cd:
  provider: github-actions
  runner: windows-latest
  workflows: [.github/workflows/ci.yml, .github/workflows/release.yml]
notes:
  - CI ejecuta linter Ruff y pytest completo en cada push/PR a main
  - CD compila Nuitka y empaqueta instalador Inno Setup en tags v*
updated_at: '2026-09-06T05:22:00.000000+00:00'
