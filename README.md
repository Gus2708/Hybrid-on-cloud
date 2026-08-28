# 🛠️ Hybrid on Cloud — SaaS de Inventario & Ventas Inteligente

Bienvenido a **Hybrid on Cloud**, la solución definitiva para transformar sistemas locales **Hybrid Lite** en potentes plataformas en la nube. Este ecosistema permite la sincronización masiva de datos, monitoreo de ventas en tiempo real y gestión centralizada, todo bajo una arquitectura de **Marca Blanca (White-Label)** totalmente personalizable.

---

## 🚀 Nuevas Funcionalidades (v1.2.0)

1.  **Sincronización Multicapa**: Ya no solo sincronizamos el inventario. Ahora el sistema gestiona de forma incremental:
    - **📦 Inventario**: Precios, existencias y datos maestros.
    - **💰 Ventas**: Cabeceras de facturas y detalles de operaciones en tiempo real.
    - **👥 Clientes**: Sincronización del maestro de clientes para fidelización en la nube.
2.  **🔍 Análisis de Integridad (iOS Style)**: Nueva tarjeta expandible en el widget que permite verificar la salud de los datos. Compara registros locales vs. nube en segundos para asegurar que nada se pierda.
3.  **📡 Disparadores Remotos (Remote Sync)**: Capacidad de forzar sincronizaciones desde el Dashboard administrativo centralizado mediante un sistema de "Heartbeat" y triggers en Supabase.
4.  **📦 Instalador Profesional (Inno Setup)**: Distribución simplificada mediante un instalador estándar de Windows que configura rutas, accesos directos y permisos de forma automática.
5.  **💓 Sistema de Heartbeat & HWID**: Registro único por máquina (Hardware ID) que reporta versión del software, estado de conexión y última actividad al panel de control global.
6.  **🎛️ Configuración Avanzada (Wizard 2.0)**: Asistente visual mejorado para configurar múltiples rutas de bases de datos (`.dat`) y parámetros de marca blanca sin tocar código.

---

## 🎨 El Widget Monitor (Interfaz de Usuario)

El widget ha sido rediseñado para ofrecer una experiencia minimalista y funcional:

-   **Indicadores de Estado**: 
    - 🟢 **Verde**: Sistema sincronizado y saludable.
    - 🟡 **Amarillo**: Sincronización en curso o cambios locales pendientes.
    - 🔴 **Rojo**: Error de conexión o servicio local detenido.
-   **Monitor de Tasas**: Extracción en tiempo real de **BCV** y **Binance P2P**. Alerta visual de "Brecha" cambiaria (se torna rojo si la brecha es crítica).
-   **Card de Integridad**: Haz clic en el icono ▶ para desplegar el desglose detallado de registros locales vs. nube.
-   **Bandeja de Sistema (Tray)**: Operación 100% silenciosa. El widget se minimiza a la barra de tareas y cambia su icono por el logo de tu empresa.

---

## 🛠️ Instalación y despliegue

### 1. Para el Usuario Final
Ejecuta el archivo `Instalador_HybridOnCloud.exe`. El asistente te guiará para instalar la aplicación en tu PC. Al finalizar, el widget se iniciará automáticamente.

### 2. Configuración Inicial (Wizard)
Al abrir por primera vez, deberás indicar:
- **Datos de Marca**: Nombre de tu negocio y ruta de tu logo.
- **Rutas Críticas**: Ubicación de los archivos `TInventario.dat`, `Ventas.dat`, etc.
- **Arranque Automático**: Activa la casilla para que el sistema inicie siempre con Windows de forma invisible.

---

## 🔄 Detalles Técnicos (Developer Specs)

### Compilación y Empaquetado
El sistema utiliza **Nuitka** para una compilación de alto rendimiento en C++ y **Inno Setup** para el empaquetado:

```powershell
# Compilación del ejecutable principal
python -m nuitka --standalone --onefile --windows-console-mode=disable --windows-icon-from-ico=assets/icon.ico --include-data-dir=assets=assets --plugin-enable=tk-inter --msvc=latest widget.py
```

### Seguridad e Instancia Única
- **Socket Lock**: Previene múltiples ejecuciones en el puerto `58231`.
- **HWID Fingerprinting**: Generación de identificador único basado en componentes de hardware para gestión de licencias.
- **Service Bridge**: El widget se comunica con un backend local en Python (Flask) para operaciones pesadas de extracción de datos, garantizando que la UI nunca se bloquee.

---

Desarrollado con ❤️ por **Hybrid on Cloud Team**.

