# Cambios en el Esquema de Base de Datos (V2)
Este documento detalla los cambios realizados en el backend de Supabase para soportar la sincronización temporal precisa y el seguimiento de métodos de pago.

## Tabla: `public.ventas` (Cabecera)

| Columna | Tipo | Descripción |
| :--- | :--- | :--- |
| `id_unico` | `bigint` | **NUEVO.** Identificador único de la base de datos origen (HybridLite). Se usa como llave de conflicto para `upsert`. |
| `metodo_pago` | `text` | **NUEVO.** Nombre descriptivo de la forma de pago (ej. "EFECTIVO USD", "ZELLE", "T. DEBITO"). |
| `created_at` | `timestamptz` | **ACTUALIZADO.** Ahora contiene la **fecha y hora real** de la transacción en el punto de venta (UTC-4 mapeado a UTC). |
| `total_bruto` | `numeric` | **NUEVO.** Almacena el subtotal antes de impuestos. |

### Notas de Implementación:
- El campo `created_at` ya no refleja el momento de inserción en la nube, sino la hora real de la factura. Esto permite que los gráficos de tendencia horaria sean precisos.
- Se eliminó el constraint `fk_ventas_cliente` para permitir la sincronización de facturas con RIFs genéricos o clientes eliminados.

---

## Tabla: `public.ventas_detalle` (Items)

| Columna | Tipo | Descripción |
| :--- | :--- | :--- |
| `id` | `bigint` | Se cambió a un tipo serial/secuencia manual para evitar conflictos de identidad durante cargas masivas. |
| `venta_id` | `bigint` | Relación con `ventas.id`. |

### Notas de Integridad:
- Los detalles se sincronizan masivamente. Para vincular detalles históricos con sus cabeceras, se recomienda realizar el cruce por `documento` y `fecha_emision` (o utilizar el `venta_id` si se genera dinámicamente).

---

## Recomendación para la App Consumidora:
Al graficar ventas por hora, utilice:
```sql
SELECT 
  date_trunc('hour', created_at) as hora,
  sum(total_neto) as ventas
FROM ventas
GROUP BY 1
ORDER BY 1;
```
No es necesario ajustar zonas horarias manualmente en la query ya que `created_at` se almacena como `timestamptz`.
