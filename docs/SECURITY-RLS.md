# SECURITY-RLS.md — Migración a `service_role` para escrituras

Este documento describe cómo activar el modo de escritura restringida en Supabase
para las tablas `productos`, `ventas`, `ventas_detalle`, `clientes`, `tazas` y
`comandos_remotos`, sin romper la sincronización actual.

Hoy (antes de esta migración) **todo** — lecturas y escrituras — se hace con la
**anon key**, y la RLS permite `FOR ALL` (INSERT/UPDATE/DELETE) con anon. Es
funcional pero inseguro si el proyecto se expone más allá de la red local: cualquiera
con la anon key (pública, embebida en apps/catálogo) podría escribir en las tablas.

El objetivo final: **lecturas siguen con anon** (el catálogo y apps externas no
cambian), pero **las escrituras solo las puede hacer quien tenga la `service_role`
key**, que vive únicamente en el `.env` de esta PC (`PRINCIPAL`).

## Pasos (en este orden exacto)

### 1. Copiar la `service_role` key del Dashboard al `.env`

1. Entrar a [Supabase Dashboard](https://supabase.com/dashboard) → proyecto
   `YOUR-PROJECT-REF` → **Settings → API**.
2. Copiar el valor de **service_role** (sección "Project API keys"). Es un JWT
   secreto — **nunca** lo subas a git, ni lo compartas, ni lo pongas en apps
   externas o en el catálogo público. Solo debe vivir en esta PC.
3. Abrir `C:\Proyect\backend serrucho\.env` (no `.env.example`) y agregar/editar
   la línea:
   ```
   SUPABASE_SERVICE_KEY=el-jwt-de-service-role-aqui
   ```
4. Guardar el archivo.

### 2. Reiniciar el backend

Cerrar los procesos `python.exe` / `pythonw.exe` de este proyecto y volver a
lanzar:
```
C:\Proyect\backend serrucho\start_backend.vbs
```
Esto asegura que `config.py` recargue el `.env` con la nueva variable.

### 3. Probar `python sync.py once`

Desde `C:\Proyect\backend serrucho`, con consola normal (no `pythonw`) para ver
la salida:
```powershell
python sync.py once
```
En este punto, la RLS **todavía no está endurecida** (sigue siendo `FOR ALL` con
anon), así que el sync debe funcionar exactamente igual que antes — solo que
ahora, internamente, ya está usando la `service_role` key para las escrituras
(gracias al fallback automático en `supabase_rest.py`, `sync_ventas.py`,
`remote_listener.py` y `rates_service.py`). Si esto falla, **no continuar** al
paso 4: revisar que la key copiada sea la correcta.

### 4. Ejecutar `sql/harden_rls.sql` en el SQL Editor de Supabase

Recién ahora, con el backend ya reiniciado y probado con la service key:

1. Abrir Supabase Dashboard → **SQL Editor**.
2. Pegar el contenido de
   [`sql/harden_rls.sql`](sql/harden_rls.sql) y ejecutarlo.
3. El script es idempotente (usa `DROP POLICY IF EXISTS` + `CREATE POLICY`), se
   puede correr más de una vez sin error.
4. Al final del script hay una consulta de verificación que lista las policies
   resultantes por tabla — confirmar que:
   - `SELECT` sigue disponible para todos (anon incluido) en las 6 tablas.
   - `INSERT/UPDATE/DELETE` en `productos`, `ventas`, `ventas_detalle`,
     `clientes`, `tazas` quedaron restringidos a `service_role`.
   - En `comandos_remotos`: `SELECT` e `INSERT` públicos, `UPDATE`/`DELETE`
     restringidos a `service_role`.

### 5. Volver a probar sync y el widget

```powershell
python sync.py once
python sync.py force
python test_conexion.py
```
Y revisar que el widget de escritorio (`widget.pyw`) siga mostrando estado
normal (bandeja del sistema, sin errores de conexión). Si el sync o el widget
muestran errores 401/403 después de este paso, ver la sección de rollback abajo.

## Cómo revertir (rollback)

Si algo falla después del paso 4, se puede volver a las políticas originales
(`FOR ALL` con `anon`) ejecutando esto en el SQL Editor de Supabase:

```sql
-- Rollback: vuelve a permitir escritura con anon en las 5 tablas principales
DROP POLICY IF EXISTS "Escritura service_role productos" ON public.productos;
CREATE POLICY "Escritura anon productos" ON public.productos
    FOR ALL USING (true) WITH CHECK (true);

DROP POLICY IF EXISTS "Escritura service_role ventas" ON public.ventas;
CREATE POLICY "Escritura anon ventas" ON public.ventas
    FOR ALL USING (true) WITH CHECK (true);

DROP POLICY IF EXISTS "Escritura service_role ventas_detalle" ON public.ventas_detalle;
CREATE POLICY "Escritura anon ventas_detalle" ON public.ventas_detalle
    FOR ALL USING (true) WITH CHECK (true);

DROP POLICY IF EXISTS "Escritura service_role clientes" ON public.clientes;
CREATE POLICY "Escritura anon clientes" ON public.clientes
    FOR ALL USING (true) WITH CHECK (true);

DROP POLICY IF EXISTS "Escritura service_role tazas" ON public.tazas;
CREATE POLICY "Escritura anon tazas" ON public.tazas
    FOR ALL USING (true) WITH CHECK (true);

-- Rollback de comandos_remotos: vuelve a permitir UPDATE/DELETE con anon
DROP POLICY IF EXISTS "Actualizacion service_role comandos_remotos" ON public.comandos_remotos;
DROP POLICY IF EXISTS "Borrado service_role comandos_remotos" ON public.comandos_remotos;
CREATE POLICY "Escritura anon comandos_remotos" ON public.comandos_remotos
    FOR ALL USING (true) WITH CHECK (true);
```

También se puede simplemente vaciar `SUPABASE_SERVICE_KEY=` en el `.env` y
reiniciar el backend: el código vuelve a usar la anon key para escrituras (por
el fallback automático), pero si la RLS ya quedó endurecida (paso 4 aplicado),
las escrituras con anon fallarán hasta aplicar el rollback SQL de arriba o
volver a completar la service key.

## Notas

- No hay `venv` en este proyecto; Python del sistema (`C:\Python314\python.exe`)
  en PATH como `python`.
- Los módulos que ya soportan el fallback automático anon → service_role son:
  `supabase_rest.py` (helper central `build_write_headers()`), `sync_ventas.py`,
  `remote_listener.py` y `rates_service.py`. Los endpoints de solo lectura
  (`app.py`, `network_util.py`, widgets) siguen usando anon siempre — no
  necesitan cambios.
- Si `SUPABASE_SERVICE_KEY` está vacía o no configurada, todo el comportamiento
  es idéntico al actual (anon key para todo). Es completamente opcional y no
  genera advertencias en consola si falta.
