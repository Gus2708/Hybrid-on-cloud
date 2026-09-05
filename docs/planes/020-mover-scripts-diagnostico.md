# Plan 020: Mover los scripts de diagnóstico de `hybrid_writeback/` a `hybrid_writeback/diagnostico/`

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. Do NOT update `plans/README.md` — your reviewer
> maintains the index.
>
> **Drift check (run first)**:
> `git diff --stat 2ad838c..HEAD -- hybrid_writeback/`
> Cambios en archivos de PRODUCCIÓN (lista abajo) posteriores a `2ad838c` no
> bloquean este plan (solo movés archivos que no son de producción), pero si
> apareció un archivo .py NUEVO en `hybrid_writeback/` desde entonces,
> tratalo como STOP (hay que clasificarlo antes de mover).

## Status

- **Priority**: P2
- **Effort**: S
- **Risk**: LOW
- **Depends on**: none (compatible con 018/019: no toca los mismos archivos)
- **Category**: tech-debt
- **Planned at**: commit `2ad838c`, 2026-07-12

## Why this matters

`hybrid_writeback/` mezcla 14 módulos de producción con ~55 scripts
desechables de diagnóstico/calibración/exploración (`diag_*`, `dbg_*`,
`shot_*`, `odbc_*`, `dat_*`, `dump_*`, etc.) acumulados durante el desarrollo
de la automatización. Nadie los importa desde producción (verificado
2026-07-12 con grep del grafo de imports). El ruido hace ilegible el paquete:
encontrar el módulo real entre 70 archivos es adivinanza. Moverlos a un
subdirectorio `diagnostico/` con un README deja el paquete de producción
limpio sin perder las herramientas (sirvieron y pueden volver a servir para
calibrar/depurar contra HybridLite).

## Current state

Directorio: `hybrid_writeback/` en `C:\Proyect\backend serrucho` (branch
`serrucho`).

**Archivos de PRODUCCIÓN — NO MOVER (keep-list exacta):**

```
flujo_precio.py          (base compartida: _find_hwnd, target PID, constantes de clase)
flujo_precio_real.py     (flujo de precio/costo con input real)
flujo_stock_real.py      (flujo de ajustes de stock)
flujo_compra_real.py     (flujo de compras + alta de producto)
abrir_hybrid.py          (auto-arranque/login/instancia aislada)
listener_writeback.py    (proceso 24/7, lo lanza backend_watchdog.py)
listener_compras.py      (proceso 24/7, lo lanza backend_watchdog.py)
listener_base.py         (si existe — lo crea el plan 018; si no existe, ignorar)
safety_control.py        (banner + F12 + mutex del mouse)
realinput.py             (motor de input real SendInput)
hybrid_price_writer.py   (lectura DBISAM + localización de campos)
read_db_existencia.py    (importado por listeners y flujos)
read_db_precio.py        (importado por hybrid_price_writer)
grabar_flujo.py          (herramienta de grabación usada con el dueño)
```

**A MOVER**: todo otro archivo `*.py` del directorio (≈55: `diag_*.py`,
`dbg_*.py`, `shot_*.py`, `odbc_*.py`, `dat_*.py`, `dump_*.py`, `find_*.py`,
`calibrar_*.py`, `click_aceptar.py`, `cerrar_ajuste.py`, `estado_ventanas.py`,
`inspect_hybrid.py`, `hybrid_ui.py` (módulo muerto, nadie lo importa),
`test_set_price.py`, `test_seleccion.py`, `read_price_fields.py`,
`_relanzar_hybrid.py`, `_inspeccionar_login.py`, `_estado_login.py`,
`_cerrar_ventanas.py`, `dbisam_write.py` (enfoque abandonado de parcheo crudo
del .DAT — el README del paquete lo lista como abandonado y nadie lo importa;
clasificado por el reviewer el 2026-07-12), `read_db_existencia.py` **NO** —
está en la keep-list, cuidado). La regla operativa es: **si está en la
keep-list queda, si no, se mueve**. No editar el contenido de ningún script movido.

**NO tocar**: `*.log`, `*.md`, `*.json`, `*.png`, `__pycache__/` ni cualquier
otro no-`.py`. Los `FLUJO-*.log` (grabaciones de coreografías) se quedan
donde están.

Notas de recon:
- pytest ignora `hybrid_writeback/` por config (`pytest.ini`:
  `--ignore=hybrid_writeback`), así que mover `test_*.py` no afecta la suite.
- `backend_watchdog.py` referencia solo `listener_writeback.py` y
  `listener_compras.py` por nombre — intactos.
