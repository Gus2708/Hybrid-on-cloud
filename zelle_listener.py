"""
zelle_listener.py — Vigila el correo Outlook via Microsoft Graph API (polling HTTPS)
y sube pagos Zelle a Supabase.

Flujo: correo llega al inbox -> polling cada pocos segundos sobre Graph (HTTPS/443)
-> se filtra/parsea (monto, remitente) -> INSERT en pagos_zelle -> el trigger de la DB
dispara la Edge Function send-push -> notificacion en la app en segundos.

Por que Graph y no IMAP: el puerto IMAP (993) esta bloqueado por el ISP de la tienda
(confirmado: falla igual contra Outlook y contra Gmail, sin ninguna regla de firewall
local ni doble NAT de por medio). Microsoft Graph corre 100% sobre HTTPS/443 — el mismo
puerto que ya usa el resto del backend para hablar con Supabase — asi que evita el
problema de raiz sin depender del router ni de que el ISP abra un puerto.

Autenticacion: OAuth2 con msal — Microsoft elimino la autenticacion basica y los app
passwords para cuentas personales de outlook.com/hotmail.com. Requiere un App
Registration gratuito en Azure (ver ZELLE-LISTENER.md) y un login inicial:

  python zelle_listener.py --login    # device-code flow, una sola vez
  python zelle_listener.py --status   # estado de config y token
  python zelle_listener.py --probe 10 # parsea los ultimos N correos SIN insertar (tuning)
  python zelle_listener.py            # correr el listener (lo lanza backend_watchdog.py)

El refresh token se renueva solo mientras el listener corra (cache en
zelle_token_cache.json). Si el listener no esta configurado, duerme sin
reiniciarse en bucle para no ensuciar el log del watchdog.
"""
import os
import sys

if sys.executable.lower().endswith("pythonw.exe"):
    try:
        sys.stdout = open(os.devnull, "w")
        sys.stderr = open(os.devnull, "w")
    except: pass

import re
import json
import time
import email
import email.policy
import email.utils
import datetime
import requests

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
LOG_FILE = os.path.join(BASE_DIR, "zelle_listener.log")
TOKEN_CACHE_FILE = os.path.join(BASE_DIR, "zelle_token_cache.json")
STATE_FILE = os.path.join(BASE_DIR, "zelle_state.json")

_MAX_LOG_BYTES = 5 * 1024 * 1024

AUTHORITY = "https://login.microsoftonline.com/consumers"  # cuentas personales MSA
SCOPES = ["https://graph.microsoft.com/Mail.Read"]
GRAPH_BASE = "https://graph.microsoft.com/v1.0"

SNIPPET_LEN = 500
NOT_CONFIGURED_SLEEP_S = 3600


def _rotate_log():
    try:
        if os.path.exists(LOG_FILE) and os.path.getsize(LOG_FILE) > _MAX_LOG_BYTES:
            bak = LOG_FILE + ".1"
            if os.path.exists(bak): os.remove(bak)
            os.rename(LOG_FILE, bak)
    except: pass


def log(message):
    timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    safe_message = str(message).encode("ascii", "replace").decode("ascii")
    print(f"[{timestamp}] {safe_message}")
    try:
        _rotate_log()
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(f"[{timestamp}] {message}\n")
    except Exception as e:
        print(f"Error escribiendo en log: {e}")


try:
    import config
except ImportError:
    print("Error: Archivo 'config.py' no encontrado.")
    sys.exit(1)


# ─── Parseo de correos Zelle (funciones puras, cubiertas por tests) ───────────
# No dependen de como se obtuvo el correo (IMAP, Graph, etc.) — operan sobre bytes
# RFC822 crudos. Se mantienen sin cambios respecto a la version IMAP.

