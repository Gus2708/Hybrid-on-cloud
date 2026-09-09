# Design: backend-ci-cd

## Technical Approach
Implementar dos flujos de trabajo independientes y altamente especializados en GitHub Actions utilizando runners de Windows (`windows-latest`) para garantizar 100% de paridad con las dependencias nativas del backend (`pywin32`, `pydbisam`, Inno Setup):

1. **`.github/workflows/ci.yml`**:
   - Se ejecuta en cada `push` a `main`, `pull_request` a `main` y disparo manual (`workflow_dispatch`).
   - Configura Python 3.14 con caché nativo de dependencias `pip`.
   - Instala `requirements-dev.txt`.
   - Ejecuta `python -m ruff check .` para validación estricta de sintaxis, variables y dependencias en milisegundos.
   - Ejecuta `python -m pytest --cov=schemas --cov-report=xml:coverage.xml --cov-report=term` para validar las 174 pruebas y medir cobertura.
   - Sube `coverage.xml` como artefacto de GitHub Actions.

2. **`.github/workflows/release.yml`**:
   - Se ejecuta ante la creación de un tag `v*` o disparo manual (`workflow_dispatch`).
   - Instala Inno Setup mediante `choco install innosetup -y`.
   - Instala dependencias de compilación (`nuitka`, `zstandard`, `requirements.txt`).
   - Compila el ejecutable independiente `widget.exe` ejecutando `python scripts/build_nuitka.py`.
   - Compila el instalador gráfico para Windows ejecutando `iscc installer.iss`.
   - Publica un nuevo GitHub Release usando `softprops/action-gh-release@v2`, adjuntando `installer/Instalador_HybridOnCloud.exe` como binario descargable y generando el changelog automáticamente.

## Architecture Decisions
| Decision | Choice | Alternatives | Rationale |
|----------|--------|--------------|-----------|
| Runner de GitHub Actions | `windows-latest` | `ubuntu-latest` | El backend requiere `pywin32` y módulos Win32; Inno Setup es nativo de Windows. |
| Separación de flujos | Dos archivos (`ci.yml` y `release.yml`) | Archivo único monolítico | Permite que los tests y linter corran en ~1-2 min en cada PR sin disparar la compilación pesada de Nuitka. |
| Instalación de Inno Setup | `choco install innosetup -y` | Third-party Action | Chocolatey está preinstalado en runners de Windows de GitHub Actions; no añade dependencias externas. |
| Gestión de Releases | `softprops/action-gh-release@v2` | `gh release create` por CLI | Maneja reintentos de upload de binarios grandes de forma robusta con permisos de token estándar. |

## Architecture Design

### Project Placement
```text
.github/
└── workflows/
    ├── ci.yml
    │   └── ci_job()
            [new] Pipeline de CI: linter Ruff, ejecución de 174 tests de Pytest y reporte de cobertura.
    └── release.yml
        └── release_job()
            [new] Pipeline de CD: compilación Nuitka, empaquetado Inno Setup y publicación en GitHub Releases.
scripts/
└── build_nuitka.py
    └── build()
        [modify] Asegurar flags no interactivos para ejecución limpia en runners desatendidos.
specs/
└── change-system/
    └── profile.md
        └── profile_metadata()
            [modify] Actualizar perfil con información de automatización CI/CD.
```

### Data Flow
```text
[Developer / PR]
       │
       ▼ (push / pull_request)
[GitHub Actions CI (ci.yml)]
       │
       ├─► [Ruff Lint Check] ──(fail)──► [Block PR / Notify]
       │
       └─► [Pytest 174 tests] ──(fail)──► [Block PR / Notify]
               │
               ▼ (pass)
       [Coverage Artifact Upload] ──► [Green Checkmark on GitHub]

[Git Tag v*.*.* / Manual Dispatch]
       │
       ▼
[GitHub Actions CD (release.yml)]
       │
       ├─► [Install Inno Setup via choco]
       ├─► [Run scripts/build_nuitka.py] ──► widget.exe
       ├─► [Run iscc installer.iss] ──────► Instalador_HybridOnCloud.exe
       │
       ▼
[softprops/action-gh-release] ────────► GitHub Release publicado con instalador adjunto
```

### Behavior Flow
1. **Flujo de Integración**: Un desarrollador abre un PR o pushea a `main`. El workflow `ci.yml` clona el repositorio, monta Python 3.14 con pip cache, instala `requirements-dev.txt`, corre `ruff check .` y luego `pytest`. Si alguna prueba falla o el linter detecta una variable no definida, el build se interrumpe con código de error.
2. **Flujo de Entrega**: Al etiquetar una versión estable (`git tag v1.2.1 && git push origin v1.2.1`), `release.yml` monta el entorno de compilación, ejecuta Nuitka y el compilador de Inno Setup. El artefacto final `Instalador_HybridOnCloud.exe` se asocia al release en GitHub junto con las notas de versión.

### Interfaces / Contracts
- GitHub Actions Workflow Schema v2 (YAML).
- Permisos explícitos: `permissions: contents: write` en `release.yml` para creación de releases.
- Invocación de Inno Setup: `iscc installer.iss`.

## Testing Strategy
| Layer | What | Approach |
|-------|------|----------|
| Sintaxis YAML | `.github/workflows/*.yml` | Validación de parsing YAML y coherencia de steps y triggers. |
| Linter Local | `ruff check .` | Ejecución idéntica en local y en runner remoto. |
| Test Suite | `pytest` | Ejecución de los 174 tests pasando en <25 segundos. |
| Dry-run de scripts | `scripts/build_nuitka.py` | Verificación de que el script puede importarse y admite ejecución no interactiva. |

## Migration / Rollout
Los archivos de workflow se añaden a `.github/workflows/`. Al pushear a GitHub, los checks se activan inmediatamente en la pestaña Actions sin requerir configuración adicional de secrets obligatorios (usa el `GITHUB_TOKEN` integrado).

## Technical Risks
| Risk | Likelihood | Mitigation |
|------|------------|------------|
| Consumo de minutos en Windows runners | Baja | `ci.yml` es ultrarrápido (<2 minutos). `release.yml` solo se ejecuta ante tags de versión. |
| Dependencias faltantes en runner de compilación | Baja | Se instalan explícitamente `nuitka` y `zstandard` junto con `requirements.txt`. |

## Open Questions
- [ ] Ninguna; el diseño aprovecha la infraestructura nativa ya preparada en el proyecto.
