# 🔧 Corrección de Precios — Backend El Serrucho

> [!NOTE]
> Los cambios detallados en este documento (corrección de IVA 16%) han sido integrados en la lógica central de `actualizar_inventario.py` y se reflejan en la documentación principal.

**Fecha:** 7 de Mayo, 2026  
**Archivo modificado:** `actualizar_inventario.py`  
**Estado:** ✅ Resuelto y sincronizado

---

## Problema Detectado

Los precios de venta (`precio_venta`) almacenados en la base de datos de Supabase eran **~13.8% más bajos** que los precios reales mostrados por el sistema HybridLite.

### Ejemplo de discrepancia (ANTES del fix)

| Producto | Precio Real (Hybrid) | Precio en DB (incorrecto) | Diferencia |
|---|---:|---:|---|
| ALICATE DE PRESION 10 TIPO R2 EXXEL | $12.00 | $10.34 | -13.8% |
| JUEGO DESTORNILLADORES PALA/ESTRIA EXXEL | $3.00 | $2.59 | -13.8% |
| ENGRASADORA MANUAL 16L EXXEL | $65.00 | $65.00 | 0% (exento) |
| MALLA ELECTROSOLDADA 6X6 100MTS | $183.00 | $157.76 | -13.8% |
| BREAKER THQL 1X20AMP BK-1320 | $2.50 | $2.16 | -13.8% |
| BOMBILLO LED INDUSTRIAL 60W | $18.99 | $16.37 | -13.8% |

> **2,008 de 7,209 productos** estaban afectados (los que tienen IVA gravado).

---

## Causa Raíz

El archivo fuente de precios de HybridLite (`TCostoPrecioInv.Dat`) contiene **dos columnas** de precio de venta:

| Índice | Campo | Descripción |
|:---:|---|---|
| **7** | `TPC_PVPSINIMPUESTO1` | Precio de venta **SIN** IVA (base imponible) |
| **13** | `TPC_PVPCONIMPUESTO1` | Precio de venta **CON** IVA 16% incluido |

El script de extracción `actualizar_inventario.py` estaba leyendo la columna **[7]** (`TPC_PVPSINIMPUESTO1`), es decir, el precio **sin impuesto**. Sin embargo, el precio que el sistema Hybrid muestra en los habladores/etiquetas y que el cliente final paga es el de la columna **[13]** (`TPC_PVPCONIMPUESTO1`), que incluye el IVA del 16%.

La relación matemática es:

```
Precio SIN IVA × 1.16 = Precio CON IVA
1 / 1.16 = 0.8621  ← ratio exacto encontrado en el análisis
```

### Estructura completa del archivo `TCostoPrecioInv.Dat`

```
[0]  TPC_AUTOINCREMENT
[1]  TPC_CODIGOPRODUCTO      ← código del producto
[2]  TPC_TIPO
[3]  TPC_COSTOANTERIOR
[4]  TPC_COSTOACTUAL         ← costo (se mantiene igual)
[5]  TPC_COSTOPROMEDIO
[6]  TPC_COSTOREFERENCIAL
[7]  TPC_PVPSINIMPUESTO1     ← ❌ se usaba este (SIN IVA)
[8]  TPC_PVPSINIMPUESTO2
[9]  TPC_PVPSINIMPUESTO3
[10] TPC_PVPSINIMPUESTO4
[11] TPC_PVPSINIMPUESTO5
[12] TPC_PVPSINIMPUESTO6
[13] TPC_PVPCONIMPUESTO1     ← ✅ ahora se usa este (CON IVA)
[14] TPC_PVPCONIMPUESTO2
[15] TPC_PVPCONIMPUESTO3
[16] TPC_PVPCONIMPUESTO4
[17] TPC_PVPCONIMPUESTO5
[18] TPC_PVPCONIMPUESTO6
[19-24] TPC_MTOUTILIDAD1-6
[25] TPC_ULTFECHA
[26] TPC_ULTUSUARIO
[27] TPC_MODULOSOURCE
```

---

## Cambio Aplicado

### Archivo: `actualizar_inventario.py`

