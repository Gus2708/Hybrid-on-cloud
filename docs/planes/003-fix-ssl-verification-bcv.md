# Plan 003: Habilitar verificación SSL en el scraper BCV

> **Instrucciones al ejecutor**: Seguí este plan paso a paso. Ejecutá cada verificación antes de avanzar. Si alguna condición de STOP ocurre, detené y reportá. Al terminar, actualizá la fila en `plans/README.md`.
>
> **Drift check**: `git diff --stat cc62d24..HEAD -- rates_service.py`

## Status

- **Priority**: P1
- **Effort**: S
- **Risk**: LOW
- **Depends on**: none
- **Category**: security
- **Planned at**: commit `cc62d24`, 2026-06-20

## Por qué importa

`rates_service.py` usa `requests.get(..., verify=False)` para scrapear el BCV. Esto desactiva la verificación del certificado SSL, abriendo la puerta a un ataque Man-in-the-Middle donde alguien en la red local (o en el ISP) podría inyectar tasas de cambio falsas. Las tasas se guardan en Supabase y se usan para convertir todos los montos de ventas a USD — datos financieros reales.

El certificado de `www.bcv.org.ve` es emitido por una CA legítima y debería verificarse correctamente. La fix es remover `verify=False`.

## Estado actual

```python
# rates_service.py:20-25
def get_bcv_rates(self) -> Dict[str, float]:
    rates = {"USD": 0.0, "EUR": 0.0}
    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)..."
        }
        response = requests.get(self.BCV_URL, headers=headers, timeout=15, verify=False)
        #                                                                    ^^^^^^^^^^^
        #                                                                    ELIMINAR ESTO
```

## Comandos necesarios

| Propósito | Comando | Esperado |
|-----------|---------|----------|
| Verificar que BCV es alcanzable | `python -c "import requests; r = requests.get('https://www.bcv.org.ve/', timeout=10); print(r.status_code)"` | 200 |
| Tests | `python -m pytest tests/ -v` | Todos pasan |
| Verificar no hay verify=False | `Select-String -Path rates_service.py -Pattern "verify=False"` | Sin matches |

## Scope

**En scope**:
- `rates_service.py` — solo la llamada `requests.get()` en `get_bcv_rates()`

**Fuera de scope**:
- `get_binance_p2p_rate()` — ya usa POST sin `verify=False`
- Cualquier otro archivo

## Git workflow

- Branch: `advisor/003-fix-ssl-verification`
- Commit: `security: habilitar verificación SSL en scraper BCV`

## Pasos

### Paso 1: Verificar que el certificado BCV es válido desde esta máquina

```powershell
python -c "import requests; r = requests.get('https://www.bcv.org.ve/', timeout=10); print('OK:', r.status_code)"
```

Si este comando falla con `SSLError` → condición de STOP (ver abajo).
Si devuelve `OK: 200` → continuar.

### Paso 2: Eliminar `verify=False` de `get_bcv_rates()`

En `rates_service.py:24`, reemplazar:

```python
response = requests.get(self.BCV_URL, headers=headers, timeout=15, verify=False)
```

Por:

```python
response = requests.get(self.BCV_URL, headers=headers, timeout=15)
```

**Verificar**: `Select-String -Path rates_service.py -Pattern "verify=False"` → sin matches

### Paso 3: Verificar que el scraper funciona con SSL activado

```powershell
python -c "
from rates_service import RatesService
s = RatesService()
r = s.get_bcv_rates()
print('BCV USD:', r['USD'], 'EUR:', r['EUR'])
"
```

Esperado: imprime tasas numéricas > 0 sin errores.

**Verificar**: `python -m pytest tests/ -v` → todos pasan

## Plan de tests

No hay tests de `rates_service.py` actualmente. Si el plan 009 ya fue ejecutado, agregar este caso al archivo existente `tests/test_rates_service.py`:

```python
def test_bcv_scraping_no_verify_false(mocker):
    """El scraper BCV no desactiva verificación SSL."""
    import inspect, rates_service
    source = inspect.getsource(rates_service.RatesService.get_bcv_rates)
    assert "verify=False" not in source
```

Si el plan 009 no fue ejecutado aún, este test puede ir en `tests/test_rates_service.py` como primer contenido.

**Verificar**: `python -m pytest tests/test_rates_service.py -v` → pasa

## Criterios de done

- [ ] `Select-String -Path rates_service.py -Pattern "verify=False"` → sin matches
- [ ] `python -c "from rates_service import RatesService; r = RatesService().get_bcv_rates(); assert r['USD'] > 0"` → sin error (requiere conexión a internet y que el sitio BCV esté disponible)
- [ ] `python -m pytest tests/ -v` → todos pasan
- [ ] Solo `rates_service.py` fue modificado
- [ ] Fila en `plans/README.md` actualizada a DONE

## Condiciones de STOP

- El Paso 1 falla con `SSLError: CERTIFICATE_VERIFY_FAILED` → el certificado del BCV puede estar expirado o hay un proxy corporativo intercalado. En ese caso, investigar el certificado (no simplemente dejar `verify=False`). Una alternativa es descargar el certificado de la CA raíz y pasarlo con `verify="/ruta/al/ca-bundle.crt"`.
- El scraper devuelve `USD: 0.0` después de la fix → el sitio BCV puede haber cambiado su estructura HTML. Reportar como hallazgo separado.

## Notas de mantenimiento

- Si el BCV migra a un certificado autofirmado o rota el CA sin preaviso, este código fallará con SSLError. El mecanismo de fallback en `save_to_db()` usará la tasa anterior de la DB, lo que es el comportamiento correcto.
- No reintroducir `verify=False` aunque la verificación falle intermitentemente — investigar la causa raíz.
