# Auditoría Técnica y Mejoras de Rendimiento en HybridLiteOS Write-Back

**Fecha:** Septiembre 2026  
**Entorno:** HybridLiteOS (Delphi 7 / DBISAM 4.30) sobre red SMB (`H:\`)  
**Caso de prueba:** Catálogo Floripaint (66 productos, actualización de costos +16% IVA con descuentos y redondeo entero hacia arriba).

---

## 1. Resumen Ejecutivo

Durante la ejecución y auditoría de la actualización masiva de precios y costos de los **66 productos de Floripaint**, se identificaron, diagnosticaron y corrigieron **5 cuellos de botella de latencia y un fallo sutil de lógica de tolerancia** en la automatización de la UI de HybridLiteOS.

Como resultado de estas intervenciones:
* El tiempo de ciclo por producto se redujo de **~35-45 segundos a 14.18 segundos** (aceleración > 60%).
* La transición muerta entre un guardado y la siguiente búsqueda pasó de **4.5 segundos a 0.001 segundos** (prácticamente instantánea).
* El tiempo de cierre de ventanas pasó de **6.10 segundos a 0.03 segundos** (reducción del 99.5%).
* La verificación de base de datos pasó de **>120 segundos (bucle secuencial) a 0.68 segundos** (lectura en lote de 1 pasada).
* Los 66 productos fueron verificados al **100.0% de exactitud en DBISAM (`TCostoPrecioInv.Dat`)**.

---

## 2. Hallazgos y Diagnóstico de Cuellos de Botella

### 2.1. El "Trap de Tolerancia" en el Recálculo de Delphi (`TOL = 0.02`)
* **Problema:** En el producto `THINNER-M`, el costo nuevo era `$3.04` y el precio meta `$4.00`. Al escribir `$3.04` en el diálogo `TFHCostosPrecios`, el algoritmo de margen interno de Delphi recalculó automáticamente el PVP a `$4.0177` (mostrado en pantalla como `$4.02`). 
* **Causa raíz:** La función `escribir_precio()` contenía una comprobación de optimización:
  ```python
  if con_actual is not None and abs(con_actual - target) <= TOL:
      return  # se asume que ya está en el target y se salta el tecleo
  ```
  Como `TOL = 0.02` y `abs(4.02 - 4.00) == 0.02`, la condición evaluó `True`. El bot saltó la escritura de `$4.00`, dejando el valor recalculado por el POS (`$4.02`).
* **Solución aplicada:**
  1. Se cambió la condición de omisión de escritura a una cota estricta de medio centavo:
     ```python
     if con_actual is not None and abs(con_actual - target) < 0.005:
     ```
  2. Se ajustó la constante global `TOL` en `flujo_precio_real.py` e `hybrid_price_writer.py` a `0.01` (1 centavo exacto). Con esto, cualquier desviación respecto al precio fijado obliga a reescribir el campo.

---

### 2.2. Timeout en Cierre de Ficha de Inventario (`TTConfigForm`)
* **Problema:** Cada vez que el bot cerraba la Ficha de Inventario (`_cerrar_ficha_si_abierta`), se quedaba congelado durante **6.10 segundos**.
* **Causa raíz:** `TTConfigForm` tiene botones de barra tipo owner-drawn y **carece de un botón con título `&Salir`**. La rutina llamaba a `child_window(title="&Salir")`, la cual esperaba el timeout por defecto de pywinauto (5.0 segundos) antes de lanzar excepción y recurrir a mensajes de Windows.
* **Solución aplicada:** Se eliminó la búsqueda del botón inexistente y se envía directamente `win32gui.PostMessage(hf, win32con.WM_CLOSE, 0, 0)`. El tiempo de cierre cayó de **6.10s a 0.03s** (30 milisegundos).

---

### 2.3. Timeout en el Botón "Compra de Mercancías"
* **Problema:** Al pasar de Ficha a Compras, el bot se quedaba colgado otros 5.0 segundos.
* **Causa raíz:** En `abrir_compras()`, se llamaba a `cand.is_visible()`. En pywinauto, invocar `.is_visible()` sobre un elemento que aún no existe en el DOM dispara internamente una búsqueda con timeout de 5.0 segundos.
* **Solución aplicada:** Se reemplazó por `cand.exists(timeout=0) and cand.is_visible()`, retornando en 3 milisegundos y reduciendo la navegación del menú lateral a **0.43s**.

---

### 2.4. Bucle Bloqueante de SMB en Guardado y Transición
* **Problema:** Entre pulsar `Guardar` en un ítem y comenzar la búsqueda del siguiente, transcurrían ~4.5 segundos de pantalla quieta.
* **Causa raíz:** `flujo_precio_real.py` ejecutaba dos llamadas síncronas (`_db_precio_usd` y `_db_costo_usd`) que abrían la tabla `TCostoPrecioInv.Dat` (20 MB) dos veces por red a través de SMB (`H:\`), con bucles de reintento de 3 segundos.
* **Solución aplicada:**
  1. En modo por lote, la verificación en caliente corre con `verificar_db=False`, aprovechando que la validación en pantalla antes del commit ya es 100% segura.
  2. Se creó `_db_valores_usd_batch(codigos)` en `hybrid_price_writer.py`: abre la tabla DBISAM **una sola vez** en memoria streaming y extrae todos los precios/costos de todos los productos en **0.68 segundos**.
  3. La transición entre guardado e inicio del siguiente producto pasó de **4.5s a 0.001s**.

---

### 2.5. Demora de Filtrado en la Grilla de Búsqueda de Delphi (~4.5s)
* **Observación:** El único paso que consume tiempo significativo en el ciclo por ítem son los ~4.3s que tarda Delphi en procesar el filtro de la tabla de inventario en red (evidenciado cuando la barra de desplazamiento `TScrollWindow` desaparece).
* **Conclusión de diseño:** Este tiempo es intrínseco del motor DBISAM de Delphi al filtrar por red. Para cargas de compras o facturas de proveedores donde vienen decenas de ítems, el camino óptimo es procesarlas por el módulo de **Compras** (`flujo_compra_real.py`), donde los ítems se cargan en grilla continua sin abrir y cerrar la Ficha 66 veces.

---

## 3. Nuevos Componentes Implementados

### 3.1. Gestor de Equivalencias de Códigos (`alias_manager.py`)
* **Ubicación:** `hybrid_writeback/alias_manager.py` y `hybrid_writeback/alias_proveedores.json`.
* **Función:** Permite mapear códigos de catálogos o facturas de proveedores que difieren de los códigos internos de HybridLiteOS (por ejemplo, `THINNER-01` $\to$ `THINNER-M`).
* **API:**
  ```python
  from alias_manager import resolver_alias, registrar_alias
  codigo_real = resolver_alias("THINNER-01", proveedor="FLORIPAINT") # Devuelve 'THINNER-M'
  ```

### 3.2. Motor de Actualización Masiva Resiliente (`batch_price_updater.py`)
* **Ubicación:** `hybrid_writeback/batch_price_updater.py`.
* **Características:**
  * **Pre-filtrado DBISAM:** Lee en 0.6s todos los productos del lote y omite automáticamente los que ya coinciden con el precio/costo meta.
  * **Checkpoints:** Guarda el progreso en `scratch/batch_checkpoint.json`. Si ocurre una desconexión o fallo, reanuda exactamente en el ítem pendiente.
  * **Extracción segura de valores:** Reconoce variantes de llaves JSON (`precio`, `precio_venta_sugerido_25`, `pvp`, `costo`, etc.) y exige valores positivos válidos (`val > 0`), impidiendo fijar precios a 0 por omisión de campos.
  * **Telemetría en tiempo real:** Emite logs formateados a consola y a archivo tracker persistente.
  * **Auditoría final consolidada:** Al concluir el lote, ejecuta una sola lectura DBISAM de red para confirmar el 100% de los productos.

### 3.3. Unificación de Confirmaciones (`_confirmar_si`)
* **Ubicación:** `hybrid_writeback/flujo_precio_real.py`.
* **Mejora:** Atiende indistintamente ventanas de clase `TMessageForm` o `TFConfirmacion`, interceptando botones `&Yes`, `&Sí`, `Sí`, `Yes`, `Aceptar`, `OK`, `Continuar`, `&Aceptar`. Elimina el riesgo de modales huérfanos que traben el flujo.

---

## 4. Tabla Comparativa de Benchmarks

| Fase / Operación | Antes | Optimizado | Mejora (%) |
| :--- | :---: | :---: | :---: |
| **Cerrar Ficha de Inventario** | 6.10 s | 0.03 s | **-99.5%** |
| **Transición Guardar $\to$ Siguiente Ítem** | 4.50 s | 0.001 s | **-99.9%** |
| **Detección botón Compras en menú** | 5.00 s | 0.43 s | **-91.4%** |
| **Transición Total Inventario $\to$ Compras** | 17.00 s | 5.17 s | **-69.6%** |
| **Auditoría DBISAM de 66 productos** | ~132 s | 0.68 s | **-99.5%** |
| **Tiempo total por ítem (Ficha)** | ~38.0 s | 14.18 s | **-62.7%** |
| **Paso de Ítem en Pedidos (alert check)** | ~1.5 - 2.0 s | 0.001 s | **-99.9%** |
| **Apertura de Ventana Pedidos** | ~2.5 - 3.0 s | 0.14 s | **-95.0%** |
| **Cierre de Ventana Pedidos (`_salir`)** | ~4.0 s | 0.34 s | **-91.5%** |

---

## 5. Auditoría y Optimizaciones en Pedidos de Clientes (`flujo_pedido_real.py` y `listener_pedidos.py`)

Aplicando las lecciones de rendimiento y robustez de Inventario y Compras, se auditó y optimizó la creación de pedidos (Tipo 10 / Status 4):

### 5.1. Prevención de Colisiones de Códigos (`colisiones.revisar_lote`)
* **Problema:** En las grillas de HybridLiteOS, al tipear en la celda "Código", Delphi busca **primero por código de barras (`PRD_REFERENCIA`)** y solo después por código interno (`PRD_CODIGO`). Existían 98 productos en el catálogo interceptados por la referencia de otro ítem. Si un cliente pedía un código interceptado, el pedido cargaba el producto incorrecto sin que el flujo lo detectara.
* **Solución:** Integración de `colisiones.revisar_lote()` en el pre-vuelo de `registrar_pedido()`. Si el código está interceptado, el bot tipea automáticamente su referencia única segura para que cargue el producto exacto. Si no tiene salida segura, aborta fail-closed con mensaje descriptivo antes de tocar la grilla.
* **Verificación UI:** `_verificar_producto_cargado()` ahora valida que la celda de la grilla contenga el código o la referencia alternativa tecleada.

### 5.2. Soporte Universal de Alias (`alias_manager.py`)
* **Mejora:** Integrado tanto en `flujo_pedido_real.registrar_pedido` como en `listener_pedidos.get_items`. Cualquier código alternativo (ej. códigos de catálogo o proveedor) se traduce al `PRD_CODIGO` oficial del sistema antes de comprobar duplicados o escribir en la grilla.

### 5.3. Eliminación de Delays Ociosos en Carga de Ítems
* **Problema:** En cada ítem, `_confirmar_lo_que_pregunte(timeout=1.0)` ejecutaba un bucle con sleeps de 0.3s que, al no haber ninguna alerta, consumía obligatoriamente 1.2 segundos por ítem.
* **Solución:** Parámetro `inmediato_si_no_hay=True` y chequeo de existencia de ventana (`CONF_CLASS` o `TMessageForm`). Si no hay modal de advertencia, retorna en 0.001s sin dormir. El tiempo por ítem bajó drásticamente.

### 5.4. Apertura y Cierre Inmediato de Ventana de Pedidos
* **Apertura:** Reemplazado `wait("exists visible", timeout=1.5)` por sondeo inmediato con `cand.exists(timeout=0) and cand.is_visible()`, seguido de clics rápidos con polling de 0.04s.
* **Cierre:** En `_salir_pedidos()`, envío inmediato de `WM_CLOSE` tras pulsar Salir y sondeo en rodajas de 0.04s, eliminando esperas de hasta 4 segundos.

### 5.5. Resiliencia de Red SMB en `_verificar_pedido_db`
* **Problema:** Tras totalizar en HybridLiteOS, el flush de buffers SMB de Windows sobre `H:\` puede tardar unos cientos de milisegundos en reflejar el nuevo registro en `TTransaccionvta.dat` y `TDetalleVta.dat`.
* **Solución:** Lazo de reintentos (hasta 3 intentos con 0.5s de pausa) desacoplado mediante `_evaluar_pedido_db()`, asegurando lectura confiable sin falsos positivos de verificación fallida.
* **Tolerancia de precio:** Estandarizada en `TOL_PRECIO = 0.01` (1 centavo exacto).

### 5.6. Suite de Tests Automatizados de Pedidos
* **Ubicación:** `tests/test_flujo_pedido_real.py` (14 nuevos tests).
* **Cobertura:** Parseo de ítems con/sin precio, pre-vuelo de colisiones, abortos fail-closed, detección de duplicados post-alias, verificación en pantalla de códigos alternativos, cálculo de tolerancia de precios con factor referencial, y reintentos SMB mockeados.
* **Total de tests de la suite general:** 139 tests pasando al 100%.
