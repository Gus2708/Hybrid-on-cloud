# Reporte de Auditoría y Guía Técnica: Sincronización Remota

Este documento detalla el estado actual del sistema de sincronización del backend **El Serrucho**, los resultados de la auditoría de integridad de datos realizada el 8 de mayo de 2026, y el funcionamiento técnico de la conexión con Supabase.

---

## 1. Resultados de la Auditoría (Integridad de Datos)

Se ha realizado una validación cruzada entre los archivos fuente de **HybridLite (H:\)** y la base de datos en **Supabase**. Los resultados confirman una paridad del 100%.

| Entidad | Registros Locales | Registros en Nube | Estado |
| :--- | :---: | :---: | :---: |
| **Productos** | 7,212 | 7,212 | ✅ OK |
| **Ventas (Cabecera)** | 25,477 | 25,477 | ✅ OK |
| **Ventas (Detalle)** | 53,039 | 53,039 | ✅ OK |
| **Clientes** | 2,677 | 2,677 | ✅ OK |

> [!NOTE]
> La sincronización de ventas utiliza **tasas de cambio dinámicas** basadas en el campo `THT_FACTORREFERENCIAL` de cada factura, garantizando que los montos en USD en la nube coincidan con los reportes históricos de HybridLite.

---

## 2. Flujo de Sincronización Remota (Arquitectura)

La sincronización remota permite activar procesos desde una App móvil o web sin necesidad de que la PC tenga una IP pública o puertos abiertos (Port Forwarding).

### Diagrama del Proceso:
1. **Origen (App/Web)**: Inserta un registro en la tabla `comandos_remotos` de Supabase con `status = 'pendiente'`.
2. **PC Local (Remote Listener)**: El script `remote_listener.py` consulta la tabla cada 10 segundos.
3. **Ejecución Local**: Al detectar un comando, el listener hace una petición POST interna a `http://localhost:5000/api/v1/sync/...`.
4. **Respuesta**: El script local ejecuta `sync.py` o `sync_ventas.py` y devuelve el resultado al listener.
5. **Cierre de Ciclo**: El listener actualiza el registro en Supabase a `status = 'completado'` o `'error_local'`.

---

## 3. Configuración de Conexión Supabase

### Tabla: `comandos_remotos`
Esta tabla actúa como una cola de mensajes (Message Queue).

| Columna | Tipo | Descripción |
| :--- | :--- | :--- |
| `id` | bigint | Autoincremental (Primaria). |
| `comando` | text | Acción a realizar (`sync_inventory`, `sync_sales`, `sync_all`). |
| `status` | text | Estado del comando (`pendiente`, `ejecutando`, `completado`, `error_local`). |
| `creado_en` | timestamptz | Fecha de creación del comando. |
| `ejecutado_en` | timestamptz | Fecha de última actualización del script local. |

### Políticas de Seguridad (RLS)
Para que el backend pueda funcionar con la `ANON_KEY`, se configuraron las siguientes reglas:
*   **SELECT**: Permitido para el rol `anon` si el estado es `pendiente`, `ejecutando`, `completado` o `error_local`.
*   **UPDATE**: Permitido para el rol `anon` solo si el estado actual es `pendiente` o `ejecutando`.
*   **INSERT**: Restringido a usuarios autenticados (App Móvil).

---

## 4. Troubleshooting (Solución de Problemas)

Si la sincronización no responde:

1. **Verificar el Listener**: Revisa el archivo `sync_remote.log`. Debe mostrar "Detectados X comandos" o "Conectado a...".
2. **Verificar API Local**: Abre `http://localhost:5000/` en el navegador de la PC. Debería mostrar un JSON con `status: running`.
3. **Reiniciar Servicios**: Ejecuta `start_backend.vbs` para asegurar que todos los procesos (`app.py`, `monitor.py`, `remote_listener.py`) se reinicien limpiamente.
4. **Logs del Monitor**: Revisa `monitor.log` para ver si los cambios en los archivos `.dat` de HybridLite están siendo detectados.

---
*Auditoría realizada por Antigravity AI - 08/05/2026*