# Patrones de parseo, confirmados con correos reales (--probe) de Bank of America
# en español. Dos tipos de aviso Zelle nos interesan:
#   • Recibido (deposito): De customerservice@ealerts.bankofamerica.com
#     Asunto "NOMBRE le envió $MONTO" — el dinero cae en ~5 min.
#   • En revisión (retenido): De onlinebanking@ealerts.bankofamerica.com
#     Asunto "Un pago de Zelle ... pendiente de revisión"; el monto/nombre van en
#     el CUERPO ("Su pago de NOMBRE ... Cantidad $MONTO").
_RE_MONTO = re.compile(r"\$\s*([0-9][0-9,]*(?:\.[0-9]{1,2})?)")
_RE_REMITENTE = [
    re.compile(r"^(.*?)\s+sent you", re.IGNORECASE),                     # "JUAN PEREZ sent you $50.00"
    re.compile(r"^(.*?)\s+(?:te|le)\s+envi[oó]", re.IGNORECASE),    # "JUAN PEREZ le envió $50.00" (recibido)
    re.compile(r"Su pago de\s+(.+?)\s+a trav[eé]s de", re.IGNORECASE),   # cuerpo BofA "en revisión"
    re.compile(r"\bDesde\s+(.+?)\s+Cantidad", re.IGNORECASE),            # cuerpo BofA "en revisión" (respaldo)
    re.compile(r"received\s+\$[0-9.,]+\s+from\s+(.+?)[\.\r\n]", re.IGNORECASE),
    re.compile(r"recibiste\s+\$[0-9.,]+\s+de\s+(.+?)[\.\r\n]", re.IGNORECASE),
    re.compile(r"\bfrom\s+([A-Z][A-Za-z .'\-]{2,60}?)(?:\s+is now available|[\.\r\n])"),
]

# Pago Zelle RECIBIDO (dinero depositándose): "NOMBRE le/te envió $N" o "sent you $N".
_RE_ZELLE_PAGO = re.compile(r"(?:te|le)\s+envi[oó]\s+\$\s*[0-9]|sent you\s+\$\s*[0-9]", re.IGNORECASE)
# Pago Zelle RETENIDO por el banco a la espera de revisión.
_RE_ZELLE_REVISION = re.compile(r"pendiente de revisi[oó]n", re.IGNORECASE)


def parsear_monto(texto):
    """Extrae el primer monto $X del texto. Devuelve float o None."""
    if not texto:
        return None
    m = _RE_MONTO.search(texto)
    if not m:
        return None
    try:
        return float(m.group(1).replace(",", ""))
    except ValueError:
        return None


def parsear_remitente(asunto, cuerpo=""):
    """Extrae el nombre de quien envio el Zelle. Devuelve str o None."""
    for texto in (asunto or "", cuerpo or ""):
        if not texto:
            continue
        for rx in _RE_REMITENTE:
            m = rx.search(texto)
            if m:
                nombre = m.group(1).strip().strip('"').strip()
                if 2 <= len(nombre) <= 80:
                    return nombre
    return None


def motivo_rechazo(from_addr, auth_results):
    """Anti-spoofing. None si el correo viene REALMENTE del banco; si no, el código
    del motivo por el que se rechaza. Dos barreras que un estafador no puede saltar
    a la vez:
      1) La dirección exacta del From tiene que estar en la allowlist (defiende de
         direcciones/dominios parecidos: bankofamerlca.com, ealerts-bofa.com, etc.)
         -> 'dominio_no_autorizado'.
      2) El correo tuvo que pasar DMARC — cabecera 'Authentication-Results' que
         Outlook AGREGA al recibir tras verificar la firma criptográfica del banco;
         un spoof con la dirección exacta pero enviado desde otro servidor la falla
         -> 'dmarc_fallido' (o 'header_from_no_alinea' si el dominio evaluado por
         DMARC no coincide con el remitente).
    """
    addr = (from_addr or "").lower().strip()
    if addr not in config.ZELLE_TRUSTED_SENDERS:
        return "dominio_no_autorizado"
    if not config.ZELLE_REQUIRE_DMARC:
        return None
    auth = (auth_results or "").lower()
    if "dmarc=pass" not in auth and "compauth=pass" not in auth:
        return "dmarc_fallido"
    # Si el veredicto DMARC trae el dominio evaluado, debe alinear con el remitente.
    m = re.search(r"header\.from=([^\s;]+)", auth)
    if m and m.group(1).strip().strip('"') != addr.split("@")[-1]:
        return "header_from_no_alinea"
    return None


def remitente_confiable(from_addr, auth_results):
    return motivo_rechazo(from_addr, auth_results) is None


