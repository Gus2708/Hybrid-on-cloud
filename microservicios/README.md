# Microservicios de proveedores

Servicios pequeños que corren **junto al backend** y responden una pregunta: *este producto está agotado en la tienda, ¿lo tiene el proveedor?* Cada uno es un proceso independiente (API local + listener) que el watchdog levanta y vigila como al resto del backend.

| Carpeta | Proveedor | Puerto | Qué devuelve |
| :--- | :--- | :--- | :--- |
| [`maxcam/`](maxcam/README.md) | Maxcam (catálogo con login por correo) | 5001 | Disponibilidad en **Barquisimeto** |
| [`corpnorte/`](corpnorte/README.md) | Corporación Norte (API pública) | 5002 | **Stock** del proveedor |

## Cómo encajan en el backend

```
Serrucho Go (empleados)
   │  inserta una consulta
   ▼
Supabase: consultas_maxcam / consultas_corpnorte   ◄── resultado
   │                                                      ▲
   ▼  polling cada 3 s                                    │
<proveedor>_listener.py ──► <proveedor>_api.py (127.0.0.1) ──► catálogo del proveedor
   │
   └─ resuelve el producto: código exacto (hash) → si no, embeddings en Supabase
```

- **Solo productos que lo necesitan y rotan:** no se gastan consultas en productos viejos sin ventas ni en productos con stock suficiente. Solo se consulta si el producto está **agotado o con poco stock** (existencia ≤ 5, el mismo tope del badge "Stock bajo") **y** es de **alta rotación** (al menos 3 facturas vigentes en los últimos 90 días) o **nuevo** (alta desde la app con una compra `es_nuevo` en los últimos 60 días). La regla es la función SQL `proveedor_elegible` (migraciones 050 y 051 de Serrucho Go): la app oculta las tarjetas si no se cumple y los listeners la repiten antes de tocar al proveedor (responden `error: …no se consulta al proveedor`). Si la función no está desplegada o falla, se consulta igual (no se frena el servicio). Para cambiar los umbrales hay que reemplazar los valores por defecto de la función.
- **Todo es desechable:** las respuestas viven en las tablas puente solo para que la app las lea; los listeners borran las filas con más de **30 minutos** (la app reutiliza una respuesta por 15). **Las fotos no se guardan en ningún lado**: el teléfono las carga directo del servidor del proveedor sin caché (`cachePolicy: none`). En Corporación Norte la URL se arma en la app a partir del código, así que no se guarda ni siquiera la URL; en Maxcam la URL de la foto no se puede deducir del código, así que viaja como un texto corto dentro de la fila temporal y se borra con ella.
- **Supervisión:** `backend_watchdog.py` los lanza con la opción `subdir` (igual que `hybrid_writeback/`), con `pythonw` e invisibles. Si una API no responde ~60 s la reinicia. Cada script tiene nombre único porque el watchdog identifica los procesos por nombre.
- **Alcance:** las APIs escuchan solo en `127.0.0.1` y no tienen autenticación; no se exponen fuera de la PC. Desde la nube se llega únicamente por las tablas puente, que tienen RLS (solo empleados autenticados crean consultas y leen respuestas; `anon` no ve nada).
- **Configuración:** los listeners usan `config` y `supabase_rest` del backend (service key incluida). Los secretos propios de cada proveedor viven en un `.env` dentro de su carpeta, ignorado por git, igual que `session.json` (sesión de Maxcam) y los catálogos descargados.
- **SQL:** las tablas y funciones están en [`../sql/`](../sql/): `crear_maxcam_embedding.sql`, `crear_consultas_maxcam.sql` y `crear_corpnorte.sql`. Se ejecutan a mano en el SQL editor de Supabase.
- **Embeddings:** los productos del Serrucho ya están embebidos (`productos_embedding`); cada proveedor tiene su tabla con el **mismo modelo** (`text-embedding-3-small`, 1536 dimensiones). Si el modelo cambia hay que re-embeber **las tres** tablas.

## Agregar otro proveedor

1. Crear `microservicios/<proveedor>/` con `<proveedor>_api.py` (puerto libre, solo `127.0.0.1`) y `<proveedor>_listener.py`.
2. Escribir un SQL con su tabla de embeddings, su función `*_equivalentes` y su tabla puente (copiar uno de `sql/`).
3. Registrar los dos scripts en `SCRIPTS` de `backend_watchdog.py` con `"subdir": "microservicios/<proveedor>"`, y el puerto en `SUPPLIER_PORTS`.
4. En Serrucho Go, crear su hook y tarjeta como envoltorios de `useConsultaProveedor` y `ProveedorDisponibilidad`.

## Lo que hay que saber al operar

- **Reiniciar un microservicio:** matar su proceso; el watchdog lo relanza en ~30 s. Para recargar los cambios del watchdog hay que reiniciar solo el watchdog; `start_backend.vbs` mata todos los procesos, incluidos los write-back que mueven el mouse en HybridLite.
- **Primera consulta tras arrancar Maxcam:** tarda ~75 s (construye su índice). El listener espera hasta 130 s.
- **Corporación Norte y el VPN:** el sitio responde 403 a IPs de VPN; con el VPN activo la API sirve el último `catalogo.json` y lo marca `en_vivo: false`.
- **Logs:** `maxcam_listener.log` y `corpnorte_listener.log` en cada carpeta (ignorados por git).
