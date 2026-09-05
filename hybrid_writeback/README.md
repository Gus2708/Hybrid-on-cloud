# Write-back: editar PRECIO y STOCK en HybridLite desde el backend

Permite que, desde la app / el bot, se solicite un cambio de **precio** o **stock** y que
el backend lo aplique en el sistema local HybridLite **sin corromper la base de datos**.

> **Estado (2026-07-23):** ✅ **Pipeline COMPLETO y en producción 24/7.** Cuatro listeners
> supervisados por `backend_watchdog.py` aplican solos: **stock/precio/costo/ficha**
> (`listener_writeback`), **compras** (`listener_compras`), **pedidos** (`listener_pedidos`)
> y **altas de cliente/proveedor** (`listener_directorio`). Todo verificado contra la DBISAM
> real (pydbisam). Última pasada: **optimización de latencia + auditoría de colas** (ver
> [§ Rendimiento y auditoría de colas](#rendimiento-y-auditoría-de-colas-2026-07-23)).

---

## Arquitectura del paquete

> Sección agregada tras los planes 018–020 (base de listeners, paquete limpio,
> diagnóstico separado). El resto del documento (debajo) es el registro histórico
> del descubrimiento del write-back; se conserva tal cual.

### Mapa de módulos

| Archivo | Rol |
|---|---|
| `realinput.py` | Motor de input real (`SendInput`): clic/tecla de hardware. |
| `flujo_precio.py` | Base compartida de ventanas: `_find_hwnd`, filtro de PID objetivo (`set_target_pid`), constantes de clase de ventana. |
| `hybrid_price_writer.py` | Lectura DBISAM (`_db_precio_usd`, `_db_costo_usd`) y localización de campos/diálogos. |
| `read_db_precio.py` / `read_db_existencia.py` | Lectura DBISAM de precio/existencia para verificación. |
| `flujo_precio_real.py` | Coreografía de precio/costo en la Ficha. |
| `flujo_stock_real.py` | Coreografía de ajustes de stock (single y lote; la carga de fila vive en `cargar_y_fijar_fila`, el single delega con fila=0). |
| `flujo_compra_real.py` | Coreografía de compras + alta de producto nuevo. |
| `abrir_hybrid.py` | Instancia AISLADA de HybridLite: launch, login, `cerrar_aislada()` (solo mata el PID propio). |
| `hybrid_health.py` | Detección de HybridLite **colgado** y kill de recuperación (ver más abajo). |
| `safety_control.py` | Banner topmost, F12 aborto, mutex del mouse (`Local\SerruchoBotMouseLock`) que serializa los dos listeners. |
| `flujo_pedido_real.py` | Coreografía de pedidos de cliente (Tipo 10 / Status 4). |
| `flujo_directorio_real.py` | Coreografía de alta de cliente/proveedor en la Ficha del Directorio. |
| `flujo_ficha_real.py` | Edición de descripción/referencia de un producto existente (Modificar). |
| `alias_manager.py` | Resolución y catálogo de equivalencias de códigos de proveedor (`alias_proveedores.json`). |
| `batch_price_updater.py` | Motor de actualización masiva de precios/costos con checkpoints, telemetría y prefiltrado DBISAM. |
| `listener_base.py` | Núcleo común de los 4 listeners (config, logging, guards, REST, prioridad `hay_pendientes_prioritarios`, bucle `correr_loop`). |
| `listener_writeback.py` | Pipeline `ordenes_cambio_items` (stock/precio/costo/ficha), 3 fases globales por pasada. |
| `listener_compras.py` | Pipeline `compras_app` (una compra = un documento). |
| `listener_pedidos.py` | Pipeline `pedidos_app` (un pedido = un documento Tipo 10). |
| `listener_directorio.py` | Pipeline `registro_clientes_app` / `registro_proveedores_app` (**prioritario**: los demás listeners le ceden el paso). |
| `grabar_flujo.py` | Grabadora de coreografías (sesiones con el dueño). |
| `diagnostico/` | Scripts desechables (ver su propio README). |

### Flujo de datos

1. La app (El Serrucho Go) escribe un pendiente en Supabase (`ordenes_cambio_items`,
   `compras_app`, `pedidos_app`, `registro_clientes_app` / `registro_proveedores_app`),
   con `backend_status='pendiente'`.
2. El listener correspondiente sondea su tabla cada `POLL_INTERVAL` (3 s en reposo,
   `listener_base.py`) y **re-sondea en 1 s tras una pasada productiva** para drenar la
   cola sin tiempo muerto. Usa `SUPABASE_SERVICE_KEY` (la RLS de esas tablas exige dueño
   autenticado; con la anon key el listener vería 0 filas, sin error).
3. Se ejecuta la coreografía de input real sobre una instancia AISLADA de
   HybridLite (levantada/logueada por `abrir_hybrid.py`), nunca sobre la sesión
   del empleado.
4. El resultado se verifica leyendo la DBISAM directamente (`read_db_precio.py` /
   `read_db_existencia.py` / lectura equivalente embebida en cada flujo).
5. El estado final (`completado` / `error`) y el detalle quedan en Supabase
   (`backend_status`, `backend_resultado`, `backend_intentos`, `backend_aplicado_en`).
6. La app muestra ese estado como chip en el item correspondiente.

### Recuperación de HybridLite colgado (`hybrid_health.py`, 2026-08-12)

Cada tanto HybridLiteOS deja de responder y hasta ahora había que ir al
Administrador de tareas a matar todo a mano: el bot no distinguía una app colgada
de una sana, intentaba trabajar sobre ella y el ítem fallaba en la etapa
`abrir_hybrid` (reintentable, así que reintentaba contra la misma app muerta).

`abrir_hybrid.asegurar_hybrid()` —el punto por el que pasan **los 6 flujos**—
ahora arranca llamando a `hybrid_health.recuperar_si_colgado()`:

| Síntoma | Cómo se detecta |
|---|---|
| Ventana que no bombea mensajes | `IsHungAppWindow` + `SendMessageTimeout(WM_NULL, SMTO_ABORTIFHUNG)` sobre cada ventana top-level visible de un `HybridLiteOS.exe` |
| Proceso fantasma | PID de `HybridLiteOS.exe` vivo **sin ninguna ventana visible** propia (es el que suele trabar el arranque de instancias nuevas) |

Confirmado el síntoma, se reconfirma durante `HYBRID_HANG_GRACE` (10 s por
defecto) — un reporte pesado congela la ventana unos segundos y **no** es motivo
para matar nada — y recién entonces se hace `taskkill /F /T /IM HybridLiteOS.exe`,
se espera a que los procesos mueran de verdad + 3 s de settle (que el SO libere
los handles de los `.Dat`) y `asegurar_hybrid()` sigue su curso lanzando y
logueando una instancia limpia. El flujo continúa sin intervención.

Además, si un intento de lanzar la instancia aislada **no produce ninguna
ventana**, `matar_huerfanos()` cierra el proceso a medio arrancar — solo PIDs
nacidos en ese intento, nunca el del empleado. Sin eso, cada intento fallido
dejaba un fantasma más.

Costo en el camino sano: **~21 ms** por flujo (barrido de 260 procesos + 4 pings).

```powershell
python hybrid_health.py            # diagnóstico, no toca nada (exit 1 si está colgado)
python hybrid_health.py --matar    # mata todas las instancias, colgadas o no
```

Variables opcionales: `HYBRID_HANG_GRACE` (s de gracia, 10), `HYBRID_HANG_KILL=0`
(diagnosticar sin matar: el flujo aborta con el detalle), `HYBRID_HANG_PING_MS`
(800), `HYBRID_HANG_SETTLE` (3 s), `HYBRID_HANG_EXES`.

### Invariantes de seguridad (NUNCA romper)

- Nunca cerrar la ventana de HybridLite del empleado; solo la instancia aislada
  propia (`abrir_hybrid.cerrar_aislada()`, por PID verificado). **Única
  excepción:** `hybrid_health.matar_todo()` con un cuelgue CONFIRMADO — ahí la
  app del empleado ya estaba perdida igual, y sin matarla no arranca ninguna otra.
- Nunca UPDATE crudo a la DBISAM ni parchear los `.DAT` (solo lectura).
- Todo-o-nada pre-Totalizar: cualquier fallo cancela el documento entero.
- Los timings, coordenadas y el orden de manejo de alertas de las coreografías
  son COMPORTAMIENTO validado en vivo: no se "limpian".
- La alerta "producto llegó al mínimo" (`TFConfirmacion`) se responde `&Ok` y se
  continúa; es tardía/asíncrona en compras.
- Etapas ambiguas (post-commit) NO son reintentables: riesgo de aplicación doble
  (ver `ETAPAS_REINTENTABLES` en cada listener).
- Tras cambiar código: reiniciar los procesos (`start_backend.vbs`) — un proceso
  stale aplicando código viejo ya causó 2 incidentes.

### Cómo probar sin escribir

- `--once` sin `HYBRID_WRITE_ENABLED=1` corre una sola pasada en modo preview.
- Los flujos de bajo nivel aceptan `commit=False` como default seguro.
- Un preview igual **toma el mouse** si hay pendientes: no correr en horario de
  atención ni mientras alguien usa HybridLite en la estación.

---

## Rendimiento y auditoría de colas (2026-07-23)

Pasada de optimización de latencia + auditoría de que las colas no se rompen en ningún caso.
Diagnóstico hecho midiendo los **deltas de timestamps reales de `writeback.log`**.

### Cuellos de botella medidos y corregidos

| Síntoma (medido) | Causa | Cambio |
|---|---|---|
| ~14.6 s muertos entre una tarea y la siguiente (picos de 26–75 s) | `POLL_INTERVAL=5` fijo + **3 queries a Supabase por pasada** (2 del chequeo de prioridad `ceder_si` + 1 de pendientes), aun ociosas | `POLL_INTERVAL` 5→3 s; nuevo `POLL_INTERVAL_TRAS_TRABAJO=1 s` (re-sondeo rápido tras una pasada productiva); el bucle pide pendientes **una vez** y solo paga `ceder_si` si hay trabajo → sondeo ocioso de 3 a **1 query** |
| ~7 s muertos por ítem en precio/pedido/compra (`Lista posicionada: False`) | `_esperar_refresco` quemaba su timeout de 6 s+1 s **siempre** que la grilla era ilegible | corta a `probe_ilegible=1.5 s` si la grilla nunca se pudo leer (+ fallback 1.0→0.5 s) → ~2 s; el caso legible **no cambia** |

> Los picos de 26–75 s son **contención del mutex de mouse** entre los 4 listeners (un solo
> mouse físico): se alivian al bajar el tiempo por ítem, pero no se eliminan — es un límite físico.

### Cómo se manejan las colas (los 3 mecanismos que evitan romperlas)

1. **Lock optimista** — cada ítem/cabecera se marca `aplicando` + `backend_intentos++`
   **antes** de tocar HybridLite; `get_pendientes` solo trae `backend_status='pendiente'`.
2. **Mutex de mouse cross-proceso** (`Local\SerruchoBotMouseLock`, timeout 5 min, degrada
   sin él) — serializa a los 4 procesos: nunca hay dos bots clickeando a la vez.
3. **Prioridad directorio** (`ceder_si=hay_pendientes_prioritarios`) — compras/pedidos/
   writeback ceden mientras haya altas de cliente/proveedor `pendiente`, para que existan en
   Hybrid antes del documento que las referencia; el mutex tapa además la ventana `aplicando`.

### Máquina de estados por ítem

```
pendiente ──lock──► aplicando ──► completado            (commit real verificado en DB)
                                └► pendiente             (preview, o fallo REINTENTABLE < MAX_INTENTOS=3)
                                └► error                 (etapa AMBIGUA post-commit, o intentos ≥ 3,
                                                          o guarda anti doble-stock)
```

**Taxonomía de etapas (auditada consistente en los 4 listeners):**
- **Reintentables** (pre-commit, todo-o-nada, nada quedó a medias): `abrir_hybrid`,
  `navegacion`, `carga/conteo`, `carga_item`, `precio_item`, `escritura`, `aceptar`,
  `campos`, `alta_producto:*` (pre-Guardar).
- **Ambiguas → `error` inmediato** (post-commit, riesgo de doble aplicación): `totalizar`,
  `verificacion_db`, `guardar`, `alta_producto:guardar`.
- En compras las etapas del alta se **prefijan** `alta_producto:` en `registrar_compra`, y
  `carga_item`/`precio_item` se **construyen dinámicas** (no salen en un grep literal, pero existen).

### Guarda anti doble-ajuste de kardex (nueva, 2026-07-23)

Único hallazgo del audit: un ítem de writeback con parte de **stock + precio/costo/ficha** a
la vez, si el **stock commitea** (delta relativo = documento permanente) y la fase hermana
falla reintentable, volvía a `pendiente` y en el reintento **re-aplicaba el delta → doble
ajuste**. `_aplicar_resultado_final` ahora detecta *stock commiteado + hermana pendiente* y
degrada a **`error`** (revisión manual) en vez de reencolar. Las fases absolutas
(precio/costo/ficha) son idempotentes y **no** gatillan la guarda. Reachability ínfima (la app
separa stock de precio/ficha en items distintos: 0 de 6 635 los combinan), pero el blindaje
cierra el hueco a futuro.

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
3. **Limpieza** de los enfoques abandonados que siguen versionados
   (`hybrid_ui.py`, `odbc_*.py`, `dbisam_write.py`): se conservan como registro
   de lo que se probó y por qué no sirvió, pero no deben confundirse con código
   de producción. Los artefactos generados (`*.png`, `calib_*`, `dump_*`,
   snapshots `.bin`) ya salieron del repositorio y hoy los cubre `.gitignore`.
4. **Integración al watchdog**: decidir si `listener_writeback.py` entra a
   `backend_watchdog.py` (con `HYBRID_WRITE_ENABLED=1` + `HYBRID_WRITE_WINDOW` de
   producción) una vez validado el end-to-end.

---

## Optimización de Latencia y Actualización Masiva (2026-09)

En septiembre de 2026 se completó una refactorización de rendimiento y robustez sobre el flujo de actualización de precios y costos, validada en vivo con los **66 productos de Floripaint** (100% verificados en DBISAM `TCostoPrecioInv.Dat`):

1. **Eliminación de pausas muertas entre productos (de 4.5s a 0.001s):**
   - En ejecución en caliente se desactiva la lectura individual síncrona por ítem (`verificar_db=False`).
   - Se añadió `_db_valores_usd_batch(codigos)` en `hybrid_price_writer.py`, que audita lotes enteros de la DBISAM en streaming en una sola pasada de red (**0.68s para 66 ítems** vs >120s antes).

2. **Cierre instantáneo de Ficha (de 6.10s a 0.03s):**
   - `TTConfigForm` no posee botón `&Salir`. Se reemplazó el intento de búsqueda de pywinauto (timeout de 5.0s) por `win32gui.PostMessage(hf, win32con.WM_CLOSE, 0, 0)`.

3. **Navegación veloz a Compras (de 17s a 5.17s):**
   - Se reemplazó el chequeo bloqueante `.is_visible()` sobre botones no instanciados por `.exists(timeout=0)`.

4. **Tolerancia estricta (<0.005) contra recálculos de Delphi:**
   - La constante de comparación en `flujo_precio_real.py` e `hybrid_price_writer.py` se fijó en `TOL = 0.01`, y la omisión de reescritura en `< 0.005`, impidiendo que el redondeo automático del POS altere el precio meta.

5. **Nuevo motor batch con checkpoints (`batch_price_updater.py`):**
   - Soporte de reanudación automática tras caídas de red o interrupciones.
   - Resolución automática de equivalencias con `alias_manager.py` (`alias_proveedores.json`).
   - Prefiltrado en 0.6s para no tocar ítems que ya están al día en la base de datos.
   - Auditoría final obligatoria y telemetría estructurada en tiempo real.

Para detalles completos, ver [docs/auditorias-y-reportes/auditoria_y_mejoras_hybrid.md](../docs/auditorias-y-reportes/auditoria_y_mejoras_hybrid.md).