def _parece_zelle(asunto, cuerpo=""):
    """Heurística laxa: ¿este correo aparenta ser un aviso Zelle? Solo se usa para
    detectar posibles intentos de spoofing desde remitentes NO confiables (log)."""
    texto = f"{asunto}\n{cuerpo}".lower()
    if "zelle" in texto:
        return True
    return bool(_RE_ZELLE_PAGO.search(texto) or _RE_ZELLE_REVISION.search(texto))


def clasificar_zelle(asunto, cuerpo):
    """Clasifica un correo (ya validado como confiable) en el estado del pago:
      'recibido'    → el dinero se está depositando (aviso instantáneo).
      'en_revision' → el banco retuvo el pago a la espera de revisión.
      None          → correo legítimo del banco pero NO es un pago Zelle
                      (ACH, wire, código de autorización, publicidad...).
    """
    texto = f"{asunto}\n{cuerpo}"
    if _RE_ZELLE_PAGO.search(texto):
        return "recibido"
    if "zelle" in texto.lower() and _RE_ZELLE_REVISION.search(texto):
        return "en_revision"
    return None


def _texto_de_html(html):
    texto = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", html, flags=re.IGNORECASE | re.DOTALL)
    texto = re.sub(r"<[^>]+>", " ", texto)
    return re.sub(r"\s+", " ", texto).strip()


def extraer_texto(msg):
    """Cuerpo del correo como texto plano (text/plain preferido, html como fallback)."""
    try:
        parte = msg.get_body(preferencelist=("plain", "html"))
        if parte is None:
            return ""
        contenido = parte.get_content()
        if parte.get_content_type() == "text/html":
            return _texto_de_html(contenido)
        return contenido.strip()
    except Exception:
        return ""


def procesar_mensaje(raw_bytes, uid, uidvalidity):
    """RFC822 bytes → dict con '_tipo' ('pago' | 'spoof'), o None si no aplica.

    'uid'/'uidvalidity' solo se usan para armar un Message-ID de respaldo si el
    correo no trae uno propio (nombres heredados de la version IMAP; con Graph
    'uid' recibe el id de mensaje de Graph y 'uidvalidity' va fijo en 0).
    """
    msg = email.message_from_bytes(raw_bytes, policy=email.policy.default)
    from_addr = email.utils.parseaddr(str(msg.get("From", "")))[1]
    asunto = str(msg.get("Subject", "")).strip()
    auth = " ".join(msg.get_all("Authentication-Results") or [])
    cuerpo = extraer_texto(msg)

    message_id = str(msg.get("Message-ID", "")).strip()
    if not message_id:
        message_id = f"<uid-{uidvalidity}-{uid}@zelle-listener>"

    recibido_en = None
    try:
        fecha = email.utils.parsedate_to_datetime(str(msg.get("Date", "")))
        if fecha:
            recibido_en = fecha.isoformat()
    except Exception:
        pass

    # Barrera anti-spoofing: solo correos que vienen REALMENTE del banco.
    motivo = motivo_rechazo(from_addr, auth)
    if motivo is not None:
        if not _parece_zelle(asunto, cuerpo):
            return None  # correo de remitente no confiable que ni parece Zelle: ignorar
        log(f"[SPOOF?] Aviso tipo Zelle de remitente NO confiable ({motivo}): {from_addr} | {asunto[:70]}")
        return {
            "_tipo": "spoof",
            "message_id": message_id,
            "from_addr": from_addr,
            "asunto": asunto[:300] or "(sin asunto)",
            "motivo": motivo,
            "auth_snippet": (auth or "")[:500],
            "cuerpo_snippet": cuerpo[:SNIPPET_LEN],
            "recibido_en": recibido_en,
        }

    estado = clasificar_zelle(asunto, cuerpo)
    if estado is None:
        return None  # correo legítimo del banco pero no es un pago Zelle

    monto = parsear_monto(asunto) or parsear_monto(cuerpo)
    remitente = parsear_remitente(asunto, cuerpo)

    return {
        "_tipo": "pago",
        "message_id": message_id,
        "monto": monto,
        "remitente": remitente,
        "banco": from_addr.split("@")[-1] if "@" in from_addr else from_addr,
        "asunto": asunto[:300] or "(sin asunto)",
        "cuerpo_snippet": cuerpo[:SNIPPET_LEN],
        "raw_parse_ok": monto is not None,
        "recibido_en": recibido_en,
        "estado": estado,
    }


