# Proposal: backend-ci-cd

## Intent
Actualmente el proyecto cuenta con 174 pruebas automatizadas y reglas de linter estrictas con Ruff, pero toda la validación depende de la ejecución manual en la máquina del desarrollador antes de hacer commits. La falta de una canalización de CI/CD expone el repositorio a regresiones no detectadas en Pull Requests y ramas remotas, y requiere que la compilación de ejecutables con Nuitka y el empaquetado del instalador con Inno Setup se realicen artesanalmente.

Esta propuesta establece una canalización automatizada mediante GitHub Actions para:
1. Validar la suite completa de pruebas y linters en cada push y PR hacia `main`.
2. Empaquetar y publicar automáticamente los instaladores de Windows (`Instalador_HybridOnCloud.exe`) en GitHub Releases ante nuevos tags o ejecuciones manuales.

## Scope
### In Scope
- Creación de `.github/workflows/ci.yml` configurado en `windows-latest` con Python 3.14.
- Ejecución automatizada de `ruff check .` y `python -m pytest` con cobertura de código.
- Carga de reporte de cobertura como artefacto en GitHub Actions.
- Creación de `.github/workflows/release.yml` para compilar con Nuitka (`scripts/build_nuitka.py`) y generar instalador con Inno Setup (`installer.iss`).
- Publicación de Releases en GitHub con `softprops/action-gh-release` al pushear tags `v*.*.*` o despacho manual (`workflow_dispatch`).
- Documentación de procedimientos y variables de entorno en el README o guías.

### Out of Scope
- Despliegue de bases de datos o modificaciones automáticas de esquema en Supabase.
- Configuración de runners auto-hospedados (self-hosted); se emplean los runners estándar de GitHub (`windows-latest`).
- Firma digital de código con certificados EV/OV para Windows (SmartScreen), a menos que el usuario provea credenciales de certificado.

## Capabilities
### New Capabilities
- `continuous-integration`: Ejecución desatendida y periódica de análisis estático (Ruff) y suite de pruebas unitarias/integración en entorno Windows reproducible.
- `continuous-delivery`: Compilación automática desatendida de ejecutable nativo (`widget.exe`) vía Nuitka, empaquetado en instalador (`Instalador_HybridOnCloud.exe`) con Inno Setup y distribución de release en GitHub.

### Modified Capabilities
- Ninguna (no se modifican capacidades previas del sistema).

## Approach
1. **Pipeline de CI (`.github/workflows/ci.yml`)**:
   - Se activará en eventos `push` a `main`, `pull_request` dirigidos a `main`, y `workflow_dispatch`.
   - Utilizará el runner `windows-latest` para garantizar compatibilidad con `pywin32` y módulos Win32 de bajo nivel.
   - Cacheará el directorio de paquetes de `pip` vinculado a `requirements-dev.txt`.
   - Ejecutará `python -m ruff check .` para fallo inmediato ante cualquier discrepancia sintáctica o de imports.
   - Ejecutará `python -m pytest` con parámetros de cobertura XML y resumen en consola.
   - Preservará el reporte de cobertura mediante `actions/upload-artifact`.

2. **Pipeline de CD / Release (`.github/workflows/release.yml`)**:
   - Se activará al crear tags con patrón `v*` (ejemplo `v1.2.0`) o mediante ejecución manual (`workflow_dispatch`).
   - Instalará Inno Setup en el runner vía Chocolatey (`choco install innosetup -y`).
   - Instalará dependencias y ejecutará `python scripts/build_nuitka.py` en modo no interactivo (`--assume-yes-for-downloads`).
   - Compilará el instalador con `iscc installer.iss`.
   - Utilizará `softprops/action-gh-release` con permisos de escritura de releases (`contents: write`) para publicar el instalador generado junto con el log de cambios automático.

## Affected Areas
| Area | Impact | Description |
|------|--------|-------------|
| `.github/workflows/ci.yml` | New | Workflow de pruebas continuas, linter y cobertura en GitHub Actions. |
| `.github/workflows/release.yml` | New | Workflow de empaquetado Nuitka e Inno Setup para releases. |
| `scripts/build_nuitka.py` | Modify | Confirmación de flags desatendidos y paths relativos correctos para CI. |
| `specs/change-system/profile.md` | Modify | Actualización del perfil del proyecto con comandos de CI/CD. |

## Risks
| Risk | Likelihood | Mitigation |
|------|------------|------------|
| Tiempo de build prolongado en Nuitka durante CI | Baja | La compilación Nuitka solo se ejecuta en el workflow `release.yml` (tags o manual), nunca en el flujo rápido de PRs/push (`ci.yml`). |
| Incompatibilidad de versión de Python 3.14 en runner | Baja | `actions/setup-python@v5` soporta oficialmente 3.14; se verificará la instalación limpia. |
| Permisos insuficientes en GITHUB_TOKEN para crear releases | Media | Se declara explícitamente el bloque `permissions: contents: write` en `release.yml`. |

## Rollback Plan
Si los workflows de GitHub Actions introducen alguna fricción o no son deseados, basta con eliminar los archivos bajo `.github/workflows/` y descartar la rama, lo cual devolverá el repositorio a su estado previo sin alterar ningún archivo del código fuente del backend.

## Success Criteria
- [ ] Workflow `ci.yml` creado y con sintaxis YAML válida.
- [ ] Ejecución exitosa de `ruff check .` y `python -m pytest` dentro del job de CI en `windows-latest`.
- [ ] Workflow `release.yml` creado y configurado con instalación automática de Inno Setup, compilación Nuitka y publicación de artefactos en GitHub Releases.
- [ ] Generación de reporte de cobertura de pruebas como artefacto adjunto.
- [ ] Validación sin errores mediante `sdd check --change backend-ci-cd`.

## Open Questions
- [ ] Ninguna; los requerimientos de CI y empaquetado CD están completamente definidos a partir de los scripts existentes.
