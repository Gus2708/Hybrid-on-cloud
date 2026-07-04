# Plan 012: Investigar y resolver Bug #3 (total_bruto) y Bug #5 (timestamps) en ventas

> **Instrucciones al ejecutor**: Seguí este plan paso a paso. Este es un plan de investigación + fix. Ejecutá cada verificación antes de avanzar. Si alguna condición de STOP ocurre, detené y reportá. Al terminar, actualizá la fila en `plans/README.md`.
>
> **Drift check**: `git diff --stat cc62d24..HEAD -- sync_ventas.py`

## Status

- **Priority**: P2
- **Effort**: M
- **Risk**: MED
- **Depends on**: `plans/001-fix-get-current-rate-key-mismatch.md` (para tener la tasa correcta antes de testear montos)
- **Category**: bug
- **Planned at**: commit `cc62d24`, 2026-06-20

## Por qué importa

El código en `sync_ventas.py` tiene dos bugs auto-reportados con comentarios `# Bug #3` y `# Bug #5`. Estos han existido desde al menos el commit `e54033c` (hace ~3 semanas según el git log). Los datos de ventas en Supabase pueden tener `total_bruto` incorrecto y timestamps mal formateados.

Este plan primero investiga qué son exactamente Bug #3 y Bug #5, luego los corrige.

## Estado actual

```python
# sync_ventas.py:207-241 — map_venta() con los bugs marcados
def map_venta(row, fallback_rate):
    rif = row.get("THT_RIFCLIENTE", "").strip()
    
    tasa_doc = safe_decimal(row.get("THT_FACTORREFERENCIAL", 0))
    if tasa_doc <= 1.0: 
        tasa_doc = fallback_rate
    
    neto_ves = safe_decimal(row["THT_TOTALNETO"])
    imp_ves = safe_decimal(row.get("THT_TOTALIMPUESTO", 0))
    bruto_ves = safe_decimal(row.get("THT_TOTALBRUTO", 0))
    if bruto_ves == 0: bruto_ves = neto_ves - imp_ves    # ← SOSPECHOSO

    neto_usd = neto_ves / tasa_doc
    impuesto_usd = imp_ves / tasa_doc
    bruto_usd = bruto_ves / tasa_doc

    id_unico = to_int(row.get("THT_IDUNICO"))
    if id_unico == 0: id_unico = to_int(row["THT_AUTOINCREMENT"])

    return {
        ...
        "total_neto": round(neto_usd, 4),
        "total_impuesto": round(impuesto_usd, 4),
        "total_bruto": round(bruto_usd, 4),          # Bug #3
        "status": to_int(row["THT_STATUS"]),
        "numero_control": row["THT_NUMEROCONTROL"],
        "metodo_pago": row.get("METODO_PAGO", "EFECTIVO"),
        "created_at": row.get("FECHA_HORA_COMPLETA")  # Bug #5 (Time)
    }
```

**Hipótesis sobre Bug #3 (total_bruto)**:
- En Venezuela, el total bruto de una factura es `neto + impuesto` (IVA incluido)
- La fórmula actual cuando `THT_TOTALBRUTO == 0` es `bruto_ves = neto_ves - imp_ves` (neto MENOS impuesto), que daría el total sin IVA — posiblemente invertida
- Si HybridLite siempre tiene `THT_TOTALBRUTO` correctamente poblado, el fallback puede no importar. Necesita verificación con datos reales.

**Hipótesis sobre Bug #5 (timestamp)**:
- `row.get("FECHA_HORA_COMPLETA")` puede ser un campo que HybridLite no popula, retornando `None`
- O puede tener un formato que Supabase no acepta como timestamp ISO
- Si Supabase rechaza el formato, el insert falla silenciosamente o usa NULL

## Comandos necesarios

