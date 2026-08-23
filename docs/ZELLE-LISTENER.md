# Listener de Zelle — Outlook → Supabase → App (notificación casi instantánea)

`zelle_listener.py` vigila el correo Outlook/Hotmail vía **Microsoft Graph API**
(polling por HTTPS, cada pocos segundos) y cada aviso de pago Zelle lo inserta en la
tabla `pagos_zelle` de Supabase. Un trigger de la DB dispara la Edge Function
`send-push`, que notifica a la app (El Serrucho to GO) en segundos.

```
Correo Zelle → polling Graph (HTTPS/443, ~5s) → parseo monto/remitente → INSERT pagos_zelle
            → trigger notify_push_zelle → Edge Fn send-push → 📱 push (admin/superempleado)
```

> **Por qué Graph y no IMAP.** El puerto IMAP (993) está bloqueado por el ISP de la
> tienda — se confirmó con pruebas de red (falla igual contra Outlook y contra Gmail,
> sin ninguna regla de firewall local ni módem intermedio de por medio). Microsoft
> Graph corre 100% sobre HTTPS/443, el mismo puerto que ya usa todo el resto del
> backend para hablar con Supabase, así que evita el problema de raíz sin depender
> del router ni de que el ISP abra un puerto especial. El costo es la latencia: en vez
> del push instantáneo de IMAP IDLE (~1-2s), aquí se consulta cada `ZELLE_POLL_INTERVAL_S`
> segundos (5 por defecto) — igual de "instantáneo" en la práctica (~5-10s de punta a
> punta contando el envío del push).

- Supervisado por `backend_watchdog.py` (se reinicia solo si muere).
- Dedupe por `Message-ID`: un correo reenviado/duplicado no genera doble push.
- Catch-up al arrancar: los correos que llegaron con el listener caído se
  recuperan (estado en `zelle_state.json`).
- Los correos NO se marcan como leídos (Graph solo los lee, nunca los modifica).

## Configuración inicial (una sola vez, ~10 min)

Microsoft eliminó la autenticación básica y los app passwords para cuentas
personales, así que hace falta OAuth2 con un "App Registration" gratuito:

### 1. Crear el App Registration en Azure

1. Entrar a https://entra.microsoft.com (sirve cualquier cuenta Microsoft, puede
   ser la misma de Hotmail) → buscar **App registrations** → **New registration**.
2. **Name**: `Serrucho Zelle Listener`.
3. **Supported account types**: elegir **"Personal Microsoft accounts only"**.
4. **Redirect URI**: dejar vacío. → **Register**.
5. En **Overview**, copiar el **Application (client) ID** (un UUID).
6. Ir a **Authentication** → bajar a **Advanced settings** →
   **Allow public client flows** → **Yes** → **Save**.
7. Ir a **API permissions** → **Add a permission** → pestaña **Microsoft APIs**
   → **Microsoft Graph** (la primera opción, ícono azul grande — no hay que
   buscarla) → **Delegated permissions** → escribir `Mail.Read` en el filtro →
   marcarlo → **Add permissions**.
   *(No hace falta "Grant admin consent" para cuentas personales — el propio
   usuario da el consentimiento durante el login del paso 3 de abajo.)*

### 2. Configurar el `.env`

En `C:\Proyect\backend serrucho\.env` agregar:

```
ZELLE_EMAIL=lacuenta@hotmail.com
ZELLE_CLIENT_ID=<el Application (client) ID copiado>
# opcionales (los defaults ya sirven para Bank of America):
ZELLE_TRUSTED_SENDERS=customerservice@ealerts.bankofamerica.com,onlinebanking@ealerts.bankofamerica.com
ZELLE_REQUIRE_DMARC=1
ZELLE_POLL_INTERVAL_S=5
```

**Filtrado anti-spoofing.** Solo se aceptan correos cuya dirección exacta esté en
`ZELLE_TRUSTED_SENDERS` **y** que hayan pasado DMARC (cabecera `Authentication-Results`
que agrega Outlook al recibir y un estafador no puede falsificar). Un correo con un
dominio casi-idéntico (`bankofamerlca.com`) o enviado desde otro servidor se descarta
y se registra como `[SPOOF?]` en el log.

