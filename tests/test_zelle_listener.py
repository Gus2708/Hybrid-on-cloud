"""Tests del parseo y filtrado de correos Zelle (zelle_listener.py).

Cubre las funciones puras: parseo de monto/remitente, filtro anti-spoofing
(remitente_confiable) y clasificación recibido/en_revisión. La conexión a Graph
y el insert a Supabase no se tocan aquí.
"""
import pytest
import zelle_listener as zl


@pytest.fixture(autouse=True)
def _log_aislado(tmp_path, monkeypatch):
    """Evita que log() escriba en el zelle_listener.log de PRODUCCIÓN.

    Bug real detectado: los tests de spoofing usan datos sintéticos (ej. el
    dominio alterado 'bankofamerlca.com') y procesar_mensaje() llama a log()
    para casos [SPOOF?] — sin este fixture, esas líneas de prueba terminaban
    en el log real, indistinguibles de un intento de fraude genuino.
    """
    monkeypatch.setattr(zl, "LOG_FILE", str(tmp_path / "test_zelle_listener.log"))


# Direcciones reales de Bank of America (confirmadas con --probe).
TRUSTED = "customerservice@ealerts.bankofamerica.com"      # avisos "recibido"
ONLINEBANK = "onlinebanking@ealerts.bankofamerica.com"     # avisos "en revisión"

# Cabecera Authentication-Results tal como la agrega Outlook para un correo
# legítimo del banco (DMARC pass, header.from alineado).
AUTH_PASS = (
    "spf=pass smtp.mailfrom=bounce.ealerts.bankofamerica.com; "
    "dkim=pass header.d=ealerts.bankofamerica.com; "
    "dmarc=pass action=none header.from=ealerts.bankofamerica.com; "
    "compauth=pass reason=100"
)


def _mk_email(subject, body, from_addr=TRUSTED, msg_id="<abc123@bofa>",
              content_type="text/plain", auth=AUTH_PASS):
    headers = [
        f"From: Bank of America <{from_addr}>",
        "To: tienda <ferreteria@hotmail.com>",
        f"Subject: {subject}",
    ]
    if msg_id:
        headers.append(f"Message-ID: {msg_id}")
    if auth is not None:
        headers.append(f"Authentication-Results: {auth}")
    headers.append("Date: Thu, 16 Jul 2026 10:00:00 -0400")
    headers.append(f"Content-Type: {content_type}; charset=utf-8")
    raw = "\r\n".join(headers) + "\r\n\r\n" + body + "\r\n"
    return raw.encode("utf-8")


# ─── parsear_monto ────────────────────────────────────────────────────────────

def test_monto_simple():
    assert zl.parsear_monto("JUAN PEREZ sent you $50.00") == 50.0

def test_monto_con_miles():
    assert zl.parsear_monto("You received $1,234.56 from MARIA") == 1234.56

def test_monto_sin_decimales():
    assert zl.parsear_monto("te envio $75 por Zelle") == 75.0

def test_monto_ausente():
    assert zl.parsear_monto("Bienvenido a Zelle") is None

def test_monto_texto_vacio():
    assert zl.parsear_monto("") is None
    assert zl.parsear_monto(None) is None


# ─── parsear_remitente ────────────────────────────────────────────────────────

def test_remitente_sent_you():
    assert zl.parsear_remitente("JUAN PEREZ sent you $50.00") == "JUAN PEREZ"

def test_remitente_le_envio_bofa():
    assert zl.parsear_remitente("Michel A Nava Batista le envió $192.50") == "Michel A Nava Batista"

def test_remitente_review_su_pago_de():
    cuerpo = "Su pago de NOSYARELIS MORILLO GUTIERREZ a través de Zelle está pendiente de revisión"
    assert zl.parsear_remitente("Un pago pendiente de revisión", cuerpo) == "NOSYARELIS MORILLO GUTIERREZ"

def test_remitente_review_desde_cantidad():
    cuerpo = "Confirmación 99x Desde ANA DIAZ ROJAS Cantidad $50.00 Fecha ..."
    assert zl.parsear_remitente("", cuerpo) == "ANA DIAZ ROJAS"

