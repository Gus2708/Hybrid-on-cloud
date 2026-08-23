# 📊 Auditoría e Integridad de Ventas y Detalles

> [!NOTE]
> Los cambios detallados en este documento han sido integrados en la rama principal y están resumidos en el [README.md](file:///c:/Proyect/backend%20serrucho/README.md) y [ARCHITECTURE.md](file:///c:/Proyect/backend%20serrucho/ARCHITECTURE.md). Este archivo se mantiene como registro histórico de la auditoría.

Este documento detalla los ajustes realizados en el motor de sincronización para alinear los datos de ventas de la base de datos en la Nube (Supabase) con los reportes de gestión de **HybridLite**.

## 🔍 Problemas Identificados

1.  **Discrepancia en el Conteo**: La Nube reportaba ~29,700 ventas mientras que el reporte de gestión mostraba ~25,400. Se detectó que se estaban subiendo **Notas de Entrega (Tipo 10)** y **Facturas Anuladas (Status 4)**, las cuales no deben figurar en el reporte de ventas reales.
2.  **Inconsistencia de Moneda**: El sistema local almacena montos en **Bolívares (Bs.)**, pero el reporte de gestión y la visión estratégica del negocio se manejan en **Dólares (USD)**.
3.  **Tasa de Cambio Estática**: Inicialmente se usaba una tasa fija, lo cual causaba errores en facturas de distintas fechas debido a la fluctuación diaria del **BCV**.
4.  **Datos Huérfanos**: Al re-extraer datos filtrados, los registros "basura" previos permanecían en la nube, inflando los contadores del Widget.

---

## 🛠️ Soluciones Implementadas

### 1. Filtrado de Extracción (`extraer_ventas.py`)
Se modificó el script de extracción para aplicar filtros de integridad directamente sobre los archivos `.dat`:
*   **Solo Facturas**: Se implementó un filtro para procesar únicamente registros con `THT_TIPO = 11`.
*   **Exclusión de Anuladas**: Se omiten registros con `THT_STATUS = 4`.
*   **Nuevas Columnas**: Se añadieron `THT_TOTALBRUTO` (Subtotal) y `THT_FACTORREFERENCIAL` (Tasa del día) al proceso de exportación.

### 2. Conversión Dinámica de Moneda (`sync_ventas.py`)
Para garantizar que cada venta refleje su valor real en USD:
*   **Tasa por Factura**: El script ahora lee el campo `THT_FACTORREFERENCIAL` de cada documento. Esto asegura que una venta de inicios de mayo use la tasa de ese día y una de hoy use la tasa actual del BCV.
*   **Cálculo de Totales**: Se convierten automáticamente a USD los campos: `total_neto`, `total_impuesto` y `total_bruto`.
*   **Detalles en USD**: El precio unitario en `ventas_detalle` ahora también se guarda en USD, permitiendo auditorías de precios precisas.

### 3. Ajuste de Esquema y Limpieza
*   **Base de Datos**: Se agregó la columna `total_bruto` a la tabla `ventas` en Supabase vía migración SQL.
*   **Purga de Datos**: Se ejecutó una limpieza total (`DELETE`) de las tablas de ventas en la nube para eliminar registros duplicados o no deseados de sincronizaciones previas.

---

## ✅ Resultado Final

*   **Ventas Sincronizadas**: 25,430 (Facturas válidas).
*   **Detalles Sincronizados**: 52,943.
*   **Estado de Integridad**: **100% Verde** en el Widget de monitoreo.
*   **Precisión**: Los montos en USD coinciden centavo a centavo con el reporte "General de Ventas" de HybridLite.

> [!IMPORTANT]
> A partir de este ajuste, cualquier nueva venta detectada por el monitor será convertida automáticamente a USD usando la tasa oficial grabada por Hybrid en el momento de la transacción.
