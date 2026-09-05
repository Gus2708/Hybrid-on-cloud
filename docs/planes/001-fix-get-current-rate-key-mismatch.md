# Plan 001: Corregir claves rotas en `get_current_rate()` — ventas siempre usan tasa 489.55

> **Instrucciones al ejecutor**: Seguí este plan paso a paso. Ejecutá cada comando de verificación antes de pasar al siguiente. Si alguna condición de STOP ocurre, detené la ejecución y reportá. Al terminar, actualizá la fila de este plan en `plans/README.md`.
>
> **Drift check (ejecutar primero)**:
> `git diff --stat cc62d24..HEAD -- sync_ventas.py rates_service.py`
> Si alguno de esos archivos cambió, comparar los excerpts de "Estado actual" con el código real antes de continuar.

## Status

- **Priority**: P1
- **Effort**: S
- **Risk**: LOW
- **Depends on**: none
- **Category**: bug
- **Planned at**: commit `cc62d24`, 2026-06-20

## Por qué importa

`get_current_rate()` en `sync_ventas.py` intenta leer las claves `"bcv"` y `"binance"` del dict que devuelve `RatesService.get_all_rates()`, pero ese dict tiene claves `"bcv_usd"` y `"binance_p2p"`. Ambas lookups devuelven `None`, y el valor final siempre cae al default hardcodeado `FACTOR_USD_DEFAULT = 489.55`.

Esto significa que **toda venta cuyo campo `THT_FACTORREFERENCIAL` sea 0 o ≤ 1.0 se convierte a USD usando 489.55 Bs/USD**, ignorando completamente la tasa BCV del momento. En Venezuela, donde la tasa cambia diariamente, los montos en Supabase pueden estar significativamente equivocados.

La corrección es un one-liner: cambiar las dos claves en `get_current_rate()` para que coincidan con lo que realmente devuelve `get_all_rates()`.

## Estado actual

Archivo: [`sync_ventas.py`](../sync_ventas.py)

```python
# sync_ventas.py:113-124
FACTOR_USD_DEFAULT = 489.55

def get_current_rate():
    try:
        from rates_service import RatesService
        service = RatesService()
        rates = service.get_all_rates()
        # Intentar obtener BCV primero, luego Binance
        return rates.get("bcv", rates.get("binance", FACTOR_USD_DEFAULT))
    except:
        return FACTOR_USD_DEFAULT
```

Archivo: [`rates_service.py`](../rates_service.py)

```python
# rates_service.py:81-94 — lo que realmente devuelve get_all_rates()
def get_all_rates(self) -> Dict[str, float]:
    bcv = self.get_bcv_rates()
    binance = self.get_binance_p2p_rate()
    return {
        "bcv_usd": bcv["USD"],      # ← clave real
        "bcv_eur": bcv["EUR"],
        "binance_p2p": binance,     # ← clave real
        "timestamp": time.time()
    }
```

La discrepancia:
- Se busca `"bcv"` → la clave real es `"bcv_usd"`
- Se busca `"binance"` → la clave real es `"binance_p2p"`

## Comandos necesarios

| Propósito | Comando | Esperado en éxito |
|-----------|---------|-------------------|
| Ejecutar tests | `python -m pytest tests/ -v` | Todos pasan |
| Test específico de tasas | `python -m pytest tests/test_rates_service.py -v` | Todos pasan (si el archivo existe) |
| Verificar importación | `python -c "from sync_ventas import get_current_rate; print(get_current_rate)"` | Sin errores de importación |

## Scope

**En scope** (solo estos archivos):
- `sync_ventas.py` — corregir `get_current_rate()`

**Fuera de scope** (NO tocar):
- `rates_service.py` — las claves son correctas ahí, ese no es el bug
- `sync.py` — no usa `get_current_rate()`
- Cualquier otra cosa

## Git workflow

- Branch: `advisor/001-fix-rate-key-mismatch`
- Commit: `fix: corregir claves de tasa en get_current_rate (bcv→bcv_usd, binance→binance_p2p)`

