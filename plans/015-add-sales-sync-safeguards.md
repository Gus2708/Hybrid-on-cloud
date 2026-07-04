# Plan 015: Agregar salvaguardas de calidad a la sincronización de ventas

> **Instrucciones al ejecutor**: Seguí este plan paso a paso. Ejecutá cada verificación antes de avanzar. Si alguna condición de STOP ocurre, detené y reportá. Al terminar, actualizá la fila en `plans/README.md`.
>
> **Drift check**: `git diff --stat cc62d24..HEAD -- sync_ventas.py sync.py`

## Status

- **Priority**: P2
- **Effort**: S
- **Risk**: LOW
- **Depends on**: none
- **Category**: direction
- **Planned at**: commit `cc62d24`, 2026-06-20

## Por qué importa

`sync.py` (inventario) tiene salvaguardas de calidad de datos que `sync_ventas.py` no tiene:

| Salvaguarda | `sync.py` (inventario) | `sync_ventas.py` (ventas) |
|-------------|------------------------|---------------------------|
| Abortar si >50% precio=0 | ✅ línea 199-201 | ❌ ausente |
| Umbral para borrar huérfanos | ✅ 10% (línea 258) | ✅ 5% (línea 506) — diferente |
| Mensajes claros de abort | ✅ con conteos | ❌ más silencioso |

Si el CSV de ventas se trunca o corrompe (H: se cae a mitad de escritura), las ventas se podrían sincronizar con precios 0, o valores inválidos podrían llegar a Supabase.

## Estado actual

```python
# sync.py:196-202 — salvaguarda de precio 0 en inventario
if len(to_upsert) >= 500:
    # Salvaguarda: si mas del 50% de lo procesado tiene precio 0, abortar
    if total_count > 100 and zero_price_count > total_count * 0.5:
        print(f"[SYNC] ! ABORTANDO: {zero_price_count}/{total_count} productos con precio 0. Posible error de lectura.")
        error_occurred = True
        break
    
    print(f"  -> Upsert batch {len(to_upsert)}...")
    if upsert_batch_rest(to_upsert): to_upsert = []
```

```python
# sync_ventas.py:179-193 — validación de CSV mínima en ventas
def validate_csv(path, min_rows=5):
    if not os.path.exists(path):
        print(f"  [SKIP] {path} no existe.")
        return False
    try:
        with open(path, "r", encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            rows = list(reader)
            if len(rows) < min_rows:
                print(f"  [SKIP] {path} tiene solo {len(rows)} filas (< {min_rows}). Posible truncado.")
                return False
            return True
    except Exception as e:
        print(f"  [ERROR] {path} corrupto: {e}")
        return False
```

La validación actual de ventas solo chequea si el CSV existe y tiene 5+ filas. No hay chequeo de calidad de los valores.

## Comandos necesarios

| Propósito | Comando | Esperado |
|-----------|---------|----------|
| Tests | `python -m pytest tests/ -v` | Todos pasan |
| Verificar sintaxis | `python -c "import ast; ast.parse(open('sync_ventas.py').read()); print('OK')"` | OK |

## Scope

**En scope**:
- `sync_ventas.py` — agregar validación de calidad en `sync_incremental()` para la cabecera de ventas

**Fuera de scope**:
- `sync.py` — no modificar (ya tiene las salvaguardas)
- La lógica de reconciliación/orphan deletion — ya tiene su propio umbral

## Git workflow

- Branch: `advisor/015-add-sales-sync-safeguards`
- Commit: `feat: agregar salvaguarda de precio=0 en sincronización de ventas`

## Pasos

### Paso 1: Agregar contadores de calidad en el procesamiento de ventas

En `sync_ventas.py`, dentro del bloque `if validate_csv("VENTAS_CABECERA.csv"):`, agregar contadores de calidad después del `for row in csv.DictReader(f):`:

```python
# Contadores de calidad (agregar al inicio del bloque de ventas)
total_ventas_count = 0
zero_total_count = 0
```

En el loop de procesamiento de ventas (dentro del `for row in csv.DictReader(f):`), agregar después de `mapped = map_venta(row, current_bcv_rate)`:

```python
total_ventas_count += 1
if mapped.get("total_neto", 0) == 0.0:
    zero_total_count += 1
```

En el bloque de upsert por lotes (cuando `len(to_upsert) >= 500`), agregar antes del upsert:

```python
# Salvaguarda: si >50% de ventas procesadas tienen total_neto=0, abortar
if total_ventas_count > 50 and zero_total_count > total_ventas_count * 0.5:
    print(f"[SYNC VENTAS] ! ABORTANDO: {zero_total_count}/{total_ventas_count} ventas con total_neto=0. "
          f"Posible error de lectura o tasa 0. Verificar CSV.")
    return
```

**Verificar**: `python -c "import ast; ast.parse(open('sync_ventas.py').read()); print('OK')"` → OK

### Paso 2: Unificar el umbral de orphan deletion

El inventario usa 10% y las ventas usan 5%. Documentar o unificar. Para este plan, documentar el 5% con un comentario:

```python
# Salvaguarda: no eliminar si >5% del cloud son huérfanos (conservador para ventas — datos financieros)
if total_cloud > 100 and len(orphans) > 200 and (len(orphans) / total_cloud) > 0.05:
```

Agregar el comentario explicativo si no está.

**Verificar**: `python -m pytest tests/ -v` → todos pasan

## Plan de tests

Si existe `tests/test_sync_ventas.py` (del plan 012), agregar:

```python
def test_ventas_sync_aborta_si_demasiados_ceros(mocker):
    """sync_incremental aborta si >50% de ventas tienen total_neto=0."""
    # Mock que devuelve ventas con total_neto=0
    # ... (adaptar según estructura del test suite existente)
    pass  # Dejar como placeholder si el test suite de ventas no existe aún
```

## Criterios de done

- [ ] `sync_ventas.py` tiene contadores `total_ventas_count` y `zero_total_count`
- [ ] Si >50% de ventas procesadas tienen `total_neto=0`, se aborta con mensaje claro
- [ ] `python -m pytest tests/ -v` → todos pasan
- [ ] Solo `sync_ventas.py` fue modificado
- [ ] Fila en `plans/README.md` actualizada a DONE

## Condiciones de STOP

- En los datos reales, hay una proporción alta de ventas con total_neto=0 por motivos legítimos (ej: ventas de cortesía, descuentos totales) → ajustar el umbral al 80% o no aplicar esta salvaguarda para ventas, solo para cabecera/detalle

## Notas de mantenimiento

- El umbral 50% es igual al de inventario. Si el negocio tiene una proporción natural de ventas con importe cero (cortesías, cambios), ajustar el umbral
