# Write-back: editar PRECIO y STOCK en HybridLite desde el backend

Permite que, desde la app / el bot, se solicite un cambio de **precio** o **stock** y que
el backend lo aplique en el sistema local HybridLite **sin corromper la base de datos**.

> **Estado (2026-07-09):** ✅ **Precio y Stock FUNCIONAN**, verificados leyendo la DB
> real (pydbisam). Falta únicamente **cablear el pipeline** (listener + tabla en Supabase)
> para que la app dispare los cambios sola.

---

## TL;DR — cómo se usa hoy

```powershell
cd "C:\Proyect\backend serrucho\hybrid_writeback"

# PRECIO (USD, "precio con impuesto"). Sin --commit = preview y descarta.
python flujo_precio_real.py <codigo> <precio> [--commit]

# STOCK (ajuste por conteo físico, kardex-safe). Sin --commit = preview + Cancelar.
python flujo_stock_real.py <codigo> <cantidad> [--commit] [--delta]
```

Ambos flujos **abren y loguean HybridLite solos** si está cerrado (`abrir_hybrid.py`),
navegan la app con **input real de hardware** y **verifican el resultado contra la DB**.

Producto de prueba seguro: `00-002-024` (restaurar su valor tras probar).

---

## Por qué NO se editan los archivos `.Dat` directamente

HybridLite usa **DBISAM 4**, no archivos planos. La estación (`C:\HybridLiteEstacion`)
abre los `.Dat` en **modo archivo-compartido** sobre `\\PRINCIPAL\Happs` (mapeado a `H:`;
`SERVERREMOTO=0` en `HybridLite.ini`). Editar esos archivos a mano es inviable y peligroso:

| Obstáculo | Detalle |
|---|---|
| Librería de solo lectura | `pydbisam` decodifica; no escribe. |
| Checksums | Cada tabla tiene MD5 y cada fila un checksum de 16 bytes (algoritmo no documentado). |
| Índices `.Idx` / BLOBs `.Blb` | B-trees y campos largos separados que deben quedar consistentes. |
| Acceso multiusuario | Otras estaciones tienen los archivos abiertos → escribir por debajo = corrupción segura. |

**Conclusión:** la escritura segura debe pasar **por el motor**. Sin licencia del driver
ODBC de DBISAM, el único motor operable es la **propia app HybridLite**.

---

## El descubrimiento clave: INPUT REAL, no sintético

`pywinauto` (input sintético) **NO sirve** aquí: la app rechaza el input sintético en los
disparadores de carga de datos (la Búsqueda responde *"Database name is missing"*, la grilla
sale vacía). La solución que **sí funciona** es automatizar la app con **input real de
hardware vía `SendInput`** — se comporta exactamente igual que un humano.

- El código se teclea con Unicode (`type_text`, conserva guiones).
- Los **números de precio** se teclean por el **teclado numérico** (VK_DECIMAL `0x6E`);
  la coma/punto como texto Unicode la app la ignora.
- Los **códigos con guion** en la grilla de stock usan la tecla `-` del numpad (VK_SUBTRACT `0x6D`).

---

## Archivos (los que funcionan, en negrita)

| Archivo | Rol |
|---|---|
| **`realinput.py`** | **Motor de input real** (clic/tecla de hardware, `type_number`, `type_code`, `clear_hard`). |
| **`flujo_precio_real.py`** | **PRECIO.** `set_precio(codigo, target, commit=)`. Preview por defecto; verifica contra DBISAM. |
| **`flujo_stock_real.py`** | **STOCK.** `cargar_y_fijar` / `ajustar_stock`. Ajuste por conteo físico. CLI arriba. |
| **`abrir_hybrid.py`** | **Auto-arranque + login** (`asegurar_hybrid()`, credenciales en `hybrid_login.json`). Integrado a ambos flujos. |
| `read_db_precio.py` / `read_db_existencia.py` | Lectura de verificación (pydbisam) del precio / la existencia real. |
| `grabar_flujo.py` | Grabador del flujo manual (hooks de mouse/teclado) usado para capturar las secuencias del dueño. |
| `calib_puntos.json` | Coordenadas calibradas por hover (menú Inventario, botón Modificar, Guardar). |
| `listener_writeback.py` | (Pipeline, **pendiente de cablear**) sondea Supabase y despacha al escritor. |
| `schema.sql` | Crea la tabla `cambios_solicitados` en Supabase (**pendiente de ejecutar**). |
| `hybrid_ui.py`, `flujo_precio.py`, `odbc_*.py`, `dbisam_write.py`, `diag_*`, `shot_*` | **Enfoques abandonados / diagnóstico** (pywinauto sintético, ODBC, parcheo crudo). No usar para producción. |

---

## Secuencias exactas (grabadas del dueño)

### PRECIO — seguro, se puede previsualizar y descartar
1. Items de Inventario → **Modificar** (barra owner-drawn de la Ficha) → abre Búsqueda.
2. Teclear el código en `Ed_Buscar` → **ENTER** ejecuta la búsqueda (**FILTRA** al código
   exacto: queda "Registros: 1", así el ENTER de selección carga siempre el correcto).
