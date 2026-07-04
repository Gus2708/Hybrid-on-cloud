# Plan 008: Restringir CORS a orígenes conocidos

> **Instrucciones al ejecutor**: Seguí este plan paso a paso. Ejecutá cada verificación antes de avanzar. Si alguna condición de STOP ocurre, detené y reportá. Al terminar, actualizá la fila en `plans/README.md`.
>
> **Drift check**: `git diff --stat cc62d24..HEAD -- app.py config.py`

## Status

- **Priority**: P3
- **Effort**: S
- **Risk**: LOW
- **Depends on**: none
- **Category**: security
- **Planned at**: commit `cc62d24`, 2026-06-20

## Por qué importa

`CORS(app)` sin parámetros permite que cualquier origen web haga requests a la API. Combinado con la falta de auth en los endpoints de sync (plan 004), esto significa que una página web maliciosa servida a alguien en la red local podría hacer requests cross-origin a `http://localhost:5000/api/v1/sync/force` y disparar operaciones costosas.

Este es un hallazgo de riesgo LOW porque el backend está en la red local y los clientes conocidos son: el widget (no usa XHR), y posibles apps de catálogo en la misma red. Pero restringir CORS es una práctica defensiva con costo de esfuerzo mínimo.

## Estado actual

```python
# app.py:15-18
from flask_cors import CORS

app = Flask(__name__)
CORS(app)  # ← acepta cualquier origen, sin restricción
```

Clientes conocidos del proyecto (de CLAUDE.md y README):
- El widget (`widget.pyw`) — usa `urllib.request` directamente, no navegador
- Apps externas de catálogo — acceden a `/api/v1/productos` para búsqueda de productos

## Comandos necesarios

| Propósito | Comando | Esperado |
|-----------|---------|----------|
| Tests | `python -m pytest tests/ -v` | Todos pasan |
| Verificar CORS en header | Iniciar app y hacer request con Origin header | Ver `Access-Control-Allow-Origin` en respuesta |

## Scope

**En scope**:
- `app.py` — solo la línea `CORS(app)`
- `config.py` — agregar `CORS_ORIGINS` configurable (opcional)

**Fuera de scope**:
- El resto de `app.py`

## Git workflow

- Branch: `advisor/008-restrict-cors`
- Commit: `security: restringir CORS a orígenes locales conocidos`

## Pasos

### Paso 1: Identificar los orígenes que realmente usan la API

Antes de restringir, verificar qué orígenes necesitan acceso:

```powershell
# Buscar referencias a la URL de la API en el código
Select-String -Path *.py,*.pyw -Pattern "localhost:5000|127.0.0.1:5000" -Recurse
```

Los orígenes típicos para este deployment:
- `http://localhost:5000` (el mismo servidor accediendo a sí mismo)
- `http://127.0.0.1:5000`
- Cualquier app de catálogo en la red local (IP 192.168.x.x)

### Paso 2: Agregar `CORS_ORIGINS` a `config.py`

```python
# ─── CORS ─────────────────────────────────────────────────────────────────────
# Lista de orígenes permitidos separada por comas. "*" permite todos (solo dev).
CORS_ORIGINS = os.environ.get("CORS_ORIGINS", "http://localhost:5000,http://127.0.0.1:5000").split(",")
```

### Paso 3: Actualizar `CORS(app)` en `app.py`

```python
# ANTES:
CORS(app)

# DESPUÉS:
from config import CORS_ORIGINS
CORS(app, origins=CORS_ORIGINS, supports_credentials=False)
```

**Verificar**: `python -c "import ast; ast.parse(open('app.py').read()); print('OK')"` → OK
**Verificar**: `python -m pytest tests/ -v` → todos pasan

### Paso 4: Documentar en `.env.example`

Agregar:
```
# Orígenes permitidos por CORS (separados por coma). Dejar vacío o * para permitir todos.
CORS_ORIGINS=http://localhost:5000,http://127.0.0.1:5000
```

## Plan de tests

```python
def test_cors_origen_local_permitido(client):
    """Requests desde localhost tienen el header CORS correcto."""
    response = client.get("/api/v1/productos", headers={"Origin": "http://localhost:5000"})
    assert response.status_code == 200
    # El header debe estar presente con el origen local
    assert "Access-Control-Allow-Origin" in response.headers

def test_cors_origen_externo_no_incluido(client):
    """Requests desde un origen externo no tienen Access-Control-Allow-Origin."""
    response = client.get("/api/v1/productos", headers={"Origin": "https://malicious.example.com"})
    # Con la restricción, el header no incluye el origen externo
    acao = response.headers.get("Access-Control-Allow-Origin", "")
    assert "malicious.example.com" not in acao
```

## Criterios de done

- [ ] `CORS(app)` en `app.py` incluye `origins=CORS_ORIGINS`
- [ ] `config.py` exporta `CORS_ORIGINS`
- [ ] `.env.example` documenta `CORS_ORIGINS`
- [ ] `python -m pytest tests/ -v` → todos pasan
- [ ] Solo los archivos de Scope fueron modificados
- [ ] Fila en `plans/README.md` actualizada a DONE

## Condiciones de STOP

- Alguna app de catálogo usa un origen que no está en la lista → agregar ese origen a `CORS_ORIGINS` antes de deployar

## Notas de mantenimiento

- Si se despliega una app web de catálogo con un dominio propio, agregar ese dominio a `CORS_ORIGINS` en el `.env`
- No usar `"*"` en producción — usar la lista específica de orígenes