def test_remitente_ausente():
    assert zl.parsear_remitente("Aviso de seguridad", "Sin nombres aqui") is None


# ─── remitente_confiable (anti-spoofing) ─────────────────────────────────────

def test_confiable_bofa_con_dmarc():
    assert zl.remitente_confiable(TRUSTED, AUTH_PASS) is True

def test_confiable_onlinebanking_con_dmarc():
    assert zl.remitente_confiable(ONLINEBANK, AUTH_PASS) is True

def test_no_confiable_dominio_parecido():
    # Estafador con dominio casi-idéntico (rl -> ri): NO está en la allowlist.
    assert zl.remitente_confiable("customerservice@ealerts.bankofamerlca.com", AUTH_PASS) is False

def test_no_confiable_sufijo_agregado():
    assert zl.remitente_confiable("customerservice@ealerts.bankofamerica.com.evil.com", AUTH_PASS) is False

def test_no_confiable_sin_dmarc():
    # Dirección exacta pero el correo NO pasó DMARC (spoof desde otro servidor).
    assert zl.remitente_confiable(TRUSTED, "spf=fail; dkim=none; dmarc=fail") is False

def test_no_confiable_sin_auth_header():
    assert zl.remitente_confiable(TRUSTED, "") is False

def test_no_confiable_header_from_no_alinea():
    auth = "dmarc=pass header.from=otrodominio.com; compauth=pass"
    assert zl.remitente_confiable(TRUSTED, auth) is False

def test_confiable_dmarc_off(monkeypatch):
    monkeypatch.setattr(zl.config, "ZELLE_REQUIRE_DMARC", False)
    assert zl.remitente_confiable(TRUSTED, "") is True


# ─── motivo_rechazo (detalle del motivo, usado para la alerta de spoofing) ───

def test_motivo_confiable_es_none():
    assert zl.motivo_rechazo(TRUSTED, AUTH_PASS) is None

def test_motivo_dominio_no_autorizado():
    assert zl.motivo_rechazo("customerservice@ealerts.bankofamerlca.com", AUTH_PASS) == "dominio_no_autorizado"

def test_motivo_dmarc_fallido():
    assert zl.motivo_rechazo(TRUSTED, "spf=fail; dkim=none; dmarc=fail") == "dmarc_fallido"

def test_motivo_header_from_no_alinea():
    auth = "dmarc=pass header.from=otrodominio.com; compauth=pass"
    assert zl.motivo_rechazo(TRUSTED, auth) == "header_from_no_alinea"


# ─── clasificar_zelle ─────────────────────────────────────────────────────────

def test_clasifica_recibido():
    assert zl.clasificar_zelle("Carlos Isea Chirinos le envió $200.00", "") == "recibido"

def test_clasifica_en_revision():
    asunto = "Un pago de Zelle que le enviamos está pendiente de revisión"
    cuerpo = "Su pago de PEDRO GOMEZ a través de Zelle está pendiente de revisión Cantidad $80.00"
    assert zl.clasificar_zelle(asunto, cuerpo) == "en_revision"

def test_clasifica_ach_no_es_zelle():
    assert zl.clasificar_zelle("Hemos recibido su solicitud de transferencia ACH", "") is None

def test_clasifica_codigo_no_es_zelle():
    assert zl.clasificar_zelle("Aquí está el código de autorización que solicitó", "") is None


# ─── procesar_mensaje (end to end del filtrado) ──────────────────────────────

def test_procesar_recibido_completo():
    raw = _mk_email(
        "Carlos Isea Chirinos le envió $200.00",
        "Carlos Isea Chirinos le envió $200.00 Por favor, espere hasta 5 minutos.",
    )
    pago = zl.procesar_mensaje(raw, uid="g1", uidvalidity=0)
    assert pago is not None
    assert pago["_tipo"] == "pago"
    assert pago["estado"] == "recibido"
    assert pago["monto"] == 200.0
    assert pago["remitente"] == "Carlos Isea Chirinos"
    assert pago["banco"] == "ealerts.bankofamerica.com"
    assert pago["raw_parse_ok"] is True

