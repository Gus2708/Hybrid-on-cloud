# Plan 011: Fijar versiones de dependencias y agregar lockfile

> **Instrucciones al ejecutor**: Seguí este plan paso a paso. Ejecutá cada verificación antes de avanzar. Si alguna condición de STOP ocurre, detené y reportá. Al terminar, actualizá la fila en `plans/README.md`.
>
> **Drift check**: `git diff --stat cc62d24..HEAD -- requirements.txt`

## Status

- **Priority**: P2
- **Effort**: S
- **Risk**: LOW
- **Depends on**: none
- **Category**: deps
- **Planned at**: commit `cc62d24`, 2026-06-20

## Por qué importa

`requirements.txt` usa versiones sin pin (`requests`, `beautifulsoup4`, `pywin32`) o con rango amplio (`Flask>=2.3.0`). Si un paquete en el índice de PyPI publica una versión nueva con un bug o vulnerabilidad, la próxima instalación limpia podría traerla sin que nadie lo note. Sin lockfile, no hay reproducibilidad entre la PC de la ferretería y un hipotético ambiente de pruebas.

La fix es: capturar las versiones actualmente instaladas (que sabemos que funcionan) y fijarlas en `requirements.txt`.

## Estado actual

```
# requirements.txt (actual)
Flask>=2.3.0
requests
python-dotenv
pytest
pytest-flask
pytest-mock
responses
Pillow
pystray
beautifulsoup4
pywin32
```

Packages faltantes en requirements.txt (usados en el código):
- `watchdog` — usado en `monitor.py`
- `flask-cors` — usado en `app.py`
- `pydbisam` — usado en `sync_ajustes.py` (plan 014 lo cubre en más detalle)

## Comandos necesarios

| Propósito | Comando | Esperado |
|-----------|---------|----------|
| Ver versiones instaladas | `python -m pip freeze` | Lista de paquetes con versiones |
| Instalar desde requirements | `python -m pip install -r requirements.txt` | Sin errores |
| Tests | `python -m pytest tests/ -v` | Todos pasan |

## Scope

**En scope**:
- `requirements.txt` — actualizar con versiones fijas y paquetes faltantes
- `requirements-dev.txt` (crear) — separar deps de desarrollo de las de producción

**Fuera de scope**:
- Actualizar los paquetes a versiones más nuevas (eso es un upgrade, no un pin)
- `pydbisam` — cubierto en plan 014

## Git workflow

- Branch: `advisor/011-pin-dependencies`
- Commit: `chore: fijar versiones de dependencias y separar deps de dev`

## Pasos

### Paso 1: Capturar versiones instaladas actualmente

```powershell
python -m pip freeze | Select-String "Flask|requests|python-dotenv|Pillow|pystray|beautifulsoup4|pywin32|watchdog|flask-cors"
```

Copiar el output. Debería verse algo como:
```
beautifulsoup4==4.12.x
Flask==3.x.x
flask-cors==4.x.x
Pillow==10.x.x
pystray==0.19.x
python-dotenv==1.x.x
requests==2.x.x
watchdog==4.x.x
pywin32==306
```

### Paso 2: Crear `requirements-dev.txt`

Separar las dependencias de testing/desarrollo:

```
# requirements-dev.txt — solo para desarrollo y CI
-r requirements.txt
pytest==X.X.X
pytest-flask==X.X.X
pytest-mock==X.X.X
responses==X.X.X
```

(Reemplazar X.X.X con las versiones reales del paso 1)

### Paso 3: Actualizar `requirements.txt` con versiones pinadas

Reemplazar el contenido de `requirements.txt` con las versiones exactas capturadas:

```
# requirements.txt — dependencias de producción
# Versiones capturadas el 2026-06-20 con Python 3.14
Flask==X.X.X
flask-cors==X.X.X
requests==X.X.X
python-dotenv==X.X.X
Pillow==X.X.X
pystray==X.X.X
beautifulsoup4==X.X.X
pywin32==XXX
watchdog==X.X.X
```

**Verificar**: `python -m pip install -r requirements.txt --dry-run` → sin errores (o sin cambios si ya están instaladas)

### Paso 4: Verificar que los tests siguen pasando

```powershell
python -m pytest tests/ -v
```

### Paso 5: Documentar en README cómo instalar

Verificar que `README.md` menciona `pip install -r requirements-dev.txt` para desarrollo. Si no, agregar una línea en la sección de instalación.

## Criterios de done

- [ ] `requirements.txt` tiene versiones exactas (sin `>=`, sin sin-pin)
- [ ] `requirements.txt` incluye `watchdog` y `flask-cors` (antes faltaban)
- [ ] `requirements-dev.txt` existe con las dependencias de testing
- [ ] `python -m pip install -r requirements.txt --dry-run` → sin errores
- [ ] `python -m pytest tests/ -v` → todos pasan
- [ ] Solo los archivos de Scope fueron modificados
- [ ] Fila en `plans/README.md` actualizada a DONE

## Condiciones de STOP

- `pip freeze` no muestra `flask-cors` o `watchdog` instalados → instalarlos primero con `pip install flask-cors watchdog`, verificar que el código funciona, luego capturar la versión

## Notas de mantenimiento

- Revisar vulnerabilidades periódicamente con `pip-audit` (instalar con `pip install pip-audit`)
- Para actualizar una dependencia: cambiar la versión en `requirements.txt`, testear, commitear
- `pywin32` tiene versiones sin patch (ej: `306`) — es normal