| Propósito | Comando | Esperado |
|-----------|---------|----------|
| Ver datos reales | `python -c "import csv; rows=list(csv.DictReader(open('VENTAS_CABECERA.csv',encoding='utf-8-sig'))); print(rows[0].keys())"` | Lista de columnas |
| Ver sample de datos | `python -c "import csv; rows=list(csv.DictReader(open('VENTAS_CABECERA.csv',encoding='utf-8-sig'))); [print(r.get('THT_TOTALBRUTO'), r.get('THT_TOTALNETO'), r.get('THT_TOTALIMPUESTO'), r.get('FECHA_HORA_COMPLETA')) for r in rows[:5]]"` | Valores reales |
| Tests | `python -m pytest tests/ -v` | Todos pasan |

## Scope

**En scope**:
- `sync_ventas.py` — solo la función `map_venta()`, específicamente las líneas marcadas
- `tests/test_sync_ventas.py` — crear o actualizar

**Fuera de scope**:
- Esquema de Supabase — no modificar la tabla `ventas` sin análisis previo
- Datos existentes en Supabase — no hacer migración de datos existentes (scope separado)

## Git workflow

- Branch: `advisor/012-fix-bug3-bug5-sales`
- Commit: `fix: corregir cálculo de total_bruto y formato de created_at en map_venta`

## Pasos

### Paso 1 (INVESTIGACIÓN): Examinar los datos reales del CSV

```powershell
python -c "
import csv
with open('VENTAS_CABECERA.csv', encoding='utf-8-sig') as f:
    rows = list(csv.DictReader(f))
    
print('Columnas disponibles:')
print(list(rows[0].keys()) if rows else 'CSV vacío')

print('\nPrimeras 5 filas — campos relevantes:')
for r in rows[:5]:
    print({
        'BRUTO': r.get('THT_TOTALBRUTO'),
        'NETO': r.get('THT_TOTALNETO'),
        'IMP': r.get('THT_TOTALIMPUESTO'),
        'FECHA_HORA': r.get('FECHA_HORA_COMPLETA'),
    })
"
```

**Análisis de Bug #3**: 
- Si `THT_TOTALBRUTO` siempre está poblado con valor > 0 → el fallback `bruto_ves = neto_ves - imp_ves` nunca se usa → riesgo bajo, pero la fórmula es incorrecta conceptualmente (debería ser `neto + imp`)
- Si `THT_TOTALBRUTO` frecuentemente es 0 → la fórmula errónea produce valores incorrectos

**Análisis de Bug #5**:
- Si `FECHA_HORA_COMPLETA` existe y tiene formato como `2024-01-15 14:30:00` → convertir a ISO 8601 (`2024-01-15T14:30:00`)
- Si `FECHA_HORA_COMPLETA` no existe (la columna no está en el CSV) → usar `THT_FECHAEMISION` como fallback

### Paso 2: Corregir Bug #3 — fórmula de total_bruto

Basado en el análisis del Paso 1:

**Caso A** (columna existe y poblada): mantener el uso de `THT_TOTALBRUTO` directo, corregir el fallback:
```python
bruto_ves = safe_decimal(row.get("THT_TOTALBRUTO", 0))
if bruto_ves == 0:
    bruto_ves = neto_ves + imp_ves  # bruto = neto + impuesto (corrección: era neto - imp)
```

**Caso B** (columna siempre 0 o no existe): calcular siempre:
```python
bruto_ves = neto_ves + imp_ves  # bruto = neto + IVA
```

Elegir el caso correcto según lo observado en Paso 1.

**Verificar**: `python -c "from sync_ventas import safe_decimal; print(100 + 16)"` → `116` (sanity check conceptual)

### Paso 3: Corregir Bug #5 — formato de timestamp

```python
# Antes:
"created_at": row.get("FECHA_HORA_COMPLETA")  # Bug #5 (Time)

# Después (si la columna existe con formato "YYYY-MM-DD HH:MM:SS"):
def _parse_timestamp(val):
    if not val:
        return None
    try:
        # Convertir "2024-01-15 14:30:00" a "2024-01-15T14:30:00"
        return str(val).replace(" ", "T") if val else None
    except Exception:
        return None

# En el dict de retorno:
"created_at": _parse_timestamp(row.get("FECHA_HORA_COMPLETA"))
```

