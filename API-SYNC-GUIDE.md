# 📱 Guía de Integración: Android -> El Serrucho Widget

Esta guía explica cómo enviar comandos de sincronización desde tu aplicación móvil al Widget de escritorio.

## 🔗 Opción 1: Red Local (Directo)
*   **URL**: `http://[IP_DE_TU_PC]:5000/api/v1/sync/run`
*   **Método**: `GET` o `POST`

---

## ☁️ Opción 2: Diferentes Redes (Vía Cloud)
Si estás fuera de la oficina, no uses la IP. Inserta un comando en la tabla de Supabase:

*   **Tabla**: `comandos_remotos`
*   **Acción**: INSERT
*   **Payload**: `{"comando": "sync_all"}`

El Widget en la oficina detectará el registro en ~10 segundos y comenzará la sincronización automáticamente.

---

## 🛠️ Ejemplo de Implementación Remota (Kotlin + Supabase SDK)

Usando la librería **OkHttp**:

```kotlin
val client = OkHttpClient()
val request = Request.Builder()
    .url("http://192.168.1.143:5000/api/v1/sync/run") // Usa la IP que ves en el Widget
    .build()

client.newCall(request).enqueue(object : Callback {
    override fun onResponse(call: Call, response: Response) {
        val body = response.body?.string()
        println("Sincronización iniciada: $body")
    }
    
    override fun onFailure(call: Call, e: IOException) {
        println("Error al conectar con la PC: ${e.message}")
    }
})
```

## 📊 Endpoints de Consulta (Opcionales)

| Endpoint | Método | Descripción |
| :--- | :--- | :--- |
| `/api/v1/sync/status` | `GET` | Devuelve los contadores de productos y ventas (Local vs Nube). |
| `/api/v1/productos?q=MARTILLO` | `GET` | Busca un producto en el inventario local de la PC. |
| `/api/v1/sync/run` | `POST` | Dispara la sincronización completa (Inventario + Ventas). |
| `/api/v1/sync/inventory` | `POST` | Sincroniza **solo** el inventario de productos. |
| `/api/v1/sync/sales` | `POST` | Sincroniza **solo** las ventas históricas y del día. |
| `/api/v1/tasa` | `GET` | Retorna la tasa actual BCV y Binance. |

## ⚠️ Requisitos para la Conexión

1.  **Misma Red**: El teléfono Android debe estar en el mismo WiFi que la computadora.
2.  **Puerto 5000**: Asegúrate de que el firewall de Windows permita tráfico entrante en el puerto 5000.
3.  **IP Estática (Recomendado)**: Si puedes, configura tu PC con una IP fija en el router para que no cambie y tu app no pierda la conexión.

---
*Configuración actual detectada: IP 192.168.1.143*
