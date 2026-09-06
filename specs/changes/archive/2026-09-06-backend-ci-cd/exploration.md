# Exploration: backend-ci-cd

## Request Understanding
Implementar una canalización integral de CI/CD (Integración y Despliegue/Entrega Continua) para el backend de Serrucho (`backend serrucho`). El objetivo es garantizar que cada commit y Pull Request valide automáticamente la suite completa de pruebas (174 tests) y la calidad de código con Ruff, además de permitir la generación y empaquetado automático de instaladores ejecutables (`widget.exe` e `Instalador_HybridOnCloud.exe`) para Windows cuando se publique una versión etiquetada (`v*.*.*`) o por despacho manual.

## Current State
- No existe el directorio `.github/workflows/` ni canalizaciones automatizadas en GitHub Actions.
- El proyecto cuenta con una suite sólida y rápida de 174 pruebas unitarias con `pytest` y `pytest-cov`, ejecutándose en ~21.5 segundos.
- La calidad de código está gobernada por `ruff check .` en [`pyproject.toml`](file:///c:/Proyect/backend%20serrucho/pyproject.toml) con 0 errores y configuración para Python 3.14.
- La compilación del cliente local se realiza mediante Nuitka ([`scripts/build_nuitka.py`](file:///c:/Proyect/backend%20serrucho/scripts/build_nuitka.py)) e Inno Setup ([`installer.iss`](file:///c:/Proyect/backend%20serrucho/installer.iss)).
- El entorno de ejecución requiere Windows para `pywin32` y las integraciones del POS físico, aunque los tests se ejecutan de forma aislada e interactúan con `mock_hybrid_env`.

## Affected Areas
| Area | Evidence | Why It Matters |
|------|----------|----------------|
| `.github/workflows/ci.yml` | Inexistente (nuevo seam) | Orquesta validación de calidad y tests en cada push/PR. |
| `.github/workflows/release.yml` | Inexistente (nuevo seam) | Orquesta compilación Nuitka, empaquetado Inno Setup y GitHub Release. |
| `scripts/build_nuitka.py` | [`scripts/build_nuitka.py:L24-43`](file:///c:/Proyect/backend%20serrucho/scripts/build_nuitka.py#L24-L43) | Debe admitir ejecución no interactiva en runners de CI/CD sin prompts de descarga. |
| `requirements-dev.txt` | [`requirements-dev.txt:L1-10`](file:///c:/Proyect/backend%20serrucho/requirements-dev.txt#L1-L10) | Contiene la especificación de dependencias necesarias para los jobs de CI. |
| `specs/change-system/profile.md` | [`specs/change-system/profile.md:L1-23`](file:///c:/Proyect/backend%20serrucho/specs/change-system/profile.md#L1-L23) | Registra comandos de verificación y arquitectura CI del repositorio. |

## Existing Tests
| Test/File | Relevance | Missing Coverage |
|-----------|-----------|------------------|
| `tests/` (174 tests) | Suite completa de pruebas unitarias y de integración de esquemas/sync/writeback | No existen pruebas de sintaxis o schema de GitHub Actions (actionlint / validación YAML). |
| `pyproject.toml` | Configuración de Ruff linter y pytest | Cobertura de tests en CI debe generar reportes de cobertura (XML/terminal). |

## Options
| Option | Pros | Cons | Risk | Effort |
|--------|------|------|------|--------|
| **Opción A: Workflows separados (`ci.yml` y `release.yml`) en runner `windows-latest`** | Separación clara de responsabilidades: `ci.yml` rápido y liviano en cada PR/push; `release.yml` solo se dispara con tags `v*` o manual (`workflow_dispatch`), compila con Nuitka y genera el instalador. Soporte nativo de `pywin32` e Inno Setup. | Consume minutos de Windows runner (típicamente 2x el costo de Ubuntu en cuentas de pago, aunque gratuito dentro de cuota pública/estándar). | Bajo; runner Windows garantiza 100% paridad con entorno de desarrollo y producción. | Medio |
| **Opción B: CI en `ubuntu-latest` con dependencias dummy y CD en `windows-latest`** | CI corre un poco más rápido y consume menos cuota de runner en Linux. | `requirements.txt` tiene `pywin32==312` hardcodeado, lo cual falla inmediatamente en Linux sin flags especiales de plataforma. Rompe paridad. | Alto; requiere reescribir `requirements.txt` con marcadores PEP 508 y arriesga discrepancias. | Alto |
| **Opción C: Archivo único monolítico `main.yml` que hace todo en un solo workflow** | Un solo archivo que gestionar. | Acopla el ciclo rápido de tests con la compilación pesada de Nuitka (que tarda varios minutos), ensuciando los builds de PR. | Medio | Bajo |

## Recommendation
Se recomienda la **Opción A**: dos workflows modulares y especializados:
1. **`ci.yml` (Integración Continua)**:
   - Disparador: `push` a `main`, `pull_request` a `main`, y `workflow_dispatch`.
   - Runner: `windows-latest`.
   - Pasos: Checkout -> Setup Python 3.14 (con caché pip) -> Instalación de `requirements-dev.txt` -> Ejecución de `ruff check .` -> Ejecución de `python -m pytest --cov=schemas --cov-report=xml` -> Carga de artefactos de cobertura.
2. **`release.yml` (Entrega Continua / Empaquetado)**:
   - Disparador: `push` de tags `v*.*.*` o manual (`workflow_dispatch`).
   - Runner: `windows-latest`.
   - Pasos: Checkout -> Setup Python 3.14 -> Instalación de dependencias de producción + Nuitka + zstandard -> Instalación de Inno Setup (via `choco install innosetup`) -> Compilación de `widget.exe` (`scripts/build_nuitka.py`) -> Compilación de instalador con ISCC (`installer.iss`) -> Publicación de GitHub Release con `Instalador_HybridOnCloud.exe` y notas automáticas.

## Risks
- **Tiempo de compilación de Nuitka**: Nuitka puede tardar entre 5 y 10 minutos en compilar en runners de GitHub Actions. Mitigación: sólo se ejecuta en tags o `workflow_dispatch`, nunca bloquea PRs ordinarios de desarrollo.
- **Flags no interactivos en Nuitka**: En un runner sin pantalla, Nuitka debe correr con `--assume-yes-for-downloads` y sin dependencias de terminal interactiva (ya configurado en `scripts/build_nuitka.py`).

## Open Questions
- [ ] ¿Deseas que el workflow de CI publique resumen de cobertura o comentarios en PRs si se configura el token, o simplemente el artefacto descargable y el check de estado de GitHub?
- [ ] ¿Deseas habilitar ejecución manual (`workflow_dispatch`) en ambos workflows para poder lanzarlos a demanda desde la interfaz de GitHub Actions?

## Ready For Planning
Yes. El alcance técnico, las dependencias y la estructura de los workflows están claramente delimitados y fundamentados en la arquitectura del repositorio.
