change: backend-assurance-and-tests
flow: spec
mode: standard
pace: semi-supervised
artifact_store: files
verbosity: concise
tdd_mode: strict
review_mode: strict
pr_strategy: single-pr
pr_mode: draft
review_budget_lines: 800
review_hard_limit_lines: 1000
review_budget_files: 15
review_hard_limit_files: 25
delivery:
  model: whole
  whole_pr:
    branch: sdd/backend-assurance-and-tests
    base: main
    draft_pr: true
    status: created
    url: https://github.com/Gus2708/Hybrid-on-cloud/pull/1
  feature_base_branch: null
  base_branch: null
  feature_pr:
    draft_pr: true
    status: not_ready
    url: null
  active_slice: null
  next_slice: null
  reopen_unit: null
  slices: []
current_phase: archive
next_phase: null
status:
  plan: pending
  exploration: done
  proposal: done
  spec: done
  design: done
  tasks: done
  apply: done
  verify: done
  archive: done
artifacts:
  intent: null
  exploration: null
  correction: null
  proposal: null
  spec: []
  design: null
  tasks: null
  refactor: null
  verify_report: null
  archive_report: null
decisions:
- Configurar Ruff para linting y formateo ultrarrápido compatible con Python 3.14 en pyproject.toml
- Integrar Pydantic v2 para validación estricta de esquemas de datos en fronteras de sync y writeback
- Construir arnés de pruebas para hybrid_writeback sin requerir entorno gráfico interactivo
- Añadir cobertura de pruebas a sync_ventas, sync_ajustes y watchdog
open_questions: []
blocked_reasons: []
updated_at: '2026-09-06T05:18:15.243206+00:00'