Si la columna no existe en el CSV, usar `THT_FECHAEMISION`:
```python
"created_at": _parse_timestamp(row.get("FECHA_HORA_COMPLETA") or row.get("THT_FECHAEMISION"))
```

**Verificar**: `python -c "from sync_ventas import map_venta; print('OK')"` → OK (verificar que la función importa sin error)

### Paso 4: Agregar tests

Crear o actualizar `tests/test_sync_ventas.py`:

```python
def test_map_venta_calculo_bruto_correcto():
    """total_bruto es neto + impuesto cuando THT_TOTALBRUTO es 0."""
    from sync_ventas import map_venta
    row = {
        "THT_TOTALNETO": "100",
        "THT_TOTALIMPUESTO": "16",
        "THT_TOTALBRUTO": "0",  # Caso donde el fallback se activa
        "THT_FACTORREFERENCIAL": "55.5",
        "THT_IDUNICO": "123",
        "THT_AUTOINCREMENT": "123",
        "THT_DOCUMENTO": "00001234",
        "THT_FECHAEMISION": "2024-01-15",
        "THT_STATUS": "1",
        "THT_NUMEROCONTROL": "NC001",
        "THT_RIFCLIENTE": "J123",
    }
    result = map_venta(row, 55.5)
    # Con tasa 55.5 Bs/USD: neto=100/55.5, imp=16/55.5, bruto=116/55.5
    expected_bruto = round(116 / 55.5, 4)
    assert result["total_bruto"] == expected_bruto

def test_map_venta_timestamp_formato_iso():
    """created_at se formatea como ISO 8601 si la columna existe."""
    from sync_ventas import map_venta
    row = {
        "THT_TOTALNETO": "100",
        "THT_TOTALIMPUESTO": "16",
        "THT_TOTALBRUTO": "116",
        "THT_FACTORREFERENCIAL": "55.5",
        "THT_IDUNICO": "123",
        "THT_AUTOINCREMENT": "123",
        "THT_DOCUMENTO": "00001234",
        "THT_FECHAEMISION": "2024-01-15",
        "THT_STATUS": "1",
        "THT_NUMEROCONTROL": "NC001",
        "THT_RIFCLIENTE": "",
        "FECHA_HORA_COMPLETA": "2024-01-15 14:30:00"
    }
    result = map_venta(row, 55.5)
    assert result["created_at"] == "2024-01-15T14:30:00"
```

**Verificar**: `python -m pytest tests/test_sync_ventas.py -v` → pasan

## Criterios de done

- [ ] El comentario `# Bug #3` fue eliminado y la lógica es correcta (con test que lo verifica)
- [ ] El comentario `# Bug #5 (Time)` fue eliminado y el timestamp tiene formato ISO 8601
- [ ] `python -m pytest tests/ -v` → todos pasan, incluyendo los nuevos tests de `map_venta`
- [ ] Solo `sync_ventas.py` y archivos de test fueron modificados
- [ ] Fila en `plans/README.md` actualizada a DONE

## Condiciones de STOP

- El Paso 1 muestra que `FECHA_HORA_COMPLETA` no existe como columna en el CSV → reportar y adaptar el plan (usar `THT_FECHAEMISION` en su lugar)
- El Paso 1 muestra que `THT_TOTALBRUTO` siempre está correctamente poblado y el fallback nunca se usa → la fix de Bug #3 puede ser solo remover el comentario y documentar que el fallback se mantiene por seguridad con la fórmula corregida

## Notas de mantenimiento

- Si HybridLite cambia el formato de las fechas en `FECHA_HORA_COMPLETA`, la función `_parse_timestamp` necesita actualizarse
- Los totales en Supabase existentes **no son corregidos automáticamente** por esta fix — los registros ya sincronizados mantienen los valores incorrectos. Si se requiere corrección retroactiva, es un data migration separado.
