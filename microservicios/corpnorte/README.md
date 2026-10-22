# Microservicio Corporación Norte

API local que consulta el catálogo del proveedor **Corporación Norte** (https://catalogocorporacionnorte.com/) y responde si un producto agotado en la ferretería tiene stock allí. Hermano de `microservicios/maxcam`: misma idea, otro proveedor.

Forma parte del backend (`microservicios/corpnorte/`): lo levanta y vigila `backend_watchdog.py` junto con su listener, usa `config` y `supabase_rest` del backend y solo escucha en `127.0.0.1:5002`. Visión general: [../README.md](../README.md). Los comandos de este README se ejecutan desde esta carpeta (`cd microservicios/corpnorte`).

## 1. Cómo funciona

El sitio publica una API PHP sin login:

- `productos.php?brand=cn&solo_cats=1` lista las 28 categorías.
- `productos.php?brand=cn&categoria=<nombre>` devuelve **todos** los productos de esa categoría (3141 en total).

Campos útiles: `codigo`, `nombre`, `precio` (USD), `stock` (número), `categoria`, `subcategoria`, `oferta`, `nuevo`. Tres campos tienen nombre engañoso: `composicion` guarda la **marca**, `colores` guarda las **piezas** ("7 PIEZAS") y `bulto` es la **venta mínima**. El campo `disponible` vale 1 en todos los productos, incluso sin stock, así que **no se usa**: `disponible` en esta API es `stock > 0`.

```
Serrucho Go ──► consultas_corpnorte (Supabase) ──► listener_corpnorte.py (backend)
                                                        │
                                   hash por código  /  embeddings (corpnorte_equivalentes)
                                                        ▼
                                          corpnorte_api.py (Flask, :5002)
                                                        │ stock en vivo
                                                        ▼
                                           catalogocorporacionnorte.com
```

| Archivo | Rol |
| :--- | :--- |
| `corpnorte_client.py` | Cliente del sitio. `CORPNORTE_OFFLINE=1` lo hace servir desde `catalogo.json`. |
| `corpnorte_index.py` | Índice hash código → producto. Arranca del snapshot y se refresca cada hora. |
| `corpnorte_api.py` | API Flask en el puerto 5002. |
| `snapshot.py` | Descarga todo el catálogo a `catalogo.json` (~15 s). |
| `embed_corpnorte.py` | Embebe el catálogo y sube los vectores a `corpnorte_embedding`. |
| `corpnorte_listener.py` | Responde las consultas de Serrucho Go (tabla puente `consultas_corpnorte`). |
| `corpnorte_env.py` | Lector del `.env` local del microservicio (no se llama `config` para no tapar el `config.py` del backend). |
| `../../sql/crear_corpnorte.sql` | Tabla de embeddings, función `corpnorte_equivalentes` y tabla puente `consultas_corpnorte`. |

## 2. Importante: la conexión

El sitio responde **403 a las IPs de VPN** (probado con Proton) aunque tu Chrome cargue con esa misma IP, y **200 desde la conexión normal de la PC de la tienda**. Por eso:

- `snapshot.py` y la API deben correr **con el VPN apagado**.
- Si la API corre con el VPN activo, no logra consultar el sitio y **sirve el último `catalogo.json`**: responde `en_vivo: false` y Serrucho Go lo muestra como "dato guardado, no en vivo".
- No se intenta disfrazar las peticiones para pasar el filtro.

## 3. Endpoints (`http://localhost:5002`)

| Endpoint | Descripción |
| :--- | :--- |
| `GET /disponibilidad?codigo=&referencia=&barras=` | ¿Hay stock? Busca los códigos en el índice y pide a la categoría del producto el stock actual. |
| `GET /productos?q=&marca=&categoria=&pagina=&por_pagina=` | Búsqueda en el índice (máx. 100 por página). |
| `GET /categorias` | Categorías y subcategorías con su cantidad. |
| `GET /marcas` | Marcas con su cantidad. |

Ejemplo de `/disponibilidad`:

```json
{ "encontrado": true, "disponible": true, "metodo": "hash", "en_vivo": true,
  "codigo": "DT05-MK0331", "nombre": "SET DE COPA DE SIERRA", "marca": "DIESEL TOOLS",
  "precio": 19, "stock": 26, "bulto": "1 Set", "piezas": "7 PIEZAS" }
```

Sin coincidencia: `{"encontrado": false, "disponible": false}`.

## 4. Equivalencias con el Serrucho

Solo **48 de 7935** productos del Serrucho comparten código con este catálogo, así que casi todo depende de **embeddings**. `corpnorte_equivalentes(codigo_interno, limite, umbral)` devuelve los productos más cercanos a uno del Serrucho (mismo modelo que `productos_embedding`). Es una sugerencia por parecido, no una certeza: la tarjeta de Serrucho Go lo avisa y muestra el porcentaje.

Si cambia el modelo de embeddings hay que re-embeber **las tres tablas** (`productos_embedding`, `maxcam_embedding`, `corpnorte_embedding`).

## 5. Puesta en marcha

1. Ejecutar `sql/crear_corpnorte.sql` (en la carpeta `sql/` del backend) en el SQL editor de Supabase.
2. Crear `microservicios/corpnorte/.env` con `OPENROUTER_API_KEY`, `SERRUCHO_SUPABASE_URL` y `SERRUCHO_SERVICE_KEY` (nunca se versiona; el `.gitignore` del backend ya lo cubre).
3. `python snapshot.py` (VPN apagado) y `python embed_corpnorte.py` (`--dry` para ver el costo, ~$0.001).
4. La API y el listener los levanta el watchdog del backend (`backend_watchdog.py`, opción `subdir`), igual que Maxcam.

## Operación

- Reiniciar solo esta API: matar el proceso `corpnorte_api.py`; el watchdog la relanza en ~30 s.
- Depurar: correr `python corpnorte_api.py` en una terminal (con `pythonw` no hay salida).
- Probar sin salir al sitio (por ejemplo con el VPN activo): `CORPNORTE_OFFLINE=1`.
- Log del listener: `corpnorte_listener.log` en esta carpeta.

## 6. Seguridad

- `corpnorte_embedding` y `consultas_corpnorte` tienen RLS: `anon` no ve nada; los empleados autenticados solo pueden crear consultas y leer respuestas.
- La API local no tiene autenticación: solo escucha en la PC.
- `.env`, `catalogo.json` y `*.har` están en `.gitignore`.

## 7. Pendientes

- Probar la tarjeta en un dispositivo y el insert/lectura como empleado autenticado (hoy probado con la service key).
- Revisar manualmente las equivalencias de los productos que se piden seguido.
