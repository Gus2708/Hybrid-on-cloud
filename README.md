# 🛠️ Backend Serrucho — Sistema de Sincronización y Writeback Inteligente

Bienvenido al núcleo del sistema de gestión de inventario y automatización para **Ferretería El Serrucho**. Este backend es la infraestructura crítica que conecta la base de datos local del POS de escritorio (**HybridLite / DBISAM 4**) con la nube (**Supabase**) en ambas direcciones (Sincronización de lectura + Writeback de escritura por automatización UI).

---

## 🚀 Resumen de Funcionalidades

1. **Write-back por Input Real de Hardware (`hybrid_writeback/`)**: Ejecuta operaciones solicitadas desde la App (El Serrucho Go) en una **instancia aislada de HybridLite** mediante simulación de eventos nativos Win32 (`SendInput`).
2. **5 Listeners 24/7 Supervisados por Watchdog**:
   - `listener_writeback.py`: Ajustes de stock por kardex en lote, actualización de precios en USD, costos y ficha.
   - `listener_compras.py`: Recepción de mercancía y alta automática de productos nuevos en el catálogo.
   - `listener_pedidos.py`: Carga de notas de entrega para cobro ultra-rápido en la caja registradora.
   - `listener_directorio.py`: Alta de fichas de clientes y proveedores con código derivado/autoasignado.
   - `zelle_listener.py`: Monitoreo en tiempo real de correos de Bank of America via Microsoft Graph API para alertas push instantáneas.
3. **Control de Seguridad de Hardware (`safety_control.py`)**:
   - Mutex global nativo Win32 (`Local\SerruchoBotMouseLock`) que evita colisión de mouse entre listeners.
   - Banner visible superior (Topmost Window) avisando la ejecución en vivo.
   - Hotkey de emergencia **F12** para abortar el proceso inmediatamente.
   - Bloqueo de periféricos (`BlockInput`) en ejecución con privilegios.
4. **Sincronización Incremental de Lectura (Sync-Espejo)**: Detección por hashing MD5 para subir facturas, productos, clientes y tasas a Supabase en lotes de 1,000 registros.
5. **Supervisor 24/7 (`backend_watchdog.py`)**: Mantiene todos los procesos vivos continuamente en la PC de la oficina de la tienda.
6. **Integración de Memoria Persistente (`Engram`)**: Registra la evolución técnica, parches y decisiones arquitectónicas en la base de datos de memoria persistente para agentes AI (`.engram/engram.db`).

---

## 📁 Estructura del Proyecto

```text
backend serrucho/
├── backend_watchdog.py       # Supervisor 24/7 que relanza listeners caídos
├── hybrid_writeback/         # Paquete Motor de Writeback UI
│   ├── listener_writeback.py # Pipeline stock (kardex), precio, costo y ficha
│   ├── listener_compras.py   # Pipeline recepción de compras + productos nuevos
│   ├── listener_pedidos.py   # Pipeline notas de entrega para caja
│   ├── listener_directorio.py# Pipeline alta de clientes y proveedores
│   ├── flujo_stock_real.py   # Coreografía SendInput de stock (single y lote)
│   ├── flujo_precio_real.py  # Coreografía SendInput de Ficha (precios/costos)
│   ├── flujo_compra_real.py  # Coreografía SendInput de Compras
│   ├── flujo_pedido_real.py  # Coreografía SendInput de Pedidos
│   ├── flujo_directorio_real.py # Coreografía SendInput de Clientes/Proveedores
│   ├── realinput.py          # Motor de input nativo Win32 (SendInput numpad)
│   ├── abrir_hybrid.py       # Instancia aislada de HybridLite con login automático
│   ├── safety_control.py     # Mutex Win32, Banner Topmost, F12 Hotkey, BlockInput
│   └── README.md             # Documentación técnica detallada del paquete
├── zelle_listener.py         # Polling MS Graph API OAuth2 de correos Bank of America
├── app.py                    # Servidor Flask (API local y Orquestación)
├── sync.py                   # Sincronización de inventario (DBISAM -> Supabase)
├── sync_ventas.py            # Sincronización de ventas y facturas en USD
├── sync_ajustes.py           # Sincronización espejo de movimientos locales
├── extraer_ventas.py         # Extractor incremental de facturas desde .DAT
├── actualizar_inventario.py   # Extractor de productos y precios (IVA 16% incl.)
├── monitor.py                # Vigilante de cambios en archivos .DAT
├── rates_service.py          # Scraper de tasas BCV y Binance P2P
├── lock_util.py              # Gestión de bloqueos por PID
├── widget.pyw                # Widget de escritorio estilo iOS para monitoreo
├── config.py                 # Central de credenciales y variables de entorno
└── tests/                    # Suite de pruebas unitarias (pytest)
```

---

## 🛠️ Instalación y Configuración

### 1. Requisitos Previos
- Python 3.10+ (32-bit/64-bit compatible con `SendInput`).
- HybridLite instalado localmente (`C:\HybridLiteEstacion` / datos en `H:\`).
- Credenciales en Supabase (`SUPABASE_REST_URL`, `SUPABASE_SERVICE_KEY`).
- Cliente [Engram](https://github.com/Gentleman-Programming/engram) instalado en el sistema.

### 2. Configuración del Entorno (`.env`)
```env
SUPABASE_REST_URL=https://tu-proyecto.supabase.co
SUPABASE_SERVICE_KEY=tu-service-role-key # Requerido para bypass RLS en colas writeback
HYBRID_WRITE_ENABLED=1                    # Habilita escrituras reales (0 = PREVIEW)
HYBRID_WRITE_WINDOW=19:00-07:00           # Ventana horaria de ejecución (fuera de tienda)
```

---

## 🖥️ Arquitectura de Ejecución 24/7

### 1. Bucle Principal con Watchdog
Para iniciar toda la infraestructura de la tienda:
```powershell
python backend_watchdog.py
```
El watchdog arrancará y mantendrá en ejecución constante:
* `listener_writeback.py`
* `listener_compras.py`
* `listener_pedidos.py`
* `listener_directorio.py`
* `zelle_listener.py`
* `monitor.py`

### 2. Pruebas y Previsualización Manual (Modo Safe)
Puedes probar cualquier listener individualmente en modo **PREVIEW** (navega y verifica en pantalla sin hacer commit):
```powershell
python hybrid_writeback/listener_writeback.py --once
```

---

## 🛡️ Invariantes de Seguridad del Writeback (NUNCA romper)

1. **Nunca editar `.Dat` a mano**: DBISAM 4 requiere pasar por el motor de HybridLite para mantener checksums, BLOBs e índices B-tree consistentes.
2. **Instancia Aislada**: Toda automatización corre sobre su propia ventana aislada (`abrir_hybrid.py`), nunca sobre la sesión de trabajo del empleado/cajero.
3. **Etapas Ambiguas NO son Reintentables**: Si una orden de cambio falla *post-commit*, pasa inmediatamente a `error` para evitar duplicar deltas de stock.
4. **Mutex de Periféricos**: Ningún script puede tocar el mouse/teclado sin obtener primero `Local\SerruchoBotMouseLock`.

---

## 🧠 Integración con Engram Memory
El backend utiliza **Engram** para guardar descubrimientos técnicos, calibraciones de formularios Delphi y soluciones a incidencias. Para buscar memorias relevantes del backend desde la terminal:
```powershell
engram search "writeback"
engram search "hybrid"
```

---

Desarrollado con ❤️ para **Ferretería El Serrucho** por ***GusDev***.
