# 📡 Configuración de Control Remoto (Cloud-to-Local)

Este documento explica cómo funciona la arquitectura que permite activar la sincronización desde cualquier red (fuera de la oficina).

## 1. Infraestructura en la Nube (Supabase)
Se utiliza una tabla llamada `comandos_remotos` como puente de comunicación.

*   **Tabla**: `comandos_remotos`
*   **Campos**:
    *   `comando`: El nombre de la acción (ej: `sync_all`).
    *   `status`: El estado del ciclo de vida (`pendiente` -> `ejecutando` -> `completado`).
    *   `creado_en`: Timestamp de la solicitud.

## 2. Componente Local (`remote_listener.py`)
Es un servicio en segundo plano que corre en la PC de la oficina y realiza las siguientes acciones:
1.  Consulta la tabla `comandos_remotos` cada 10 segundos buscando registros `pendiente`.
2.  Al encontrar uno, cambia su estado a `ejecutando`.
3.  Envía un "ping" al servidor local Flask (`localhost:5000/api/v1/sync/run`).
4.  Una vez que la sincronización termina, marca el comando como `completado`.

## 3. Beneficios de esta Arquitectura
*   **Seguridad**: No requiere abrir puertos en el Router de la empresa.
*   **Omnipresencia**: Funciona desde cualquier red (WiFi, 4G/5G).
*   **Feedback Visual**: El Widget local detecta la actividad y muestra el progreso en pantalla.
*   **Instancia Única**: El sistema tiene un bloqueo de socket para evitar que se abran múltiples ventanas del widget.

---
*Implementado el 07/05/2026 para el Proyecto El Serrucho.*
