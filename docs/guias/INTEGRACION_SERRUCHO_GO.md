# Guía de Integración: Historial de Movimientos Unificado en El Serrucho Go

Esta guía explica cómo consumir y renderizar en la aplicación móvil **El Serrucho Go** (React Native / Expo) los movimientos de stock locales (compras y ajustes manuales) que ahora el backend sincroniza automáticamente a Supabase.

---

## 1. Arquitectura de los Datos Sincronizados

Para mantener la base de datos limpia y no alterar el esquema de Supabase, el backend reutiliza las tablas de órdenes de cambio:
* **Cabecera (`ordenes_cambio`):** Se inserta cada movimiento en estado `status = 'emitido'` con la fecha original del sistema físico (`creado_en`) y `creado_por = null` (ya que provienen del sistema de escritorio, no de un usuario móvil).
* **Detalle (`ordenes_cambio_items`):** Contiene los productos involucrados, su stock anterior (`existencia_actual`), stock nuevo (`nueva_existencia`), notas y la columna autogenerada `delta` (que calcula la diferencia de stock).

### Firmas en el Campo `nota`
Para identificar el origen del movimiento e interpretarlo correctamente en la App, cada cabecera lleva una firma en el campo `nota`:
* **Ajustes Manuales:** `[Local Inv ID: {id}] - Ajuste #{documento}: {motivo}`
  * *Ejemplo:* `[Local Inv ID: 344] - Ajuste #00000168: DESINCORPORACION DE PRODUCTOS DEFECTUOSO`
* **Compras (Ingresos de mercancía):** `[Local Com ID: {id}] - Compra #{documento}: {proveedor} (RIF: {rif})`
  * *Ejemplo:* `[Local Com ID: 158] - Compra #90276593: INVERSIONES LA FUENTE C.A (RIF: J314403419)`

---

## 2. Implementación del Hook en React Native
### Archivo: `src/hooks/useMovimientosProducto.ts`

Este hook obtiene en paralelo las ventas reales (facturadas) y las órdenes de cambio/movimientos locales, los unifica, los ordena cronológicamente (más recientes primero) y los devuelve de forma eficiente.

```typescript
import { useQuery } from '@tanstack/react-query';
import { supabase } from '../lib/supabase'; // Tu cliente de Supabase

export interface Movimiento {
  id: string;
  tipo: 'venta' | 'ingreso' | 'ajuste';
  cantidad: number;
  referencia: string;
  nota?: string;
  fecha: string; // ISO String o Formato DD/MM/YYYY
}

export function useMovimientosProducto(codigoProducto: string) {
  return useQuery<Movimiento[]>({
    queryKey: ['movimientos-producto', codigoProducto],
    queryFn: async () => {
      if (!codigoProducto) return [];

      // 1. Obtener las últimas 50 ventas validadas
      const { data: ventas, error: errVentas } = await supabase
        .from('ventas_detalle')
        .select(`
          cantidad,
          documento,
          ventas!inner(status, created_at)
        `)
        .eq('codigo_producto', codigoProducto)
        .eq('ventas.status', 1) // Solo facturas válidas
        .order('id', { ascending: false })
        .limit(50);

      if (errVentas) console.error('Error cargando ventas:', errVentas);

      // 2. Obtener los últimos 50 ajustes/compras
      const { data: ordenes, error: errOrdenes } = await supabase
        .from('ordenes_cambio_items')
        .select(`
          delta,
          nota,
          ordenes_cambio!inner(status, nota, creado_en)
        `)
        .eq('codigo_producto', codigoProducto)
        .eq('ordenes_cambio.status', 'emitido') // Solo órdenes finalizadas
        .order('id', { ascending: false })
        .limit(50);

      if (errOrdenes) console.error('Error cargando ajustes:', errOrdenes);

      // 3. Unificar y mapear los registros
      const movimientos: Movimiento[] = [];

      // Mapear Ventas (Rojo / Salida)
      if (ventas) {
        ventas.forEach((v: any) => {
          movimientos.push({
            id: `v-${v.documento}-${v.cantidad}`,
            tipo: 'venta',
            cantidad: -Math.abs(v.cantidad), // Forzar negativo para ventas
            referencia: `Factura ${v.documento}`,
            fecha: v.ventas.created_at,
          });
        });
      }

      // Mapear Ajustes y Compras locales/móviles
      if (ordenes) {
        ordenes.forEach((o: any) => {
          const cabeceraNota = o.ordenes_cambio.nota || '';
          const deltaVal = Number(o.delta);
          
          let tipoMov: 'ingreso' | 'ajuste' = deltaVal > 0 ? 'ingreso' : 'ajuste';
          let referencia = 'Ajuste manual';
          let notaDetalle = o.nota || '';

          // Detectar si proviene del backend como COMPRA (Ingreso)
          if (cabeceraNota.includes('[Local Com ID:')) {
            tipoMov = 'ingreso';
            // Extraer el número de compra y proveedor quitando la firma técnica [Local Com ID: X]
            referencia = cabeceraNota.replace(/\[Local Com ID:\s*\d+\]\s*-\s*/g, '');
          } 
          // Detectar si proviene del backend como AJUSTE
          else if (cabeceraNota.includes('[Local Inv ID:')) {
            // Extraer descripción del ajuste local
            referencia = cabeceraNota.replace(/\[Local Inv ID:\s*\d+\]\s*-\s*/g, '');
          }
          // Ajustes hechos directamente desde la App móvil
          else {
            referencia = cabeceraNota || 'Ajuste de App';
          }

          movimientos.push({
            id: `o-${o.orden_id}-${o.codigo_producto}-${deltaVal}`,
            tipo: tipoMov,
            cantidad: deltaVal,
            referencia: referencia,
            nota: notaDetalle || undefined,
            fecha: o.ordenes_cambio.creado_en,
          });
        });
      }

      // 4. Ordenar cronológicamente (más recientes primero)
      return movimientos.sort((a, b) => new Date(b.fecha).getTime() - new Date(a.fecha).getTime());
    },
    staleTime: 1000 * 30, // 30 segundos de caché
  });
}
```

