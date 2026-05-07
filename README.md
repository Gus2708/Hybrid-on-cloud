# 🛠️ Backend Serrucho — Sistema de Inventario Inteligente

Bienvenido al núcleo del sistema de gestión de inventario para **Ferretería El Serrucho**. Este backend es una solución robusta diseñada para sincronizar en tiempo real el inventario local (HybridLite) con la nube (Supabase), proporcionando una API de alto rendimiento y una interfaz de monitoreo visual estilo iOS.

---

## 🚀 Resumen de Funcionalidades

Este sistema no es solo una API; es un ecosistema completo de sincronización y monitoreo:

1.  **Sincronización Incremental Inteligente**: Utiliza algoritmos de hashing MD5 para detectar cambios exactos, minimizando el tráfico de red y optimizando la velocidad.
2.  **Motor de Ventas y Auditoría**: Sincronización automática de facturas convertidas a USD utilizando la tasa histórica real de cada transacción.
3.  **Robustez Industrial**: Implementación de bloqueos por PID (`lock_util.py`) y procesamiento de datos por flujos (streaming) para manejar archivos de gran tamaño (>200MB) sin saturar la memoria.
4.  **Monitoreo en Tiempo Real**: Un servicio de vigilancia (`monitor.py`) detecta cambios en HybridLite y dispara actualizaciones automáticas.
5.  **Widget de Escritorio Premium**: Interfaz minimalista estilo iOS para control visual del estado del sistema.
6.  **Servicio de Tasas**: Extracción automática de **BCV** y **Binance P2P** con sistema de rotación (actual/anterior).
7.  **Infraestructura de Pruebas**: Suite completa de tests con `pytest` para garantizar la estabilidad de la API y los motores de sync.

---

## 📁 Estructura del Proyecto

```text
backend serrucho/
├── app.py                # Servidor Flask (API y Orquestador)
├── sync.py               # Motor de sincronización de Inventario
├── sync_ventas.py        # Motor de sincronización de Ventas (USD)
├── extraer_ventas.py     # Extractor incremental de facturas desde .DAT
├── actualizar_inventario.py # Extractor de productos y precios (IVA 16% incl.)
├── monitor.py            # Vigilante de archivos locales (HybridLite)
├── rates_service.py      # Scraper de tasas BCV y Binance P2P
├── lock_util.py          # Gestión de bloqueos por PID para evitar solapamientos
├── widget.pyw            # Interfaz de monitoreo visual (Estilo iOS)
├── config.py             # Gestión centralizada de configuración
├── tests/                # Suite de pruebas unitarias e integración (pytest)
├── sql/                  # Migraciones y esquemas de base de datos
└── assets/               # Recursos visuales del widget
```

---

## 🛠️ Instalación y Configuración

### 1. Requisitos Previos
- Python 3.10 o superior.
- Una cuenta en Supabase con un proyecto activo.
- Acceso de lectura a los archivos `.Dat` de HybridLite.

### 2. Configuración del Entorno
Copia el archivo `.env.example` a `.env` y completa las variables:
```env
SUPABASE_REST_URL=https://tu-proyecto.supabase.co
SUPABASE_ANON_KEY=tu-anon-key
CSV_SOURCE_PATH=C:\Ruta\Al\MAESTRO_ACTUAL.csv
PORT=5000
```

### 3. Instalación de Dependencias
Ejecuta el siguiente comando en la terminal:
```powershell
pip install -r requirements.txt
```

### 4. Preparación de la Base de Datos
Importa los archivos SQL en el **SQL Editor** de Supabase para crear las tablas necesarias (`productos` y `tazas`).

---

## 🖥️ Uso del Sistema

### Ejecución de Servicios
Existen varias formas de iniciar el backend:

- **Modo Desarrollo**: `python app.py` (Muestra logs detallados).
- **Modo Fondo (Recomendado)**: Ejecuta `start_backend.vbs` para lanzar la API y el monitor de forma invisible.
- **Widget de Monitoreo**: Ejecuta `widget.pyw` para tener el panel visual en tu escritorio.

### API Endpoints Principales

| Método | Endpoint | Descripción |
| :--- | :--- | :--- |
| `GET` | `/api/v1/buscar?q=martillo` | Búsqueda global de productos. |
| `GET` | `/api/v1/producto/<id>` | Detalle de un producto por código o barra. |
| `GET` | `/api/v1/tasa` | Obtiene la tasa de cambio actual. |
| `POST` | `/api/v1/sync/run` | Fuerza una sincronización inmediata. |
| `GET` | `/health` | Estado de salud de los servicios. |

---

## 🔄 Lógica de Sincronización

El sistema utiliza un flujo de tres capas para garantizar la integridad de los datos:

1.  **Detección**: `monitor.py` vigila la fecha de modificación de los archivos `.Dat` de HybridLite.
2.  **Extracción e Integridad**: Los scripts `actualizar_inventario.py` y `extraer_ventas.py` filtran datos basura (anuladas, notas de entrega) y aseguran precios con IVA incluido.
3.  **Conversión USD**: Las ventas se convierten a dólares usando la tasa grabada en el momento de la factura (`THT_FACTORREFERENCIAL`).
4.  **Hashing MD5**: El sistema genera una "huella" de cada registro. Solo se envían cambios reales.
5.  **Streaming & Batch**: Se procesan los archivos en fragmentos (chunks) para no agotar la RAM y se suben a Supabase en lotes de 1,000 registros.

---

## 🎨 El Widget (Serrucho Monitor)

El widget es una ventana flotante transparente que:
- **Punto Verde**: Todo sincronizado y online.
- **Punto Amarillo**: Sincronización en progreso o cambios pendientes.
- **Punto Rojo**: Error de conexión o servicio caído.
- **Glow Animado**: Pulso visual que indica actividad del sistema.
- **Integración con Tray**: Se minimiza a la barra de tareas para no estorbar.

---

## 🧪 Infraestructura de Pruebas

El proyecto cuenta con una suite de pruebas para asegurar la calidad del código:

- **Ejecutar Pruebas**: `pytest`
- **Cobertura**: Las pruebas cubren la lógica de búsqueda, normalización de strings, configuración y respuesta de la API.

---

## 🛡️ Mantenimiento y Solución de Problemas

- **Logs**: Revisa `monitor.log` para ver errores de sincronización.
- **Prevención de Conflictos**: El sistema usa `lock_util.py` para evitar que dos procesos de sincronización corran al mismo tiempo.
- **Prueba de Conexión**: Ejecuta `python test_conexion.py` para diagnosticar problemas con Supabase.
- **Reinicio Forzado**: Si el widget se queda pegado, cierra los procesos `python.exe` y ejecuta `start_backend.vbs`.

---

Desarrollado con ❤️ para **Ferretería El Serrucho** por ***GusDev***.