- Los scripts movidos hacen `import flujo_precio ...` asumiendo que el módulo
  está en `sys.path[0]` (el dir del script). Tras moverse eso se rompe si se
  ejecutan directo: el README (Step 2) documenta cómo correrlos. NO les
  agregues shims de sys.path (son desechables; editar 55 archivos es churn).

## Commands you will need

| Purpose | Command (desde el worktree) | Expected on success |
|---------|------------------------------|---------------------|
| Import smoke producción | `cd hybrid_writeback && C:/Python314/python.exe -c "import flujo_precio, flujo_precio_real, flujo_stock_real, flujo_compra_real, abrir_hybrid, safety_control, realinput, hybrid_price_writer, read_db_existencia, read_db_precio, grabar_flujo, listener_writeback, listener_compras; print('OK')"` | `OK` |
| Suite | `C:/Python314/python.exe -m pytest -q` (raíz) | 47 passed |

## Scope

**In scope**:
- `hybrid_writeback/diagnostico/` (crear, con README.md)
- Los ~55 `.py` de la lista "A MOVER" (solo `git mv`, sin ediciones)

**Out of scope**:
- Cualquier edición al CONTENIDO de un archivo (movés, no modificás).
- La keep-list completa, los `.log`/`.md`/assets, `pytest.ini`,
  `backend_watchdog.py`.

## Git workflow

- Branch: `improve/020-mover-diagnostico`
- Un commit: `chore(writeback): mover scripts de diagnostico a hybrid_writeback/diagnostico/`
- Usar `git mv` para que queden como renames.
- NO push.

## Steps

### Step 1: Crear el directorio y mover

1. `mkdir hybrid_writeback/diagnostico`
2. Generar la lista efectiva: todos los `hybrid_writeback/*.py` que NO estén
   en la keep-list. Compararla contra la lista "A MOVER" del plan: debería
   rondar 55 archivos; si aparece un `.py` que no matchea ningún patrón
   mencionado y no está en la keep-list, STOP (archivo nuevo sin clasificar).
3. `git mv` de cada uno a `hybrid_writeback/diagnostico/`.

**Verify**: `git status --porcelain | grep -c "^R"` → ≈55 (todos renames), y
`ls hybrid_writeback/*.py | wc -l` → 13 o 14 (la keep-list; 14 si el plan 018
ya creó listener_base.py).

### Step 2: README del subdirectorio

Crear `hybrid_writeback/diagnostico/README.md` (en español) con:
- Qué es: scripts desechables de diagnóstico/calibración/exploración usados
  durante el desarrollo del write-back. No son producción; ninguno se importa
  desde los módulos de producción.
- Cómo ejecutar uno: desde `hybrid_writeback/`, con
  `$env:PYTHONPATH = (Get-Location); python diagnostico\<script>.py`
  (los scripts importan `flujo_precio` etc. esperando el paquete en el path).
- Advertencia: varios toman el mouse real o abren HybridLite; correr solo
  con supervisión y fuera de horario.

**Verify**: `test -f hybrid_writeback/diagnostico/README.md` → exit 0

### Step 3: Verificación integral

**Verify**:
1. Import smoke de producción (tabla de comandos) → `OK`
2. `C:/Python314/python.exe -m pytest -q` → 47 passed
3. `git status --porcelain` → solo renames hacia `diagnostico/` + el README
   nuevo; NINGÚN archivo de la keep-list modificado.

## Test plan

Sin tests nuevos. Los gates: import smoke de los 13-14 módulos de producción
y la suite de 47 tests intacta.

## Done criteria

- [ ] `ls hybrid_writeback/*.py` muestra exactamente la keep-list
- [ ] Import smoke `OK`
- [ ] `pytest -q` → 47 passed
- [ ] Todos los movimientos son renames de git (historial preservado)
- [ ] `diagnostico/README.md` existe con las 3 secciones

## STOP conditions

- Un `.py` fuera de la keep-list resulta estar importado por un módulo de
  producción (verificalo con
  `grep -l "import <nombre>" hybrid_writeback/*.py` antes de mover si tenés
  duda) — reportar, no mover.
- Aparece un `.py` nuevo no clasificado (posterior al recon).
- Cualquier verificación falla dos veces.

## Maintenance notes

- Los scripts nuevos de diagnóstico van DIRECTO a `diagnostico/`.
- Si algún día un diag "asciende" a producción, se mueve de vuelta y se
  agrega a la keep-list del README del paquete.
- Reviewer: chequear que ningún rename tocó contenido
  (`git diff --stat -M100%` debe mostrar 0 inserciones/borrados en los renames).
