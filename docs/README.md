# Documentación del Proyecto — Backend El Serrucho

Este directorio centraliza toda la documentación técnica, arquitectónica, operativa y de planificación del backend **El Serrucho**.

---

## Estructura de la Documentación

```text
docs/
├── arquitectura/              # Arquitectura de alto nivel y flujos de datos
├── guias/                     # Guías prácticas de integración y configuración
├── base-de-datos/             # Esquemas de Supabase, migraciones y seguridad RLS
├── auditorias-y-reportes/     # Auditorías técnicas, rendimiento y reportes de estado
├── soluciones-historicas/     # Registro histórico de fixes y soluciones implementadas
└── planes/                    # Planes de implementación técnica y seguimiento (001 a 021)
```

---

## 🏛️ [Arquitectura](arquitectura/)

Documentos sobre el diseño del sistema y los flujos de datos entre componentes locales y la nube.

| Documento | Descripción |
|-----------|-------------|
| [ARCHITECTURE.md](arquitectura/ARCHITECTURE.md) | Flujo general de sincronización: DBISAM (`H:\`) -> Transformación local -> Supabase. Diagramas y componentes. |

---

## 📖 [Guías de Integración y Configuración](guias/)

Manuales operativos y guías paso a paso para conectar aplicaciones clientes y servicios externos.

| Documento | Descripción |
|-----------|-------------|
| [API-SYNC-GUIDE.md](guias/API-SYNC-GUIDE.md) | Cómo disparar la sincronización desde clientes móviles vía API local (red de oficina) o comando remoto en la nube. |
| [INTEGRACION_SERRUCHO_GO.md](guias/INTEGRACION_SERRUCHO_GO.md) | Guía de consumo del historial de movimientos unificado (compras y ajustes) en la app móvil El Serrucho Go. |
| [REMOTE-CONTROL-SETUP.md](guias/REMOTE-CONTROL-SETUP.md) | Arquitectura y configuración de `comandos_remotos` en Supabase para control remoto fuera de la oficina. |
| [ZELLE-LISTENER.md](guias/ZELLE-LISTENER.md) | Configuración del listener de pagos Zelle con Microsoft Graph API (Outlook) y notificaciones casi instantáneas. |

---

## 🗄️ [Base de Datos y Seguridad](base-de-datos/)

Configuraciones del esquema en la nube, políticas de acceso y control de permisos.

| Documento | Descripción |
|-----------|-------------|
| [DATABASE_CHANGES_V2.md](base-de-datos/DATABASE_CHANGES_V2.md) | Evolución del esquema en Supabase V2: soporte para sincronización temporal precisa y métodos de pago. |
| [SECURITY-RLS.md](base-de-datos/SECURITY-RLS.md) | Migración a `service_role` para escrituras y políticas de Row Level Security (RLS) en Supabase. |

---

## 🔍 [Auditorías y Reportes Técnicos](auditorias-y-reportes/)

Informes detallados sobre rendimiento, latencia e integridad de datos.

| Documento | Descripción |
|-----------|-------------|
| [auditoria_y_mejoras_hybrid.md](auditorias-y-reportes/auditoria_y_mejoras_hybrid.md) | Auditoría de rendimiento del motor de write-back en HybridLiteOS, DBISAM streaming y batch pricing. |
| [AUDIT_REMOTE_SYNC.md](auditorias-y-reportes/AUDIT_REMOTE_SYNC.md) | Auditoría técnica de integridad de datos y conexión en la sincronización remota hacia Supabase. |
| [REPORT_BACKEND_FIX_V2.md](auditorias-y-reportes/REPORT_BACKEND_FIX_V2.md) | Informe de corrección de regresiones e inconsistencias en la sincronización del Widget V2. |

---

## 🛠️ [Soluciones Históricas](soluciones-historicas/)

Documentación de contexto sobre fixes críticos ya integrados en el código productivo.

| Documento | Descripción |
|-----------|-------------|
| [SOLUTION-PRICE.md](soluciones-historicas/SOLUTION-PRICE.md) | Registro de la corrección del cálculo de IVA (16%), redondeo y descuentos en el catálogo de productos. |
| [SOLUTION-SALES.md](soluciones-historicas/SOLUTION-SALES.md) | Registro de la auditoría y estabilización de la integridad de ventas y detalles de venta. |

---

## 📋 [Planes de Implementación](planes/)

Especificaciones técnicas previas a la implementación y seguimiento de mejoras progresivas.

| Documento | Descripción |
|-----------|-------------|
| [planes/README.md](planes/README.md) | Matriz completa de estado y dependencias de los planes 001 al 021. |
| [001-021](planes/) | Planes técnicos individuales (ej. corrección de tasas, autenticación por API key, desacople de listeners, etc.). |

---

## 📦 Documentación de Módulos Específicos

- [hybrid_writeback/README.md](../hybrid_writeback/README.md) — Motor de automatización y write-back hacia la interfaz de HybridLite (Delphi/Win32).
- [hybrid_writeback/diagnostico/README.md](../hybrid_writeback/diagnostico/README.md) — Scripts de diagnóstico y captura de estado para el motor de write-back.