## Pasos

### Paso 1: Corregir las claves en `get_current_rate()`

En `sync_ventas.py`, línea 122, reemplazar:

```python
return rates.get("bcv", rates.get("binance", FACTOR_USD_DEFAULT))
```

Por:

```python
return rates.get("bcv_usd", rates.get("binance_p2p", FACTOR_USD_DEFAULT))
```

**Verificar**: `python -c "import ast, sys; ast.parse(open('sync_ventas.py').read()); print('OK')"` → imprime `OK`

### Paso 2: Agregar comentario explicativo

Actualizar el comentario en la línea anterior para que sea claro:

```python
# Intentar obtener BCV USD primero, luego Binance P2P como fallback
return rates.get("bcv_usd", rates.get("binance_p2p", FACTOR_USD_DEFAULT))
```

**Verificar**: `python -m pytest tests/ -v` → todos los tests pasan

## Plan de tests

Crear `tests/test_rates_service.py` (si no existe) con al menos estos casos:

```python
def test_get_current_rate_uses_bcv_usd(mocker):
    """get_current_rate devuelve bcv_usd cuando BCV scraping funciona."""
    mocker.patch("sync_ventas.RatesService.get_all_rates", return_value={
        "bcv_usd": 55.5, "bcv_eur": 60.0, "binance_p2p": 56.0, "timestamp": 0
    })
    from sync_ventas import get_current_rate
    assert get_current_rate() == 55.5

def test_get_current_rate_fallback_to_binance(mocker):
    """Si bcv_usd es 0, cae a binance_p2p."""
    mocker.patch("sync_ventas.RatesService.get_all_rates", return_value={
        "bcv_usd": 0.0, "bcv_eur": 0.0, "binance_p2p": 56.0, "timestamp": 0
    })
    from sync_ventas import get_current_rate
    # bcv_usd = 0.0 es falsy pero .get() devuelve el valor, no lo evalúa
    # Esto documenta el comportamiento actual: 0.0 se devuelve como-es
    result = get_current_rate()
    assert result == 0.0 or result == 56.0  # Ajustar según comportamiento deseado

def test_get_current_rate_fallback_to_default_on_exception(mocker):
    """Si RatesService falla, devuelve FACTOR_USD_DEFAULT."""
    mocker.patch("sync_ventas.RatesService", side_effect=Exception("network error"))
    from sync_ventas import get_current_rate
    assert get_current_rate() == 489.55
```

**Verificar**: `python -m pytest tests/test_rates_service.py -v` → mínimo el primer y tercer test pasan

## Criterios de done

- [ ] `sync_ventas.py:122` contiene `"bcv_usd"` y `"binance_p2p"` (no `"bcv"` ni `"binance"`)
- [ ] `python -m pytest tests/ -v` → todos pasan
- [ ] `grep -n '"bcv"' sync_ventas.py` → no devuelve línea 122 (ninguna match en get_current_rate)
- [ ] Solo `sync_ventas.py` fue modificado (`git diff --name-only`)
- [ ] Fila del plan en `plans/README.md` actualizada a DONE

## Condiciones de STOP

Detener y reportar si:
- El código en `sync_ventas.py:122` no coincide con el excerpt de "Estado actual" (drift)
- `rates_service.get_all_rates()` fue modificado y ya no devuelve `"bcv_usd"` (la fix es en el lugar equivocado)
- Los tests existentes rompen por la modificación

## Notas de mantenimiento

- Si `RatesService.get_all_rates()` alguna vez cambia las claves de retorno, `get_current_rate()` debe actualizarse en sincronía
- El test `test_get_current_rate_fallback_to_binance` documenta un edge case: `bcv_usd=0.0` se devuelve como 0.0 (el dict.get() no evalúa falsiness). Si el comportamiento correcto es saltar a binance_p2p cuando bcv_usd=0, agregar `if result else rates.get("binance_p2p", FACTOR_USD_DEFAULT)`