3. **ENTER** selecciona la fila → **Costos y Precios** → diálogo `TFHCostosPrecios`.
4. Campo correcto = **"Precio con impuesto"** del panel `POtrasMonedas` (DÓLARES) =
   registro TIPO=1 `TPC_PVPCONIMPUESTO1`. Enfocar, **borrar duro** (END + backspaces),
   teclear por numérico. Al ENTER la app recalcula sola el sin-impuesto y el precio en Bs.
5. **Commit:** **Aceptar → Salir → Guardar → Confirm "&Yes"**. (Salir sin Aceptar descarta.)

### STOCK — documento PERMANENTE del kardex (⚠ no se puede descartar)
Ventana `TFormHTransaccion_Ajustes` ("Transacciones: AJUSTES"), desde menú Inventario →
**"Ajustes de inventario"**. Es un **ajuste por CONTEO físico** (respeta kardex): la columna
**Conteo** es el valor absoluto deseado; `Diferencia = Conteo − Existencia` se aplica al Totalizar.

El **truco del posteo** (lo que costó descubrir): clic en celda **Código** → teclear el
código **LENTO** (si no, el autocompletado abre una búsqueda que bloquea) → **ENTER** (el
cursor **salta solo a Conteo**) → teclear la cantidad **DIRECTO** (reemplaza el auto-relleno
= existencia) → **ENTER** (confirma) + **ENTER** (postea la fila). **Verificar el valor
ANTES del 2º ENTER** (tras postear la fila se vuelve estática e ilegible).

- **Commit:** `&Totalizar` → confirmación `TFConfirmacion &SI` → se genera un **comprobante
  impreso** `TfrxPreviewForm` que **hay que cerrar con foco + ESC** (si queda abierto BLOQUEA
  la siguiente operación).
- **Preview** (sin `--commit`) = llenar código + conteo y **Cancelar** (no genera documento).
- Revertir un ajuste real exige **otro** documento de ajuste. Probar con MUCHO cuidado.

---

## Restricciones duras (no negociables)

- **NUNCA** parchear los `.Dat` a mano ni por ODBC Local sobre el share.
- **Precio** = campo maestro (`TPC_PVPCONIMPUESTO1`, USD), seguro de escribir por el motor.
- **Stock** NUNCA como UPDATE crudo al saldo (`TExistenciaInv.EIN_EXISTENCIA`): Hybrid
  calcula la existencia por kardex/movimientos/depósito. Debe hacerse como **documento de
  ajuste** por la app.
- **Un cambio a la vez, supervisado.** El input real toma el mouse/teclado ~30s por cambio
  → correr **fuera de horario** o en sesión aparte. Nada de escritura masiva.

---

## Pruebas verificadas

| Qué | Resultado |
|---|---|
| Precio | `00-002-024` 12.0 → 13.5 → 12.0 (restaurado), leyendo `TPC_PVPCONIMPUESTO1`. |
| Stock | `00-002-024` 1 → 3 → 1 (restaurado), leyendo `EIN_EXISTENCIA`. |
| Selección | 5 códigos de distintas posiciones cargaron el producto correcto. |
| Auto-arranque | cerrar → auto-abrir → login (SU/SU) → navegar → preview, sin intervención. |

---

## Pipeline real: Orden de Cambio (app El Serrucho Go) → HybridLite

**(2026-07-09)** El pipeline queda enganchado a lo que la app **ya hace hoy**, en vez
de a una tabla nueva: cuando alguien arma un ajuste de stock en El Serrucho Go y lo
emite, `useOrdenCambio.ts` inserta un header en `ordenes_cambio` (`status: 'emitido'`)
y un item por producto en `ordenes_cambio_items` (`codigo_producto`,
`existencia_actual`, `nueva_existencia`, y `delta` **generado por Postgres** =
`nueva_existencia - existencia_actual`). Hoy eso solo genera un PDF para aplicar a
mano; `listener_writeback.py` ahora también lo aplica solo en HybridLite.

- Migraciones **EJECUTADAS en Supabase (2026-07-09)**, viven en el repo de la app:
  - `018_ordenes_cambio_items_backend_status.sql`: agrega `backend_status` /
    `backend_resultado` / `backend_intentos` / `backend_aplicado_en` a
    `ordenes_cambio_items` (no toca el flujo existente de la app).
  - `019_backend_status_backfill_completado.sql`: deja el vocabulario de estados en
    **`pendiente` / `aplicando` / `error` / `completado`** (ya no existe `aplicado`)
    e hizo el **backfill de seguridad**: los 6471 items históricos (`id <= 7747`)
    quedaron `completado` con nota de backfill para EXCLUIRLOS del pipeline (el
    default `pendiente` de la 018 se les había aplicado retroactivamente; nunca los
    aplicó el bot, eran ajustes ya gestionados a mano). Solo los items nuevos
    (`id > 7747`) nacen `pendiente`.