---

## 3. Formateo y Estilo de la UI en React Native (Glassmorphism Premium)
### Archivo: `app/producto/[id].tsx`

Aplica esta estructura JSX dentro de tu componente de detalles de producto para que coincida perfectamente con el tema oscuro de la aplicación utilizando JetBrains Mono y colores de estado:

```tsx
import React from 'react';
import { View, Text, ScrollView, ActivityIndicator, StyleSheet } from 'react-native';
import { useMovimientosProducto } from '../../hooks/useMovimientosProducto';
import { Ionicons } from '@expo/vector-icons';

// Formateador de fecha amigable (DD/MM/YYYY)
const formatFecha = (isoString: string) => {
  try {
    const d = new Date(isoString);
    const day = String(d.getDate()).padStart(2, '0');
    const month = String(d.getMonth() + 1).padStart(2, '0');
    const year = d.getFullYear();
    return `${day}/${month}/${year}`;
  } catch {
    return '---';
  }
};

export default function HistorialMovimientos({ codigoProducto }: { codigoProducto: string }) {
  const { data: movimientos, isLoading } = useMovimientosProducto(codigoProducto);

  if (isLoading) {
    return <ActivityIndicator size="small" color="#F5A623" style={{ marginVertical: 20 }} />;
  }

  if (!movimientos || movimientos.length === 0) {
    return (
      <View style={styles.cardEmpty}>
        <Text style={styles.textDim}>Sin movimientos registrados en este producto</Text>
      </View>
    );
  }

  return (
    <View style={styles.container}>
      <Text style={styles.sectionTitle}>HISTORIAL DE MOVIMIENTOS</Text>
      <View style={styles.historyCard}>
        {movimientos.map((mov) => {
          // Determinar estilos visuales basados en el tipo de movimiento
          let iconName: any = 'sliders';
          let iconColor = '#9B9B9B'; // Gris por defecto
          let badgeBg = 'rgba(155, 155, 155, 0.12)';
          let qtyColor = '#FFFFFF';
          let labelText = '';

          if (mov.tipo === 'venta') {
            iconName = 'arrow-down-right';
            iconColor = '#FF3B30'; // Rojo peligro/salida
            badgeBg = 'rgba(255, 59, 48, 0.12)';
            qtyColor = '#FF3B30';
            labelText = `${mov.cantidad}`;
          } else if (mov.tipo === 'ingreso') {
            iconName = 'plus';
            iconColor = '#34C759'; // Verde éxito/ingreso
            badgeBg = 'rgba(52, 199, 89, 0.12)';
            qtyColor = '#34C759';
            labelText = `+${mov.cantidad}`;
          } else { // ajuste negativo
            iconName = 'sliders';
            iconColor = mov.cantidad > 0 ? '#34C759' : '#FF3B30';
            badgeBg = mov.cantidad > 0 ? 'rgba(52, 199, 89, 0.12)' : 'rgba(255, 59, 48, 0.12)';
            qtyColor = iconColor;
            labelText = mov.cantidad > 0 ? `+${mov.cantidad}` : `${mov.cantidad}`;
          }

          return (
            <View key={mov.id} style={styles.historyRow}>
              {/* Ícono circular glassmorphic */}
              <View style={[styles.iconCircle, { backgroundColor: badgeBg }]}>
                <Ionicons name={iconName} size={16} color={iconColor} />
              </View>

              {/* Información del movimiento */}
              <View style={styles.infoCol}>
                <Text style={styles.textReferencia} numberOfLines={1}>
                  {mov.referencia}
                </Text>
                {mov.nota && (
                  <Text style={styles.textNota} numberOfLines={1}>
                    {mov.nota}
                  </Text>
                )}
              </View>

              {/* Cantidad y Fecha */}
              <View style={styles.rightCol}>
                <Text style={[styles.textQty, { color: qtyColor }]}>
                  {labelText}
                </Text>
                <Text style={styles.textFecha}>
                  {formatFecha(mov.fecha)}
                </Text>
              </View>
            </View>
          );
        })}
      </View>
    </View>
  );
}

// Estilos premium oscuros
const styles = StyleSheet.create({
  container: {
    marginTop: 20,
    paddingHorizontal: 16,
  },
  sectionTitle: {
    fontFamily: 'JetBrainsMono-Bold',
    fontSize: 12,
    color: '#8A8A8F',
    letterSpacing: 1.5,
    marginBottom: 8,
  },
  historyCard: {
    backgroundColor: 'rgba(28, 28, 30, 0.7)',
    borderRadius: 16,
    borderWidth: 1,
    borderColor: 'rgba(255, 255, 255, 0.08)',
    paddingVertical: 8,
  },
  historyRow: {
    flexDirection: 'row',
    alignItems: 'center',
    paddingVertical: 12,
    paddingHorizontal: 16,
    borderBottomWidth: 1,
    borderBottomColor: 'rgba(255, 255, 255, 0.05)',
  },
  iconCircle: {
    width: 32,
    height: 32,
    borderRadius: 16,
    alignItems: 'center',
    justifyContent: 'center',
    marginRight: 12,
  },
  infoCol: {
    flex: 1,
    justifyContent: 'center',
  },
  textReferencia: {
    fontFamily: 'JetBrainsMono-Medium',
    fontSize: 13,
    color: '#E5E5EA',
  },
  textNota: {
    fontFamily: 'JetBrainsMono-Regular',
    fontSize: 11,
    color: '#8E8E93',
    marginTop: 2,
  },
  rightCol: {
    alignItems: 'end',
    justifyContent: 'center',
    marginLeft: 8,
  },
  textQty: {
    fontFamily: 'JetBrainsMono-Bold',
    fontSize: 14,
    textAlign: 'right',
  },
  textFecha: {
    fontFamily: 'JetBrainsMono-Regular',
    fontSize: 10,
    color: '#8E8E93',
    marginTop: 2,
    textAlign: 'right',
  },
  cardEmpty: {
    padding: 24,
    alignItems: 'center',
  },
  textDim: {
    fontFamily: 'JetBrainsMono-Regular',
    fontSize: 12,
    color: '#8E8E93',
  },
});
```

---

## 4. Beneficios del Diseño
1. **Unificación Inmediata:** La aplicación no necesita implementar APIs nuevas; consume datos agregados desde tablas de Supabase estándar y seguras que ya lee hoy.
2. **Carga Ultra Rápida:** Al paginar las consultas a un máximo de 50 registros por tipo en Supabase y resolver las descripciones a nivel de backend, el dispositivo móvil solo procesa la data unificada final de manera fluida y fluida.
3. **Control Total:** La visualización segmenta claramente qué movimientos corresponden a facturas (salidas), ingresos de mercancías por compras locales (ingresos), y mermas o reajustes manuales en el almacén.
