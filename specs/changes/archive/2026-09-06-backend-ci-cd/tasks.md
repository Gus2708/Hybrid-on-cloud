# Tasks: backend-ci-cd

## Review Workload Forecast
Estimated changed lines: 120-220
Estimated product files: 4-6
Target budget: 800 lines and 15 files
Hard limit: 1000 lines and 25 files
Budget risk: Low
Independent slices possible: No
Shared production files across slices: No
Forecast basis: proposal/spec/design focused exploration

## Delivery Plan
Strategy: single-pr
Model: whole
PR mode: draft
PR creation point: final verify only
Current delivery unit: whole

### Whole Delivery
Planned branch/base: sdd/backend-ci-cd -> main
Scope: Configuración e implementación de pipelines de CI/CD para GitHub Actions (ci.yml y release.yml) con soporte para Windows runner, Ruff, Pytest, Nuitka e Inno Setup.

## Slice: whole — Pipelines de Integración y Entrega Continua

### Phase 1: Pipeline de Integración Continua (CI)
- [x] 1.1 Configuración de workflow de CI para GitHub Actions
  - [x] 1.1.a Safety Net evidence: comprobar ausencia de `.github/workflows/ci.yml`.
  - [x] 1.1.b RED failing test: añadir test unitario que valide la existencia y parseo sintáctico de `.github/workflows/ci.yml`.
  - [x] 1.1.c GREEN implementation: crear `.github/workflows/ci.yml` con triggers en `main`, runner `windows-latest`, Python 3.14 con pip cache, Ruff y Pytest.
  - [x] 1.1.d TRIANGULATE second case: validar que el workflow define el step de upload de artefacto de cobertura `coverage.xml`.
  - [x] 1.1.e REFACTOR evidence: estructurar pasos limpios con nombres idiomáticos en inglés y variables reutilizables.

### Phase 2: Pipeline de Entrega Continua y Empaquetado (CD)
- [x] 2.1 Configuración de workflow de Release y empaquetado para Windows
  - [x] 2.1.a Safety Net evidence: comprobar ausencia de `.github/workflows/release.yml`.
  - [x] 2.1.b RED failing test: añadir test unitario que valide la existencia y parseo sintáctico de `.github/workflows/release.yml`.
  - [x] 2.1.c GREEN implementation: crear `.github/workflows/release.yml` con triggers de tags `v*`, instalación de Inno Setup con Chocolatey, compilación con Nuitka e Inno Setup y publicación en GitHub Releases.
  - [x] 2.1.d TRIANGULATE second case: validar que el workflow define permisos `contents: write` y asset `installer/Instalador_HybridOnCloud.exe`.
  - [x] 2.1.e REFACTOR evidence: asegurar consistencia en variables de entorno y soporte para ejecución manual (`workflow_dispatch`).

### Phase 3: Robustez de Empaquetado y Documentación de Perfil
- [x] 3.1 Verificación de compatibilidad desatendida y sincronización de perfil SDD
  - [x] 3.1.a Safety Net evidence: inspeccionar `scripts/build_nuitka.py` y `specs/change-system/profile.md`.
  - [x] 3.1.b RED failing test: test que valide que el script de compilación maneja rutas absolutas relativas a la raíz del repositorio.
  - [x] 3.1.c GREEN implementation: asegurar que `scripts/build_nuitka.py` opere de forma desatendida y registrar CI en `profile.md`.
  - [x] 3.1.d TRIANGULATE second case: N/A — verificación estructural de configuración y comandos de perfil.
  - [x] 3.1.e REFACTOR evidence: verificación con `python -m ruff check .` y suite completa de pruebas.