def test_procesar_en_revision_completo():
    cuerpo = (
        "Su pago de NOSYARELIS MORILLO GUTIERREZ a través de Zelle está pendiente de revisión. "
        "Desde NOSYARELIS MORILLO GUTIERREZ Cantidad $272.00 Enviado a la cuenta que termina en 9713."
    )
    raw = _mk_email(
        "Un pago de Zelle que le enviamos está pendiente de revisión",
        cuerpo,
        from_addr=ONLINEBANK,
    )
    pago = zl.procesar_mensaje(raw, uid="g2", uidvalidity=0)
    assert pago is not None
    assert pago["_tipo"] == "pago"
    assert pago["estado"] == "en_revision"
    assert pago["monto"] == 272.0
    assert pago["remitente"] == "NOSYARELIS MORILLO GUTIERREZ"

def test_procesar_spoof_dominio_genera_alerta():
    # Dominio parecido + asunto de Zelle real: debe generar una alerta de spoofing,
    # NO insertarse como pago.
    raw = _mk_email(
        "Carlos Isea Chirinos le envió $200.00",
        "Carlos Isea Chirinos le envió $200.00",
        from_addr="customerservice@ealerts.bankofamerlca.com",
    )
    alerta = zl.procesar_mensaje(raw, uid="g3", uidvalidity=0)
    assert alerta is not None
    assert alerta["_tipo"] == "spoof"
    assert alerta["motivo"] == "dominio_no_autorizado"
    assert alerta["from_addr"] == "customerservice@ealerts.bankofamerlca.com"
    assert "Carlos Isea Chirinos" in alerta["asunto"]

def test_procesar_spoof_sin_dmarc_genera_alerta():
    raw = _mk_email(
        "Carlos Isea Chirinos le envió $200.00",
        "Carlos Isea Chirinos le envió $200.00",
        auth="spf=fail; dmarc=fail",
    )
    alerta = zl.procesar_mensaje(raw, uid="g4", uidvalidity=0)
    assert alerta is not None
    assert alerta["_tipo"] == "spoof"
    assert alerta["motivo"] == "dmarc_fallido"

def test_procesar_no_confiable_sin_pinta_de_zelle_se_ignora():
    # Remitente no confiable pero el correo ni siquiera aparenta ser un Zelle:
    # no genera alerta (evita ruido de spam genérico no relacionado).
    raw = _mk_email("Oferta especial de la semana", "Compre ahora y ahorre.",
                    from_addr="marketing@otrobanco.com")
    assert zl.procesar_mensaje(raw, uid="g_noise", uidvalidity=0) is None

def test_procesar_ach_confiable_pero_no_es_zelle():
    raw = _mk_email("Hemos recibido su solicitud de transferencia ACH", "Detalle de su ACH.",
                    from_addr=ONLINEBANK)
    assert zl.procesar_mensaje(raw, uid="g5", uidvalidity=0) is None

def test_procesar_sin_monto_marca_parse_fallido():
    # Confiable + clasificable como revisión pero sin monto parseable.
    raw = _mk_email(
        "Un pago de Zelle que le enviamos está pendiente de revisión",
        "Su pago a través de Zelle está pendiente de revisión. Consulte su actividad.",
        from_addr=ONLINEBANK,
    )
    pago = zl.procesar_mensaje(raw, uid="g6", uidvalidity=0)
    assert pago is not None
    assert pago["estado"] == "en_revision"
    assert pago["monto"] is None
    assert pago["raw_parse_ok"] is False

def test_procesar_html_recibido():
    raw = _mk_email(
        "Maria Lopez le envió $45.50",
        "<html><body><p>Maria Lopez le envió <b>$45.50</b> con Zelle</p></body></html>",
        content_type="text/html",
    )
    pago = zl.procesar_mensaje(raw, uid="g7", uidvalidity=0)
    assert pago["monto"] == 45.5
    assert pago["estado"] == "recibido"
