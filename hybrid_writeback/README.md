# Write-back: App El Serrucho Go → HybridLite (local)

Permite que, desde la app, se solicite un cambio de **precio** o **stock** y que el
backend lo aplique en el sistema local HybridLite **sin corromper la base de datos**.

---

## Por qué NO se editan los archivos directamente

HybridLite no usa archivos planos: usa **DBISAM 4** en modo **cliente/servidor**
(servidor `HybridServerDB.exe` en la máquina `PRINCIPAL`, puerto `12005`). Los
archivos `.Dat` que ves en `H:\` son una unidad de red mapeada a `\\PRINCIPAL\Happs`.

Editar esos `.Dat` a mano es inviable y peligroso porque:

| Obstáculo | Detalle |
|---|---|
| Librería de solo lectura | `pydbisam` solo decodifica; no escribe. |
| Checksums | Cada tabla tiene MD5 propio y cada fila un checksum de 16 bytes (algoritmo no documentado). |
| Índices `.Idx` | B-trees separados; la app busca por ellos, no por el dato crudo. |
| BLOBs `.Blb` | Campos largos en archivo aparte que debe quedar consistente. |
| **Servidor vivo** | `HybridServerDB.exe` tiene los archivos abiertos y cacheados. Escribir por debajo = corrupción segura. Existe `REPAIRFILE.CFG` (el motor valida/repara). |

**Conclusión:** la escritura segura debe pasar **por el motor**. Sin el driver ODBC
de DBISAM (de pago / detrás de login de Elevate), el único motor operable es la
**propia app HybridLite**, manejada por automatización de interfaz.

---

## Arquitectura

```
App Serrucho Go
   └─(insert)→ Supabase: tabla `cambios_solicitados` {tipo, codigo, valor/delta, motivo}
                   └─(poll)→ listener_writeback.py  (corre en DESKTOP-U9B6562)
                                 └→ hybrid_ui.py  (pywinauto maneja HybridLitePro)
                                       └→ la app hace el UPDATE/ajuste por el motor ✅
                   ←(patch status: aplicado/error)─┘
   El sync normal (sync.py) sube luego el cambio confirmado a la tabla `productos`.
```

### Archivos
| Archivo | Rol |
|---|---|
| `schema.sql` | Crea la tabla `cambios_solicitados` en Supabase. |
| `inspect_hybrid.py` | **Solo lectura.** Vuelca ventanas/controles de la app para calibrar. |
| `hybrid_ui.py` | Escritor pywinauto: `set_price()` y `adjust_stock()`. DRY-RUN por defecto. |
| `listener_writeback.py` | Sondea Supabase y despacha al escritor. Corre junto a `remote_listener.py`. |

---

## Estado actual

- [x] Pipeline app→Supabase→backend→escritor montado y probado en **DRY-RUN**.
- [x] Esquema SQL listo.
- [x] Inspector de UI funcionando.
- [ ] **Crear la tabla en Supabase** (ejecutar `schema.sql`).
- [ ] **Calibrar los pasos de UI** (`# >>> CALIBRAR <<<` en `hybrid_ui.py`) — requiere la app abierta.
- [ ] Probar con UN producto y luego habilitar escritura real.

---

## Puesta en marcha

### 1. Crear la tabla en Supabase
Pega `schema.sql` en *Supabase → SQL Editor* y ejecútalo.

### 2. Calibrar (requiere la app abierta y con sesión)
```powershell
# 1) Abre HybridLitePro e inicia sesión
# 2) Vuelca la estructura de la pantalla de edición de precio:
cd "C:\Proyect\backend serrucho\hybrid_writeback"
python inspect_hybrid.py --tree --snapshot
# 3) Repite navegando a "Ajuste de inventario" y vuelve a volcar.
```
Con esos volcados se rellenan las secciones `# >>> CALIBRAR <<<` de `hybrid_ui.py`
(menús, campos de búsqueda, campo de precio, botón Guardar, etc.).

### 3. Probar sin riesgo (DRY-RUN)
```powershell
python listener_writeback.py --once
```
Inserta una fila de prueba en `cambios_solicitados` y verifica que el log diga
`[DRY_RUN] cambiaría precio ...` y que la fila pase a `aplicado`.

### 4. Habilitar escritura real (solo cuando esté calibrado y con respaldo)
```powershell
$env:HYBRID_WRITE_ENABLED = "1"
python listener_writeback.py
```

### 5. Dejarlo corriendo
Igual que el backend actual: añade `listener_writeback.py` al arranque
(junto a `remote_listener.py`), o créale un acceso en `start_backend.vbs`.

---

## Notas de seguridad

- **Respaldos:** ya hay Cobian Reflector en la máquina. Asegúrate de tener un
  respaldo reciente de `H:\HybridLite\HybridEmpresa\HybridDataBase` antes de la
  primera prueba real.
- **Precio = seguro** (campo de valor). **Stock = como ajuste**, nunca sobrescribir
  el saldo: por eso `adjust_stock()` exige `motivo` y se hará con el documento de
  ajuste de la app (respeta kardex y auditoría).
- **Un cambio a la vez:** el listener procesa secuencialmente para no pelear con
  la app. No está pensado para cargas masivas.
- **Variables de entorno** (opcionales): `HYBRID_WRITE_ENABLED`, `HYBRID_APP_EXE`,
  `HYBRID_UI_USER`, `HYBRID_UI_PASS`, `HYBRID_UI_BACKEND` (win32|uia).
```