# ─── Supabase ─────────────────────────────────────────────────────────────────

def _insertar_con_dedupe(tabla, payload):
    """INSERT genérico con dedupe por message_id. True si quedo guardado (o ya existia)."""
    try:
        from supabase_rest import build_write_headers, REST_URL
        headers = build_write_headers(extra_prefer="return=minimal,resolution=ignore-duplicates")
    except Exception as e:
        log(f"Error importando supabase_rest: {repr(e)}")
        return False

    url = f"{REST_URL.rstrip('/')}/rest/v1/{tabla}?on_conflict=message_id"
    try:
        resp = requests.post(url, headers=headers, json=[payload], timeout=30)
        if resp.status_code in (200, 201, 204):
            return True
        if resp.status_code == 409:
            return True  # duplicado: ya estaba registrado
        log(f"HTTP {resp.status_code} insertando en {tabla}: {resp.text[:300]}")
        return False
    except Exception as e:
        log(f"Error de red insertando en {tabla}: {repr(e)}")
        return False


def insertar_pago(pago):
    return _insertar_con_dedupe("pagos_zelle", pago)


def insertar_alerta_spoof(alerta):
    return _insertar_con_dedupe("alertas_zelle_spoof", alerta)


# ─── OAuth2 (msal) ────────────────────────────────────────────────────────────

def _build_msal_app():
    import msal
    cache = msal.SerializableTokenCache()
    if os.path.exists(TOKEN_CACHE_FILE):
        try:
            with open(TOKEN_CACHE_FILE, "r", encoding="utf-8") as f:
                cache.deserialize(f.read())
        except Exception as e:
            log(f"Token cache corrupto, se ignora: {repr(e)}")
    app = msal.PublicClientApplication(
        config.ZELLE_CLIENT_ID, authority=AUTHORITY, token_cache=cache
    )
    return app, cache


def _save_cache(cache):
    if not cache.has_state_changed:
        return
    tmp = TOKEN_CACHE_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(cache.serialize())
    os.replace(tmp, TOKEN_CACHE_FILE)


def obtener_token(interactivo=False):
    """Access token para Graph. Silencioso via refresh token; device-code si interactivo."""
    app, cache = _build_msal_app()
    result = None
    accounts = app.get_accounts()
    if accounts:
        result = app.acquire_token_silent(SCOPES, account=accounts[0])
    if not result and interactivo:
        flow = app.initiate_device_flow(scopes=SCOPES)
        if "user_code" not in flow:
            raise RuntimeError(f"No se pudo iniciar device flow: {flow.get('error_description', flow)}")
        print("\n" + flow["message"] + "\n")
        result = app.acquire_token_by_device_flow(flow)
    _save_cache(cache)
    if result and "access_token" in result:
        return result["access_token"]
    detalle = result.get("error_description") if result else "sin sesion iniciada (correr --login)"
    raise RuntimeError(f"No se pudo obtener token: {detalle}")


# ─── Estado local (fecha del ultimo correo procesado) ─────────────────────────

def cargar_estado():
    try:
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def guardar_estado(estado):
    try:
        tmp = STATE_FILE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(estado, f)
        os.replace(tmp, STATE_FILE)
    except Exception as e:
        log(f"Error guardando estado: {repr(e)}")


# ─── Microsoft Graph (polling HTTPS) ──────────────────────────────────────────

def _graph_headers(access_token):
    return {"Authorization": f"Bearer {access_token}"}


def listar_mensajes_nuevos(access_token, desde_iso):
    """IDs + fecha de los mensajes del inbox recibidos despues de desde_iso.

    Sin $orderby (para no arriesgar una combinacion rara con $filter en Graph):
    se ordena del lado del cliente, es un puñado de correos por ciclo.
    """
    url = f"{GRAPH_BASE}/me/mailFolders/inbox/messages"
    params = {
        "$filter": f"receivedDateTime gt {desde_iso}",
        "$select": "id,receivedDateTime",
        "$top": "50",
    }
    resp = requests.get(url, headers=_graph_headers(access_token), params=params, timeout=30)
    resp.raise_for_status()
    mensajes = resp.json().get("value", [])
    return sorted(mensajes, key=lambda m: m["receivedDateTime"])