- `listener_writeback.py` sondea items con `backend_status='pendiente'` cuya orden
  ya esté `status='emitido'` (ignora borradores) y llama
  `flujo_stock_real.ajustar_stock(codigo_producto, delta, commit=, delta=True)` con
  el `delta` que la app ya calculó — **modo relativo**, no absoluto: si entre que se
  emitió la orden y que el backend la aplica cambió el stock real (ventas, etc.), el
  ajuste relativo sigue siendo correcto.
- **⚠ DOBLE USO de la tabla:** además de la app, `sync_ajustes.py` (backend) inserta
  en estas mismas tablas **espejos históricos** de los movimientos locales de
  HybridLite (ajustes manuales y compras de la tienda), con `creado_por` **NULL** y
  firma `[Local Inv ID: n]` / `[Local Com ID: n]` en la `nota` de la cabecera. Esos
  espejos ya están aplicados localmente: si el listener los procesara se
  re-aplicarían y se armaría un **bucle de retroalimentación** (re-aplicar → se
  vuelve a espejar → se vuelve a re-aplicar). Defensa en dos capas: (1) el listener
  filtra `ordenes_cambio.creado_por=not.is.null` (solo órdenes creadas por un
  usuario de la app); (2) `sync_ajustes.py` inserta sus items directamente en
  `backend_status='completado'`.
- **Requiere `SUPABASE_SERVICE_KEY`** en el `.env` del backend — **ya configurada
  (2026-07-09)**. La tabla `ordenes_cambio_items` tiene RLS que solo deja ver/editar
  al dueño autenticado (`owner_items` en `004_rls.sql` de la app) — con la anon key
  el listener vería siempre 0 filas, **sin ningún error**, porque RLS filtra en
  silencio.
- Gate de seguridad: por defecto procesa en **preview** (`commit=False`, cancela sin
  guardar); solo aplica cambios reales con `HYBRID_WRITE_ENABLED=1` en el entorno. En
  bucle continuo (`python listener_writeback.py`, sin `--once`) **no procesa nada**
  si `HYBRID_WRITE_ENABLED` no está en `1` (evita tomar el mouse en preview sin fin
  cada 8s); `--once` sí corre una pasada de preview para pruebas puntuales.

### Protecciones del listener (hardening 2026-07-09)

- **Guard de `H:`**: antes de cada pasada chequea que `TExistenciaInv.Dat` sea
  accesible; si la unidad `H:` / el share `\\PRINCIPAL\Happs` está caído, no pide ni
  procesa pendientes (una caída de red ya nos quemó 2 de 3 reintentos de 10 items).
- **`HYBRID_WRITE_WINDOW` (opcional)**: ventana horaria `"HH:MM-HH:MM"` local, con
  soporte de cruce de medianoche (ej. `19:30-07:30`). Fuera de la ventana el bucle
  continuo no procesa nada (el input real toma el mouse ~30s por item). Si la
  variable está seteada pero es inválida → **fail-closed** (no procesa). `--once` la
  ignora (corrida manual supervisada).
- **Reintentos conservadores**: solo fallos en etapas PRE-commit (`abrir_hybrid`,
  `carga/conteo`) reintentan (hasta 3). Cualquier etapa ambigua post-commit
  (`totalizar`, `verificacion_db`) o excepción → `error` **inmediato** con
  advertencia: como el ajuste es relativo (delta), reintentar un commit ambiguo
  puede aplicarlo DOS VECES. Verificar en HybridLite antes de reencolar a mano.
- **Recuperación de huérfanos**: al arrancar, todo item que quedó en `aplicando`
  (corrida anterior interrumpida) pasa a `error` con nota de verificación manual —
  nunca se auto-reencola.
- **`delta` NULL** → `error` inmediato (dato mal generado, corregir en la app).
  **`delta` 0** → `completado` directo sin tocar HybridLite.
- **Anti-spam de logs**: los avisos de "no proceso" (H: caída, fuera de ventana) se
  loguean solo al cambiar de estado, no cada 8 segundos.

### Sin usar por ahora

La tabla genérica `cambios_solicitados` / `schema.sql` (pensada también para
**precio**, que la app todavía no tiene como feature) queda **sin usar** — no se
ejecutó ni se cableó. Retomarla el día que se agregue edición de precio en la app.

## Pendiente

1. **Prueba end-to-end real**: emitir una orden de cambio de prueba desde la app
   sobre `00-002-024`, correr `python listener_writeback.py --once` (preview) y
   después con `HYBRID_WRITE_ENABLED=1` para confirmar el commit real contra
   HybridLite.
2. **Modificaciones en la app El Serrucho Go**: mostrar `backend_status` /
   `backend_resultado` por item (chip de estado), reencolado manual de items en
   `error` (con advertencia de verificación previa), realtime opcional. Ver
   `el-serrucho-go/docs/WRITEBACK-PIPELINE.md`.
3. **Limpieza** de scripts de diagnóstico (`diag_*`, `shot_*`, `dbg_*`, `*.png`,
   enfoques ODBC/pywinauto abandonados, incluido `hybrid_ui.py`).
4. **Integración al watchdog**: decidir si `listener_writeback.py` entra a
   `backend_watchdog.py` (con `HYBRID_WRITE_ENABLED=1` + `HYBRID_WRITE_WINDOW` de
   producción) una vez validado el end-to-end.