```diff
     db_precios = pydbisam.PyDBISAM(RUTA_PRECIOS)
-    # TPC_CODIGOPRODUCTO (1), TPC_COSTOACTUAL (4), TPC_PVPSINIMPUESTO1 (7)
+    # TPC_CODIGOPRODUCTO (1), TPC_COSTOACTUAL (4), TPC_PVPCONIMPUESTO1 (13)
+    # NOTA: Se usa columna [13] (CON impuesto) en vez de [7] (SIN impuesto)
+    #       para reflejar el precio real de venta incluyendo IVA 16%.
     for row in db_precios.rows():
         code = str(row[1]).strip()
         if code in productos:
             try:
                 costo = float(row[4]) if row[4] != 'Fail' else 0.0
-                precio = float(row[7]) if row[7] != 'Fail' else 0.0
+                precio = float(row[13]) if row[13] != 'Fail' else 0.0
```

**Resumen:** Se cambió la lectura del precio de la columna `[7]` a la columna `[13]` del archivo `.DAT`.

---

## Verificación Post-Fix

### Precios confirmados en Supabase (DESPUÉS del fix)

| Producto | Hablador Hybrid | DB Supabase | Estado |
|---|---:|---:|:---:|
| ALICATE DE PRESION 10 TIPO R2 EXXEL | 12.00 | 12.00 | ✅ |
| JUEGO DESTORNILLADORES PALA/ESTRIA EXXEL | 3.00 | 3.00 | ✅ |
| ENGRASADORA MANUAL 16L EXXEL | 65.00 | 65.00 | ✅ |
| MALLA ELECTROSOLDADA 6X6 100MTS | 183.00 | 183.00 | ✅ |
| YESO PIRAMIDE ESCAYOLA 25KG | 15.00 | 15.00 | ✅ |
| BREAKER THQL 1X20AMP BK-1320 | 2.50 | 2.50 | ✅ |
| BREAKER THQL 1X30AMP BK-1321 | 2.50 | 2.50 | ✅ |

### Resultado del análisis comparativo

```
Antes del fix:  2,008 productos con precio diferente
Después del fix: 1 producto con precio diferente (caso edge menor)
```

---

## Impacto en Aplicaciones que Consumen de la DB

### ⚠️ Qué cambió en la tabla `productos`

| Campo | Antes | Ahora |
|---|---|---|
| `precio_venta` | Precio **SIN** IVA (base imponible) | Precio **CON** IVA 16% (precio final) |
| `costo` | Sin cambios | Sin cambios |
| `existencia` | Sin cambios | Sin cambios |
| `descripcion` | Sin cambios | Sin cambios |

### Para las aplicaciones frontend/bots:

1. **El campo `precio_venta` ahora ya incluye el IVA.** Si alguna aplicación estaba calculando el IVA por separado multiplicando `precio_venta × 1.16`, **debe dejar de hacerlo** porque el valor ya viene con impuesto incluido.

2. **Si se necesita mostrar el desglose de IVA**, se puede calcular así:
   ```
   Precio base (sin IVA) = precio_venta / 1.16
   Monto IVA (16%)       = precio_venta - (precio_venta / 1.16)
   Precio total           = precio_venta  ← ya es el precio final
   ```

3. **Productos exentos de IVA:** Para estos productos, las columnas `[7]` y `[13]` del `.DAT` tienen el mismo valor, por lo que el cambio no les afecta.

### Flujo de datos actualizado

```
TCostoPrecioInv.Dat (columna 13: TPC_PVPCONIMPUESTO1)
        │
        ▼
actualizar_inventario.py  ──►  MAESTRO_ACTUAL.csv (campo PRECIO_VENTA)
        │
        ▼
sync.py  ──►  Supabase tabla "productos" (campo precio_venta)
        │
        ▼
   Aplicaciones / Bots / Frontend
```

---

## Acciones Realizadas

1. ✅ Identificado el problema comparando `Habladores_Limpio.csv` vs `MAESTRO_ACTUAL.csv`
2. ✅ Analizado la estructura del archivo `TCostoPrecioInv.Dat` (28 columnas)
3. ✅ Corregido `actualizar_inventario.py`: columna `[7]` → `[13]`
4. ✅ Re-extraído `MAESTRO_ACTUAL.csv` con los precios correctos
5. ✅ Eliminado `sync_cache.json` para forzar sync completo
6. ✅ Sincronizados los 7,209 productos a Supabase con precios corregidos
7. ✅ Verificado en la DB que los precios coinciden con los habladores de Hybrid