def obtener_mime(access_token, message_id):
    """MIME crudo (bytes) de un mensaje — deja reusar el mismo parser que la version IMAP."""
    url = f"{GRAPH_BASE}/me/messages/{message_id}/$value"
    resp = requests.get(url, headers=_graph_headers(access_token), timeout=30)
    resp.raise_for_status()
    return resp.content


def procesar_pendientes(access_token, estado):
    """Procesa correos nuevos desde el ultimo visto. Solo avanza el puntero si el insert salio bien.

    OJO con la precision de Graph: receivedDateTime llega truncado a segundos,
    pero '$filter gt' compara contra el valor con sub-segundos del buzon — el
    ultimo correo procesado vuelve a matchear en cada ciclo para siempre. Por
    eso ademas del timestamp se guardan los IDs ya procesados dentro de ese
    ultimo segundo ('vistos') y se saltan del lado del cliente.
    """
    desde_iso = estado.get("last_received_iso")
    vistos = set(estado.get("vistos", []))
    if not desde_iso:
        # Primera corrida (o estado perdido): partir del ultimo dia para no
        # ingerir todo el historial del inbox.
        desde = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=1)
        desde_iso = desde.strftime("%Y-%m-%dT%H:%M:%SZ")
        log(f"Primera corrida. Revisando correos desde {desde_iso}.")

    mensajes = listar_mensajes_nuevos(access_token, desde_iso)

    for m in mensajes:
        msg_id = m["id"]
        recibido = m["receivedDateTime"]
        if msg_id in vistos:
            continue
        try:
            raw = obtener_mime(access_token, msg_id)
            resultado = procesar_mensaje(raw, msg_id, 0)
        except Exception as e:
            log(f"Error procesando mensaje (se salta): {repr(e)}")
            resultado = None

        if resultado is not None:
            tipo = resultado.pop("_tipo", None)
            if tipo == "spoof":
                if not insertar_alerta_spoof(resultado):
                    log("Insert de alerta de spoofing fallido; se reintentara en el proximo ciclo.")
                    return
                log(f"[ALERTA] Intento de spoofing registrado ({resultado['motivo']}): "
                    f"{resultado['from_addr']} | {resultado['asunto'][:60]}")
            elif tipo == "pago":
                if not insertar_pago(resultado):
                    # Sin nube: no avanzar el puntero; se reintenta en el proximo ciclo.
                    log("Insert fallido; se reintentara en el proximo ciclo.")
                    return
                monto_txt = f"${resultado['monto']:.2f}" if resultado["monto"] is not None else "monto no parseado"
                etq = "EN REVISION" if resultado.get("estado") == "en_revision" else "recibido"
                log(f"ZELLE [{etq}]: {monto_txt} — {resultado['remitente'] or '?'}")

        if recibido == estado.get("last_received_iso"):
            vistos.add(msg_id)
        else:
            vistos = {msg_id}
        estado["last_received_iso"] = recibido
        estado["vistos"] = list(vistos)
        guardar_estado(estado)


def correr_listener():
    log("=== Iniciando Listener de Zelle v2.0 (Microsoft Graph, polling HTTPS) ===")

    while not config.ZELLE_CLIENT_ID:
        log("ZELLE_CLIENT_ID no configurado en .env. Durmiendo 1h...")
        time.sleep(NOT_CONFIGURED_SLEEP_S)
        import importlib
        importlib.reload(config)

    backoff = 10
    estado = cargar_estado()
    while True:
        try:
            access_token = obtener_token()
            backoff = 10
            while True:
                procesar_pendientes(access_token, estado)
                time.sleep(config.ZELLE_POLL_INTERVAL_S)
                # acquire_token_silent no golpea la red si el token sigue vigente;
                # solo refresca cuando esta por expirar.
                access_token = obtener_token()

        except RuntimeError as e:
            # Token invalido/expirado sin refresh posible: requiere --login manual.
            log(f"[AUTH] {e}")
            log("Reintentando en 10 min (si persiste, correr: python zelle_listener.py --login)")
            time.sleep(600)
        except requests.exceptions.RequestException as e:
            log(f"Error de red con Graph: {repr(e)}. Reintentando en {backoff}s...")
            time.sleep(backoff)
            backoff = min(backoff * 2, 300)
        except Exception as e:
            log(f"Error inesperado: {repr(e)}. Reintentando en {backoff}s...")
            time.sleep(backoff)
            backoff = min(backoff * 2, 300)


