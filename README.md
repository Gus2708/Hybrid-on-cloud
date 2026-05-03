# 🛠️ Backend Serrucho — Sistema de Inventario Inteligente

Bienvenido al núcleo del sistema de gestión de inventario para **Ferretería El Serrucho**. Este backend es una solución robusta diseñada para sincronizar en tiempo real el inventario local (HybridLite) con la nube (Supabase), proporcionando una API de alto rendimiento y una interfaz de monitoreo visual estilo iOS.

---

## 🚀 Resumen de Funcionalidades

Este sistema no es solo una API; es un ecosistema completo de sincronización y monitoreo:

1.  **Sincronización Incremental Inteligente**: Utiliza algoritmos de hashing MD5 para detectar cambios exactos en el `MAESTRO_ACTUAL.csv`, minimizando el tráfico de red y optimizando la velocidad.
2.  **Monitoreo en Tiempo Real**: Un servicio de vigilancia (`monitor.py`) detecta cambios en los archivos locales de la base de datos HybridLite y dispara actualizaciones automáticas.
3.  **Widget de Escritorio Premium**: Una interfaz minimalista con estética iOS que muestra el estado de la conexión, la última sincronización y permite disparar actualizaciones manuales.
4.  **Servicio de Tasas de Cambio**: Extracción automática de tasas oficiales del **BCV** y **Binance P2P** para mantener los precios en Bolívares siempre actualizados.
5.  **API REST de Alta Disponibilidad**: Búsqueda avanzada de productos con paginación, filtrado por stock y cálculo dinámico de precios.
6.  **Ejecución Silenciosa**: Scripts optimizados (`.vbs`) para correr en segundo plano sin interrumpir al usuario.

---

## 📁 Estructura del Proyecto

```text
backend serrucho/
├── app.py                # Servidor Flask (API y Orquestador)
├── sync.py               # Motor de sincronización CSV ↔ Supabase
├── monitor.py            # Vigilante de archivos locales (HybridLite)
├── rates_service.py      # Scraper de tasas BCV y Binance P2P
├── widget.pyw            # Interfaz de monitoreo visual (Estilo iOS)
├── config.py             # Gestión centralizada de configuración
├── supabase_rest.py      # Cliente de bajo nivel para Supabase REST
├── run_sync.bat          # Script de ejecución manual de sincronización
├── start_backend.vbs     # Lanzador invisible para servicios de fondo
├── sql/
│   ├── crear_tabla_productos.sql  # Schema de base de datos
│   └── crear_tabla_tazas.sql      # Schema para tasas de cambio
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

1.  **Detección**: El `monitor.py` vigila la fecha de modificación de los archivos HybridLite.
2.  **Comparación**: `sync.py` genera un hash de cada fila del CSV. Solo las filas cuyo hash ha cambiado o que no existen en la nube son enviadas.
3.  **Actualización**: Se realiza una operación `UPSERT` masiva en Supabase para maximizar la eficiencia.

---

## 🎨 El Widget (Serrucho Monitor)

El widget es una ventana flotante transparente que:
- **Punto Verde**: Todo sincronizado y online.
- **Punto Amarillo**: Sincronización en progreso o cambios pendientes.
- **Punto Rojo**: Error de conexión o servicio caído.
- **Glow Animado**: Pulso visual que indica actividad del sistema.
- **Integración con Tray**: Se minimiza a la barra de tareas para no estorbar.

---

## 🛡️ Mantenimiento y Solución de Problemas

- **Logs**: Revisa `monitor.log` para ver errores de sincronización.
- **Prueba de Conexión**: Ejecuta `python test_conexion.py` para diagnosticar problemas con Supabase.
- **Reinicio Forzado**: Cierra los procesos de Python en el administrador de tareas y vuelve a ejecutar `start_backend.vbs`.

---

Desarrollado con ❤️ para **Ferretería El Serrucho**.
