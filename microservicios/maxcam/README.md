# Microservicio Maxcam

API local que consulta el catálogo del proveedor **Maxcam** (https://catalogo.maxcam.com/) y responde si un producto agotado en la ferretería está disponible en **Barquisimeto (BQ)** para pedirlo.

Forma parte del backend (`microservicios/maxcam/`): lo levanta y vigila `backend_watchdog.py` junto con su listener, usa `config` y `supabase_rest` del backend y solo escucha en `127.0.0.1:5001`. Serrucho Go lo consulta por la tabla puente `consultas_maxcam` (sección 7). Visión general: [../README.md](../README.md).

Los comandos de este README se ejecutan desde esta carpeta (`cd microservicios/maxcam`).

## 1. Cómo funciona

El catálogo de Maxcam es una SPA que habla con Supabase (RPC `catalogo_contexto`). Exige sesión: sin login, la base responde `permission denied`. Esta API inicia sesión con el correo del negocio y reutiliza esas mismas RPC.

```
Serrucho Go / otro cliente
        │  HTTP
        ▼
maxcam_api.py (Flask, :5001) ──► índice hash (maxcam_index.py)
        │                          código → SKU, O(1)
        │  stock en vivo
        ▼
Supabase de Maxcam  ◄── maxcam_auth.py (OTP por correo, token renovable)
```

| Archivo | Rol |
| :--- | :--- |
| `maxcam_api.py` | API Flask. Endpoints de la sección 3. |
| `maxcam_auth.py` | Login por código de correo y renovación automática del token. |
| `maxcam_index.py` | Índice hash del catálogo: busca por código en O(1) al momento de la consulta. |
| `embed_maxcam.py` | Embebe el catálogo y sube los vectores a `maxcam_embedding` (Supabase del Serrucho). |
| `build_equivalencias.py` | Genera `equivalencias.csv` (Serrucho → Maxcam) para revisión manual. |
| `maxcam_listener.py` | Responde las consultas de Serrucho Go (tabla puente `consultas_maxcam`). |
| `../../sql/crear_maxcam_embedding.sql` | Tabla `maxcam_embedding` y función `maxcam_equivalentes`. |
| `../../sql/crear_consultas_maxcam.sql` | Tabla puente `consultas_maxcam`. |

## 2. Sesión y configuración

Maxcam envía un código al correo del negocio (login OTP de Supabase). Se hace una sola vez:

```bash
python maxcam_auth.py request        # envía el código al correo
python maxcam_auth.py verify 123456  # canjea el código por una sesión
```

- La sesión queda en `session.json`; el access token dura ~1 h y se **renueva solo** con el refresh token. Solo se repite el código si la sesión queda muchos días sin uso.
- Variables en `.env` (nunca se versiona, junto con `session.json`): `SUPABASE_URL`, `SUPABASE_KEY`, `MAXCAM_RIF`, `MAXCAM_EMAIL`, y para los embeddings `OPENROUTER_API_KEY`, `SERRUCHO_SUPABASE_URL`, `SERRUCHO_SERVICE_KEY` (opcional `EMBEDDING_MODEL`).

## 3. Endpoints (`http://localhost:5001`)

| Endpoint | Descripción |
| :--- | :--- |
| `GET /disponibilidad` | ¿Un producto está disponible en Maxcam BQ? Es el principal. |
| `GET /productos` | Búsqueda: `q`, `marca`, `rubro`, `rubro_hijo`, `precio_min`, `precio_max`, `disponibles`, `agotados`, `orden`, `pagina`, `por_pagina` (máx. 100). |
| `GET /productos/<sku>` | Un producto por SKU. |
| `GET /marcas` | Marcas con su cantidad de productos. |
| `GET /categorias` | Rubros y sub-rubros. |

### `/disponibilidad`

Parámetros: `codigo`, `referencia`, `barras` (se pueden repetir) y `descripcion` (respaldo).

```bash
curl "http://localhost:5001/disponibilidad?codigo=0-360"
```

```json
{
  "encontrado": true,
  "disponible": true,
  "stock_bq": 100.0,
  "metodo": "hash",
  "coincidio_con": "0-360",
  "sku": "0-360",
  "nombre": "ABRAMAGIC ROJO GRANO 100 x 5\" ABRACOL 0-360",
  "precio": 0.74,
  "cant_caja": 50,
  "stock_por_sucursal": [{ "sucursal": "BQ", "disponible": 100.0, "inventario_real": 103.0 }]
}
```

Reglas:
- **Solo cuenta Barquisimeto.** `disponible` es `true` únicamente si el stock `disponible` de BQ es mayor a 0. Guarenas y otras sucursales no atienden esta zona; aparecen en `stock_por_sucursal` solo como información.
- **Primero por hash.** Los códigos recibidos se buscan en el índice (SKU y código alterno de Maxcam). Si no hay coincidencia y viene `descripcion`, busca por texto y toma el primer resultado (`metodo: "texto"`). **Ese respaldo puede equivocarse de producto**: úsalo solo como pista.
- **El stock siempre es en vivo.** El índice solo resuelve código → SKU; el stock se pide a Maxcam en cada consulta.
- Si no hay coincidencia: `{"encontrado": false, "disponible": false}`.

El índice se reconstruye cada hora. La **primera consulta tras arrancar tarda ~76 s** (descarga los ~7500 productos); la API lo precarga al iniciar. Después responde en 1–2 s.

## 4. Integración al backend

`maxcam_api.py` está registrado en `backend serrucho/backend_watchdog.py` como "API Maxcam":

- El watchdog la levanta con `pythonw` (invisible) al iniciar el backend y la reinicia si cae.
- Si el puerto 5001 no responde ~60 s, la considera colgada y la reinicia.
- Vive en `microservicios/maxcam` y se lanza con la opción `subdir` del watchdog, igual que `hybrid_writeback`. El listener (`maxcam_listener.py`) se supervisa de la misma forma.
- El nombre del script es único a propósito: el watchdog identifica procesos por nombre, y un segundo `app.py` se habría confundido con la API del Serrucho (puerto 5000).

Operación:
- Reiniciar solo esta API: matar el proceso `maxcam_api.py`; el watchdog la relanza en ~30 s.
- Depurar: correr `python maxcam_api.py` en una terminal (con `pythonw` no hay salida).
- Reiniciar todo el backend: `start_backend.vbs` **mata todos los procesos**, incluidos los write-back que mueven el mouse en HybridLite. Preferible reiniciar solo el watchdog.

## 5. Equivalencias Serrucho → Maxcam

Los códigos del Serrucho casi no coinciden con los de Maxcam (≈390 de 7935). Para el resto hay dos recursos:

1. **`maxcam_equivalentes` (Supabase, embeddings).** Los 7502 productos de Maxcam están embebidos con el mismo modelo que `productos_embedding` (`text-embedding-3-small`, 1536 dimensiones). La función devuelve los candidatos más cercanos a un producto del Serrucho. Medido contra los casos con código en común: acierta en el primer candidato ~70 % y entre los tres primeros ~83 %. Muchos fallos eran etiquetas erróneas de la tabla de referencia, así que es una cota inferior.
2. **`equivalencias.csv`.** Tabla para revisar a mano. Solo conviene para los productos que se piden seguido; una equivalencia confirmada es más confiable que una sugerencia por similitud.

> **Importante:** el embedding encuentra el producto *parecido*, no necesariamente el *mismo* (por ejemplo, otro grano del mismo disco). Mostrar siempre el nombre de Maxcam para que una persona confirme.
>
> Si se cambia de modelo de embeddings hay que re-embeber **las dos tablas** (`productos_embedding` y `maxcam_embedding`); vectores de modelos distintos no son comparables.

Actualizar los vectores cuando cambie el catálogo (incremental por hash, cuesta centavos):

```bash
python embed_maxcam.py --dry   # qué haría y cuánto costaría
python embed_maxcam.py
```

## 6. Seguridad

- `maxcam_embedding` tiene RLS activado y **sin acceso para `anon`/`authenticated`**: son datos del proveedor, que exige login. Solo se escribe con la service key.
- `maxcam_equivalentes` es la única vía de lectura. Devuelve `sku`, `nombre`, `marca` y `similitud`; **no** precios ni stock.
- La API local no tiene autenticación: solo escucha en la PC. Si se expone fuera de la oficina, hay que protegerla.
- `.env`, `session.json`, `*.csv` y `maxcam_catalogo.json` están en `.gitignore`.

## 7. Uso desde Serrucho Go

Serrucho Go no llama a la API directamente (corre en `localhost:5001`, dentro de la red de la tienda). Usa una **tabla puente** en Supabase, así funciona desde cualquier lugar sin abrir puertos:

```
Serrucho Go ──► consultas_maxcam (Supabase) ──► maxcam_listener.py ──► maxcam_api.py (:5001)
        ▲                                              │
        └────────────── resultado (jsonb) ◄────────────┘
```

1. En el detalle de un producto agotado (`existencia <= 0`), la tarjeta **"Disponibilidad en Maxcam (BQ)"** tiene el botón *Consultar*. Es manual a propósito: cada consulta golpea el catálogo del proveedor.
2. La app inserta una fila en `consultas_maxcam` (o reutiliza una respuesta de los últimos 15 minutos).
3. `maxcam_listener.py` la toma, busca el producto en `productos` y resuelve el SKU de Maxcam: **primero por código exacto** (hash) y, si no hay coincidencia, por **embeddings** (`maxcam_equivalentes`, parecido mínimo 0.6, hasta 3 candidatos). Para cada candidato pide a la API el stock de BQ en vivo.
4. Escribe `resultado` (`metodo`, `candidatos` con nombre, SKU, parecido, precio, `stock_bq`, `disponible`) y la app lo lee cada 2.5 s. Si en 150 s no hay respuesta, la tarjeta avisa que el backend puede estar apagado.

Si el resultado salió por parecido y no por código, la tarjeta avisa que hay que **verificar que sea el mismo producto**: el embedding no distingue bien las medidas.

Código en Serrucho Go: `src/hooks/useConsultaProveedor.ts` (lógica compartida), `useMaxcamConsulta.ts` y `src/components/MaxcamDisponibilidad.tsx` (sobre `ProveedorDisponibilidad.tsx`).

Operación del listener:
- Log: `microservicios/maxcam/maxcam_listener.log`.
- Al arrancar devuelve a `pendiente` las filas que quedaron `procesando` si el proceso murió a medias, y borra las de más de 3 días.
- La primera consulta tras arrancar la API tarda ~75 s (construye el índice); el listener espera hasta 130 s.

## 8. Pendientes

- Probar la tarjeta en un dispositivo y el insert/lectura como empleado autenticado (hoy probado con la service key).
- Probar un reinicio completo de la PC para confirmar que el watchdog levanta todo solo.
- Revisar equivalencias de los productos que se piden seguido.
