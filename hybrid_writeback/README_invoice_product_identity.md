# Strict product identity for invoice-origin purchases

Opt-in path in `flujo_compra_real.py` that makes sure a product created from a supplier
invoice is stored with exactly the identity the app prepared. Default manual / CLI
behavior is unchanged: nothing below applies unless `identidad_estricta=True` is passed.

## Policy (from the app, not inverted here)

| Hybrid field | Value |
| --- | --- |
| Código (`PRD_CODIGO`) | scanned physical barcode (`codigo` of the item) |
| Referencia (`PRD_REFERENCIA`) | effective printed invoice supplier code (`referencia`) |
| Descripción (`PRD_DESCRIPCION`) | item description |

Values are literal: leading zeros, case and punctuation are kept. Nothing is trimmed,
coerced or truncated; an unsupported value is rejected before anything is touched.
The reference may be missing (`None` or `""`) and is then expected to stay empty.

## What the strict path does

`registrar_compra(..., identidad_estricta=True)`, only for items with `es_nuevo`:

1. **Validate** each identity (`invoice_product_identity.validar_identidad`): code
   1-80 chars, reference up to 100, description required, `str` only, no outer
   whitespace, no control characters, and not the catalog sentinel `Fail` (the catalog
   reader cannot represent it). Failure: stage `navegacion`, nothing touched.
2. **Verify what already exists** with one *fresh* catalog read
   (`colisiones.catalogo_fresco`, bypasses the mtime cache), before opening Hybrid:
   - code absent: it will be created;
   - code present with the exact expected reference and description: treated as
     already created (retry after a failed purchase), not re-created;
   - code present with another reference/description, or only under another
     capitalization: fail closed (stage `navegacion`, "Nada se tocó"), no product is
     overwritten and **no** alta runs for any item of the purchase;
   - catalog unreadable: fail closed.
3. **Create** with `crear_producto(..., identidad_estricta=True)`: code, reference and
   description must read back on screen exactly as typed. A missing Referencia control
   or any difference stops before saving (stage `campos`, Ficha discarded). Costs and
   prices keep their existing numeric checks and tolerances.
4. **Read back after saving**: `colisiones.identidad` (fresh read, never the cached
   catalog) is polled with the existing `REINTENTOS_LECTURA_DB` / `ESPERA_LECTURA_DB`
   bound to absorb DBISAM read-after-save lag. It only reads: it never saves or
   creates again.

Result stages (existing names; listener mapping below):

| Situation | Stage | Meaning |
| --- | --- | --- |
| Identity read back exactly | `commit` | alta saved and identity verified |
| Not found / fields differ after the bounded reads | `verificacion_db` (`alta_producto:verificacion_db` inside a purchase) | ambiguous: the save was pressed; purchase is cancelled, nothing is re-saved |
| Catalog unreadable after saving | `verificacion_indisponible` | save was pressed, identity not verified |
| Numeric read unavailable | `verificacion_indisponible` | as before, plus "identidad no verificada" |

Messages name fields (`codigo`, `referencia`, `descripcion`), never the invoice values.

**Preview** (`commit=False`) never saves and never reads the catalog for proof. Its
result says the identity was verified on screen only, "sin prueba de persistencia en DB".

## Known limits

- The check proves what the catalog reader (`TInventario.dat`) returns after the bounded
  reads; it does not prove Hybrid's own screens, kardex or other tables.
- The existing code/reference interception pre-flight (`colisiones.revisar_lote`) still
  runs after the alta, as before.
- `ESPERA_LECTURA_DB` (20 s) x `REINTENTOS_LECTURA_DB` (3) bounds the lag wait; a longer
  lag is reported as not verified, never retried by saving again.

## Invoice-origin detection (`listener_compras.py`)

`procesar_compra` asks the app for the canonical origin of every queued purchase **before
any Hybrid/UI effect** (before the safety overlay and `registrar_compra`):

```
POST <existing Supabase URL>/rest/v1/rpc/es_compra_de_factura   {"p_compra_id": <positive int>}
```

It uses the existing `listener_base.rest` transport (same server credentials, 30 s
timeout) with the new optional `expected_status=200`, and the app contract in
`docs/INVOICE-WRITEBACK-ORIGIN.md` (migration `20261120210740_invoice_writeback_origin.sql`).
The binding table is never read and the origin is never inferred from title, note or
document number. Only a literal HTTP 200 **and** an exact JSON boolean count.

| Answer | Behavior |
| --- | --- |
| exact JSON `true` | `registrar_compra(..., identidad_estricta=True)` |
| exact JSON `false` | the same call as always (no new kwarg): manual/default behavior |
| anything else: non-positive or non-`int` id, HTTP error (401/403/404/500, `22023`, `P0002`), timeout, network error, malformed JSON, `null`, string, number, list, object | **fail closed**: stage `origen_desconocido`, Hybrid untouched, never run as manual |

`origen_desconocido` is in `ETAPAS_REINTENTABLES` (nothing was touched, so retrying is
safe) and ends in `error` after `MAX_INTENTOS`, with the failure category (for example
`HTTP 403` or `HTTP 201 en lugar de 200`) visible in `backend_resultado`; raw bodies and
error text are never stored.

`listener_base.rest(..., expected_status=None)`: the default keeps every existing caller
exactly as before (any 2xx, JSON/empty body, errors propagate). With `expected_status=N`
a different status raises `RestStatusInesperado` (code only, no body or credentials)
before the body is read or parsed, so a 201/202/204 carrying `true`/`false` is rejected.
Only the origin lookup passes the keyword.

Strict-mode result policy (`_politica_resultado(res, intentos, estricto=...)`):

- failures before anything is saved (`navegacion` conflicts or unreadable catalog,
  `alta_producto:campos`, ...) keep the existing retryable policy;
- `alta_producto:verificacion_db` (alta saved, fresh read-back does not match or the
  product is not found) is an immediate `error`, keeps the original detail and adds
  "NO reintentar ni recrear"; the purchase is never loaded because `registrar_compra`
  cancels before buying;
- `alta_producto:verificacion_indisponible` and every other stage follow the old policy;
- without the strict flag (manual purchases) every stage behaves exactly as before.

**Deployment order.** Apply and verify the app migration first, then deploy this backend.
With this backend and no RPC available, the origin check fails closed for **every**
purchase, manual ones included, until the RPC exists. The lookup is a snapshot: it does
not authorize product creation or emission and says nothing about a later Hybrid write.
Imported linked-purchase emission is not enabled by this change.

## Tests

```
python -m unittest discover -s hybrid_writeback/tests -p test_invoice_product_identity.py -v
python -m unittest discover -s hybrid_writeback/tests -p test_listener_invoice_origin.py -v
python -m unittest discover -s hybrid_writeback/tests -p test_listener_base_rest_status.py -v
```

Standard-library `unittest`; the listener tests fake `listener_base` and the REST transport before importing the listener; the status tests import the real `listener_base` with a fake `config` and a fake `urlopen`. All UI, DBISAM, network and session effects are fakes and
the catalog is synthetic. No real `.dat`, window or credential is used.