# ─── CLI ──────────────────────────────────────────────────────────────────────

def cmd_login():
    if not config.ZELLE_CLIENT_ID:
        print("Falta ZELLE_CLIENT_ID en .env (ver ZELLE-LISTENER.md, paso Azure).")
        return 1
    token = obtener_token(interactivo=True)
    print("Login OK — token guardado en zelle_token_cache.json")
    print("El listener ya puede correr en segundo plano (lo lanza el watchdog).")
    return 0 if token else 1


def cmd_status():
    print(f"ZELLE_EMAIL:          {config.ZELLE_EMAIL or '(no configurado)'}")
    print(f"ZELLE_CLIENT_ID:      {'configurado' if config.ZELLE_CLIENT_ID else '(no configurado)'}")
    print(f"Remitentes confiables:{sorted(config.ZELLE_TRUSTED_SENDERS)}")
    print(f"Exigir DMARC:         {config.ZELLE_REQUIRE_DMARC}")
    print(f"ZELLE_POLL_INTERVAL:  {config.ZELLE_POLL_INTERVAL_S}s")
    print(f"Token cache:          {'existe' if os.path.exists(TOKEN_CACHE_FILE) else 'NO existe (correr --login)'}")
    print(f"Estado:               {cargar_estado() or '(sin estado, primera corrida)'}")
    if os.path.exists(TOKEN_CACHE_FILE) and config.ZELLE_CLIENT_ID:
        try:
            obtener_token()
            print("Token silencioso:     OK (refresh vigente)")
        except Exception as e:
            print(f"Token silencioso:     FALLO — {e}")
    return 0


def cmd_probe(n):
    """Parsea los ultimos N correos del inbox SIN insertar nada (para afinar regexes)."""
    access_token = obtener_token()
    url = f"{GRAPH_BASE}/me/mailFolders/inbox/messages"
    params = {"$select": "id,receivedDateTime", "$top": str(n)}
    resp = requests.get(url, headers=_graph_headers(access_token), params=params, timeout=30)
    resp.raise_for_status()
    mensajes = sorted(resp.json().get("value", []), key=lambda m: m["receivedDateTime"])

    for m in mensajes:
        raw = obtener_mime(access_token, m["id"])
        msg = email.message_from_bytes(raw, policy=email.policy.default)
        from_addr = email.utils.parseaddr(str(msg.get("From", "")))[1]
        asunto = str(msg.get("Subject", "")).strip()
        auth = " ".join(msg.get_all("Authentication-Results") or [])
        motivo = motivo_rechazo(from_addr, auth)
        resultado = procesar_mensaje(raw, m["id"], 0)
        print("-" * 70)
        print(f"De: {from_addr}  [{'CONFIABLE' if motivo is None else f'NO confiable ({motivo})'}]")
        print(f"Asunto: {asunto}")
        tipo = resultado.get("_tipo") if resultado else None
        if tipo == "pago":
            print(f">> ZELLE [{resultado['estado']}]  monto={resultado['monto']}  "
                  f"remitente={resultado['remitente']}  parse_ok={resultado['raw_parse_ok']}")
        elif tipo == "spoof":
            print(f">> ALERTA DE SPOOFING ({motivo}) — se registraria en alertas_zelle_spoof")
        else:
            print(">> (no es Zelle)")
    return 0


if __name__ == "__main__":
    args = sys.argv[1:]
    if "--login" in args:
        sys.exit(cmd_login())
    elif "--status" in args:
        sys.exit(cmd_status())
    elif "--probe" in args:
        idx = args.index("--probe")
        n = int(args[idx + 1]) if len(args) > idx + 1 and args[idx + 1].isdigit() else 10
        sys.exit(cmd_probe(n))
    else:
        correr_listener()
