# 🛠️ Reporte de Fix Backend — Widget V2 (2026-05-09)

Este documento resume las correcciones aplicadas al widget de sincronización para resolver las regresiones que afectaron la integridad de datos en Supabase. **Los datos en la nube ya son consistentes y están listos para ser consumidos por la App móvil sin parches adicionales.**

## 📋 Resumen de Correcciones

| # | Bug | Solución | Estado |
|---|---|---|---|
| 1 | Productos con valores en cero | Se corrigió el parsing de números con comas y se añadió salvaguarda de aborto si >50% fallan. | ✅ **Fixed** |
| 2 | Ventas/Detalle en VES (Bolívares) | Se forzó el uso del `THT_FACTORREFERENCIAL` de cada factura para conversión a USD nativo. | ✅ **Fixed** |
| 3 | `total_bruto` siempre en 0 | Se implementó el cálculo de subtotal (Neto - Impuesto) y población del campo. | ✅ **Fixed** |
| 4 | FK `venta_id` en NULL | Se mapeó el ID real de Supabase durante el upsert de detalles (vínculo restaurado). | ✅ **Fixed** |
| 5 | Duplicados de Ventas | Se cambió la clave de upsert a `id_unico` (HybridLite) y se aplicó UNIQUE constraint. | ✅ **Fixed** |

---

## 🗄️ Estado Actual de los Datos (USD)

### Tabla `ventas` (Cabecera)
Los montos ahora reflejan valores reales en **USD**. Se ha poblado el campo `total_bruto` y `metodo_pago` V2.

| id | documento | fecha_emision | total_neto ($) | total_bruto ($) | metodo_pago | id_unico |
|---|---|---|---|---|---|---|
| 208770 | 00025245 | 2026-05-09 | 16.20 | 13.96 | T. DEBITO | 1586704765 |
| 183236 | 00025244 | 2026-05-09 | 16.45 | 14.18 | T. DEBITO | 1077448438 |
| 183235 | 00025243 | 2026-05-09 | 8.00 | 6.90 | EFECTIVO USD | 914226905 |

### Tabla `ventas_detalle`
Se eliminaron los registros huérfanos y se re-sincronizaron con el `venta_id` correcto. Los precios ya están divididos por la tasa histórica.

| id | documento | codigo_producto | cantidad | precio_venta ($) | venta_id (FK) |
|---|---|---|---|---|---|
| 67195 | 00025245 | 02701 | 1.0 | 1.50 | 208770 |
| 67194 | 00025245 | 03509 | 2.0 | 5.60 | 208770 |
| 67190 | 00025244 | 05183 | 1.0 | 11.55 | 183236 |

---

## 📢 Instrucciones para el Equipo de la App Móvil

> [!CAUTION]
> **ES CRÍTICO REVERTIR LOS PARCHES TEMPORALES.**
> Las vistas SQL `vw_ventas_items_usd` y `vw_ventas_usd` ya han sido restauradas a su versión original.

### Acciones requeridas:
1.  **Eliminar divisiones manuales**: Si la app estaba dividiendo los campos `total_neto` o `precio_venta` por la tasa BCV del día, debe dejar de hacerlo inmediatamente para evitar una "doble división".
2.  **Usar JOIN por ID**: Ya no es necesario hacer JOIN por `documento` y `fecha_emision`. El campo `venta_id` en `ventas_detalle` es ahora la fuente de verdad.
3.  **Actualizar Dashboard**: Los gráficos de ventas ahora mostrarán montos precisos históricos basados en el cambio de cada día, no en la tasa actual.

---

## ✅ Verificación Final de Integridad
- **Total Ventas Re-sincronizadas:** 25,533
- **Total Detalles Vinculados:** 53,154
- **Errores de FK:** 0
- **Valores fuera de rango ($ > 5000):** 0 (detectados 1, verificado legítimo)

**Reporte generado por Antigravity (IA) - 9 de mayo de 2026.**