**Clasificación.** Cada pago se marca como `recibido` (dinero depositándose, aviso de
`customerservice@`) o `en_revision` (retenido por el banco a la espera de revisión,
aviso de `onlinebanking@` con "pendiente de revisión"). La app los muestra separados.

**Alertas de intento de estafa.** Un correo que aparenta ser un aviso Zelle pero NO
pasa la barrera anti-spoofing (dirección o DMARC) se registra en
`alertas_zelle_spoof` con el motivo exacto (`dominio_no_autorizado`,
`dmarc_fallido`, `header_from_no_alinea`) y dispara un push distinto
("🚨 INTENTO DE ESTAFA DETECTADO") a **todos los empleados activos** (no solo
admin/superempleado — es un tema de seguridad de la tienda). En la app aparece en
la pestaña **SEGURIDAD** de Notificaciones. Suena más fuerte que el resto:
canal Android dedicado (`alerta-seguridad`, importancia MAX, vibración larga) y en
web se queda en pantalla hasta que alguien la descarta (`requireInteraction`).
Correos de remitente no confiable que ni siquiera parecen un Zelle (spam genérico)
se ignoran sin generar alerta.

### 3. Login inicial (device-code)

```powershell
cd "C:\Proyect\backend serrucho"
python zelle_listener.py --login
```

Muestra un código y la URL https://microsoft.com/devicelogin — abrirla,
pegar el código e **iniciar sesión con la cuenta Hotmail que recibe los Zelle**
(no con otra). El refresh token queda en `zelle_token_cache.json` y se renueva
solo mientras el listener corra.

### 4. Verificar y afinar el parser

```powershell
python zelle_listener.py --status     # config + token OK
python zelle_listener.py --probe 10   # parsea los últimos 10 correos SIN insertar
```

`--probe` muestra, por cada correo: si el remitente es CONFIABLE, su estado
(recibido / en_revision) y el monto/remitente extraídos. Si el banco usa otra
dirección, agregarla a `ZELLE_TRUSTED_SENDERS`; si cambia el formato del asunto,
avisar para ajustar el patrón del parser.

### 5. Arrancar en producción

```powershell
.\start_backend.vbs   # reinicia todo; el watchdog ya incluye zelle_listener.py
```

Log: `zelle_listener.log`. Si `.env` no tiene `ZELLE_CLIENT_ID`, el listener
duerme (no molesta) hasta que se configure.

## Prueba end-to-end

Enviarse a la cuenta un correo con asunto tipo `JUAN PEREZ sent you $1.00 with
Zelle` (o reenviarse un aviso real). En menos de ~10 s debe:
1. Aparecer la línea `ZELLE registrado: ...` en `zelle_listener.log`.
2. Existir la fila en `pagos_zelle` (Supabase).
3. Sonar la notificación en los teléfonos de admin/superempleado.
4. Verse el pago en la pantalla **Pagos Zelle** de la app.

## Problemas comunes

| Síntoma | Causa / solución |
|---|---|
| `--login` da error AADSTS7000218 o similar | Falta "Allow public client flows = Yes" (paso 1.6). |
| `--login` pide permisos y falla | Revisar que el permiso `Mail.Read` de Microsoft Graph esté agregado (paso 1.7). |
| `[AUTH] No se pudo obtener token` en el log | El refresh expiró (≥90 días sin correr). Borrar `zelle_token_cache.json` y repetir `--login`. |
| Detecta el correo pero `monto=None` (`raw_parse_ok=false`) | El formato del banco no matchea el regex. Correr `--probe` y ajustar patrones. |
| No llega el push pero la fila existe | Revisar logs de la Edge Function `send-push` en Supabase y que el teléfono tenga la suscripción en `push_subscriptions`. |
| `requests.exceptions.HTTPError: 403` en el log | El permiso `Mail.Read` no quedó bien agregado/consentido en Azure; repetir `--login` tras revisar el paso 1.7. |

## Seguridad

- `zelle_token_cache.json` da acceso de solo lectura práctica al correo:
  **no sale de esta PC** (no subir a git; ya está cubierto por `*.json` en `.gitignore`).
- El listener nunca modifica ni borra correos (Graph solo se usa para leer).
- Solo admin/superempleado reciben el push y ven los montos en la app (RLS).
