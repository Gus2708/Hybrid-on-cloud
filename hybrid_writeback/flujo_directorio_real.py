"""flujo_directorio_real.py — Alta de CLIENTE / PROVEEDOR nuevo en HybridLiteOS con
INPUT REAL de hardware.

Coreografía grabada del dueño el 2026-07-22
(grabar_flujo_20260722_010203.log = cliente, grabar_flujo_20260722_010420.log = proveedor)
+ inspección de la ficha (inspeccion_TTConfigForm_*.txt) + verdad de campo contra la DBISAM
(los dos registros de prueba PRUEBA CLAUDE C1 / P1, verificados con read_db_directorio).

Ambas fichas son TTConfigForm (misma clase que la Ficha de Inventario), distinguidas por
TÍTULO: 'Forma de Cliente' / 'Forma Proveedores'. Se abren desde el menú principal
(TAdvGlassButton 'Clientes' / 'Proveedores'). El alta es análoga a crear_producto de
flujo_compra_real: barra owner-drawn Incluir · … · Guardar (mismas posiciones que la
Ficha) y campos THybridEdit localizados por FRANJA de posición.

v1 (mínimo robusto): se llenan CÓDIGO + NOMBRE + RIF. El CÓDIGO es MANUAL en HybridLite y
se deriva del RIF sin guiones (convención de la tienda: 'J-31440341-9' → 'J314403419'); por
eso el RIF es obligatorio. Teléfono/dirección/contacto/email quedan para v2.

Secuencia (registrar, un solo Guardar):
  1. abrir_hybrid.asegurar_hybrid() (instancia aislada).
  2. Menú → 'Clientes'/'Proveedores' → abre/reutiliza la Forma (TTConfigForm por título).
  3. Barra 'Incluir' (coord) → modo alta (campos vacíos).
  4. CÓDIGO(=norm(RIF)) → NOMBRE → RIF, cada uno verificado en pantalla.
  5. commit: 'Guardar' (coord) + verificación contra DBISAM (código devuelto).
     preview: 'Cancelar' (coord) + responder 'No' → nada se guarda.
  TODO-O-NADA: cualquier fallo pre-Guardar cancela el alta.

Idempotencia: si ya existe una ficha con ese código (retry), NO se crea de nuevo.

SEGURIDAD: preview por defecto; --commit aplica de verdad y verifica contra la base.

USO:
    python flujo_directorio_real.py cliente   "JUAN PEREZ"   --rif V-12345678
    python flujo_directorio_real.py proveedor "TORNILLOS CA" --rif J-12345678-9 --commit
"""
import os
import sys
import time
import logging

import win32gui
import win32con

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

import flujo_precio as fp            # helpers de ventanas + MAIN_CLASS
import flujo_precio_real as fpr       # _focus / _click_boton_dialogo
import flujo_stock_real as fsr        # _cerrar_ficha_si_abierta
import realinput as ri
import read_db_directorio as rdb

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("directorio_real")

FORM_CLASS = "TTConfigForm"           # compartida por Cliente, Proveedor y Ficha de Inventario
CONF_CLASS = "TFConfirmacion"

# Barra owner-drawn de la ficha (Incluir · Modificar · Cancelar · Guardar · … · Salir),
# misma disposición que la Ficha de Inventario (ver fpr.GUARDAR_REL=(240,60) /
# INCLUIR_REL=(42,62) en flujo_compra_real). Confirmado por captura: proveedor Incluir≈
# (38,53) Guardar≈(240,71); cliente Incluir≈(42,65) Salir≈(355,58). y=62 cae en el centro
# del botón (TPanel ~40px de alto), robusto a la pequeña variación entre las dos formas.
INCLUIR_REL = (42, 62)
GUARDAR_REL = (240, 62)
CANCELAR_REL = (175, 62)
SALIR_REL = (360, 62)

# Configuración por tipo: botón del menú, título de la forma, y franja `top` (relativa a
# la ventana) de cada campo THybridEdit de la COLUMNA IZQUIERDA. Tops confirmados: proveedor
# por inspección (código 137 / nombre 174 / rif 362); cliente por la captura
# (código≈160 / nombre≈198 / rif≈345). El filtro left_max descarta la columna derecha
# (p.ej. el NIT del proveedor en rel_left≈231, junto al RIF en 33).
CFG = {
    "cliente": {
        "menu_btn":   "Clientes",
        "menu_grupo": (216, 202),     # panel del grupo del menú (fallback si el botón no está desplegado)
        "form_title": "Forma de Cliente",
        "tops":       {"codigo": 160, "nombre": 198, "rif": 345},
    },
    "proveedor": {
        "menu_btn":   "Proveedores",
        "menu_grupo": (216, 202),
        "form_title": "Forma Proveedores",
        "tops":       {"codigo": 137, "nombre": 174, "rif": 362},
    },
}

TOP_TOL = 16       # ± px de tolerancia al localizar un campo por su franja `top`
LEFT_MAX = 70      # rel_left máximo para considerar un campo de la columna izquierda


class DirectorioError(Exception):
    pass


# ── utilidades ────────────────────────────────────────────────────────────────
def _focus(hwnd):
    if not hwnd:
        return
    try:
        if win32gui.IsIconic(hwnd):
            win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
        win32gui.SetForegroundWindow(hwnd)
    except Exception:
        pass
    try:
        fp._win(hwnd).set_focus()
    except Exception:
        pass
    time.sleep(0.1)


def _find_form(title):
    """hwnd de la ventana TTConfigForm cuyo título contiene `title`, filtrando por el
    PID de la instancia aislada si set_target_pid() está activo (para no agarrar una
    ficha abierta en la instancia de un empleado)."""
    objetivo = title.lower()
    target_pid = getattr(fp, "_target_pid", None)
    out = []

    def _cb(h, _):
        if not win32gui.IsWindowVisible(h):
            return
        if win32gui.GetClassName(h) != FORM_CLASS:
            return
        if objetivo not in (win32gui.GetWindowText(h) or "").lower():
            return
        if target_pid is not None:
            try:
                import win32process
                if (win32process.GetWindowThreadProcessId(h)[1] & 0xFFFFFFFF) != target_pid:
                    return
            except Exception:
                return
        out.append(h)

    win32gui.EnumWindows(_cb, None)
    return out[0] if out else None


def _responder(dialogo_titulos, timeout=2.0):
    """Responde a un diálogo de confirmación pulsando el primer botón cuyo título
    matchee `dialogo_titulos`. Devuelve True si respondió alguno.
    Polling reactivo cada 0.05s para no penalizar altas limpias."""
    t0 = time.time()
    while time.time() - t0 < timeout:
        h = fp._find_hwnd(CONF_CLASS) or fp._find_hwnd("TMessageForm")
        if not h:
            time.sleep(0.05)
            continue
        _focus(h)
        m = fp._win(h)
        for titulo in dialogo_titulos:
            try:
                b = m.child_window(title=titulo)
                r = b.rectangle()
                ri.click((r.left + r.right) // 2, (r.top + r.bottom) // 2)
                log.info("Diálogo: '%s' pulsado.", titulo)
                time.sleep(0.2)
                return True
            except Exception:
                continue
        time.sleep(0.05)
    return False



# ── apertura de la forma ──────────────────────────────────────────────────────
def abrir_forma(tipo):
    """Garantiza que la Forma (Cliente/Proveedor) esté abierta; navega el menú si no.
    Devuelve su hwnd."""
    cfg = CFG[tipo]
    h = _find_form(cfg["form_title"])
    if h:
        log.info("Forma '%s' ya abierta, reutilizando.", cfg["form_title"])
        return h

    # una Ficha residual (misma clase) delante bloquea los clics del menú
    try:
        fsr._cerrar_ficha_si_abierta()
    except Exception:
        pass

    hmain = fp._find_hwnd(fp.MAIN_CLASS)
    if not hmain:
        raise DirectorioError("HybridLiteOS no está abierto (no veo el módulo principal).")
    _focus(hmain)
    time.sleep(0.1)
    main = fp._win(hmain)


    try:
        btn = main.child_window(title=cfg["menu_btn"], class_name="TAdvGlassButton")
        btn.wait("exists visible", timeout=1.5)
    except Exception:
        # grupo del menú aún no desplegado → clic en el panel del grupo (fallback)
        L, T, _, _ = win32gui.GetWindowRect(hmain)
        ri.click(L + cfg["menu_grupo"][0], T + cfg["menu_grupo"][1])
        time.sleep(0.8)
        btn = main.child_window(title=cfg["menu_btn"], class_name="TAdvGlassButton")
        btn.wait("exists visible", timeout=8)

    r = btn.rectangle()
    ri.click((r.left + r.right) // 2, (r.top + r.bottom) // 2)

    t0 = time.time()
    while time.time() - t0 < 15:
        h = _find_form(cfg["form_title"])
        if h:
            time.sleep(0.35)   # dejar renderizar la ficha antes de Incluir
            return h
        time.sleep(0.3)
    raise DirectorioError(f"No abrió la Forma '{cfg['form_title']}' tras clickear '{cfg['menu_btn']}'.")


# ── campos ────────────────────────────────────────────────────────────────────
def _localizar_campos(hform, tops):
    """Localiza todos los THybridEdit de la columna izquierda en una SOLA pasada
    por el árbol de controles (en vez de llamar descendants() N veces)."""
    form = fp._win(hform)
    L, T, _, _ = win32gui.GetWindowRect(hform)
    edits = []
    for c in form.descendants(class_name="THybridEdit"):
        r = c.rectangle()
        if (r.left - L) <= LEFT_MAX:
            edits.append((r.top - T, c))

    controles = {}
    for clave, top_objetivo in tops.items():
        mejor, mejor_delta = None, TOP_TOL + 1
        for rel_top, c in edits:
            delta = abs(rel_top - top_objetivo)
            if delta <= TOP_TOL and delta < mejor_delta:
                mejor, mejor_delta = c, delta
        controles[clave] = mejor
    return controles


def _escribir_campo(campo, valor):
    """Clic en el centro del campo + seleccionar-todo + teclear (Unicode). Devuelve el
    texto leído tras teclear (window_text stripped), para que el llamador verifique.

    En modo alta (tras Incluir) los campos vienen VACÍOS, así que en vez del clear_hard
    de 32 teclas se usa select_all_field (HOME + Shift+End): si hay texto residual (retry)
    lo selecciona y el type lo reemplaza; si está vacío, no cuesta nada. Mucho más rápido."""
    r = campo.rectangle()
    ri.click((r.left + r.right) // 2, (r.top + r.bottom) // 2)
    time.sleep(0.05)
    try:
        campo.set_focus()
    except Exception:
        pass
    time.sleep(0.04)
    ri.select_all_field()
    ri.type_text(valor)
    time.sleep(0.08)
    return (campo.window_text() or "").strip()


def _llenar_campos(hform, tipo, codigo, nombre, rif):
    """Llena CÓDIGO → NOMBRE → RIF verificando cada uno en pantalla. Lanza
    DirectorioError si alguno no queda como se esperaba (el llamador cancela el alta)."""
    tops = CFG[tipo]["tops"]
    controles = _localizar_campos(hform, tops)

    plan = [("codigo", codigo), ("nombre", nombre), ("rif", rif)]
    for clave, _ in plan:
        if controles.get(clave) is None:
            raise DirectorioError(
                f"no localicé el campo {clave} (franja top≈{tops[clave]}) del alta de "
                f"{tipo} — ¿'Incluir' no abrió el modo alta? (revisar INCLUIR_REL/tops).")

    for clave, valor in plan:
        leido = _escribir_campo(controles[clave], valor)
        if _norm(leido) != _norm(valor):
            raise DirectorioError(
                f"el campo {clave} quedó en pantalla como {leido!r}, esperaba {valor!r}. "
                f"Nada se guarda.")
        log.info("Campo %s = %r verificado en pantalla.", clave, leido)



def _norm(v):
    return " ".join(str(v or "").upper().split())


# ── barra: Incluir / Guardar / Cancelar / Salir ───────────────────────────────
def _click_barra(hform, rel):
    _focus(hform)
    L, T, _, _ = win32gui.GetWindowRect(hform)
    ri.click(L + rel[0], T + rel[1])
    time.sleep(0.25)


def _incluir(hform):
    _click_barra(hform, INCLUIR_REL)
    time.sleep(0.2)


def _guardar(hform):
    _click_barra(hform, GUARDAR_REL)
    # tras Guardar puede pedir confirmación o avisar; aceptar lo que pregunte
    _responder(("&Ok", "Ok", "&Aceptar", "Aceptar", "&SI", "SI", "&Sí", "Sí", "&Yes", "Yes"), timeout=0.6)
    time.sleep(0.15)


def _cancelar(hform):
    """Descarta el alta SIN guardar (preview o abort): 'Cancelar' + responder 'No' si
    pregunta si desea guardar."""
    _click_barra(hform, CANCELAR_REL)
    _responder(("&NO", "No", "&No"), timeout=0.6)


def _cerrar_forma(hform):
    """Cierra la Forma al terminar: 'Salir' (coord) + confirmaciones + WM_CLOSE de
    respaldo, para dejar limpio antes del próximo registro."""
    if not hform or not win32gui.IsWindow(hform) or not win32gui.IsWindowVisible(hform):
        return
    _click_barra(hform, SALIR_REL)
    # Si la ventana ya cerró al pulsar Salir, terminamos inmediatamente sin esperas
    if not win32gui.IsWindow(hform) or not win32gui.IsWindowVisible(hform):
        return
    _responder(("&NO", "No", "&No", "&Ok", "Ok", "&SI", "SI"), timeout=0.5)
    for _ in range(2):
        if not win32gui.IsWindow(hform) or not win32gui.IsWindowVisible(hform):
            return
        try:
            win32gui.PostMessage(hform, win32con.WM_CLOSE, 0, 0)
        except Exception:
            pass
        _responder(("&NO", "No", "&No"), timeout=0.4)
        time.sleep(0.1)



# ── orquestador ───────────────────────────────────────────────────────────────
def registrar(tipo, nombre, rif, commit=False):
    """Da de alta una ficha de `tipo` ('cliente'|'proveedor') con nombre + rif.
    El código se deriva del rif (sin guiones). Return:
        {"ok": bool, "etapa": str, "detalle": str, "codigo": str|None}
    etapas éxito:  "commit" | "preview" | "ya_existe"
    etapas fallo pre-commit (reintentables, nada guardado): "abrir_hybrid" | "navegacion" | "campos"
    etapas AMBIGUAS (no reintentar solo): "guardar" | "verificacion_db"
    """
    if tipo not in CFG:
        return {"ok": False, "etapa": "navegacion", "detalle": f"tipo desconocido: {tipo!r}", "codigo": None}

    nombre = _norm(nombre)
    codigo = rdb.codigo_desde_rif(rif)
    if not nombre:
        return {"ok": False, "etapa": "campos", "detalle": "el nombre es obligatorio.", "codigo": None}
    if not codigo:
        return {"ok": False, "etapa": "campos",
                "detalle": "el RIF/cédula es obligatorio (de él se deriva el código).", "codigo": None}

    # idempotencia: si el código ya existe, no recrear (retry seguro)
    try:
        if rdb.existe_codigo(tipo, codigo):
            return {"ok": True, "etapa": "ya_existe",
                    "detalle": f"ya existe una ficha de {tipo} con código {codigo}; no se recrea.",
                    "codigo": codigo}
    except Exception as e:
        log.warning("No pude chequear si el código %s ya existe (%r); continúo con cautela.", codigo, e)

    import abrir_hybrid
    ok, msg = abrir_hybrid.asegurar_hybrid()
    if not ok:
        return {"ok": False, "etapa": "abrir_hybrid", "detalle": msg, "codigo": None}

    # navegación + alta
    try:
        hform = abrir_forma(tipo)
        _incluir(hform)
        _llenar_campos(hform, tipo, codigo, nombre, rif)
    except (DirectorioError, fp.FlujoError) as e:
        h = _find_form(CFG[tipo]["form_title"])
        _cancelar(h)
        _cerrar_forma(h)
        etapa = "campos" if isinstance(e, DirectorioError) and "campo" in str(e) else "navegacion"
        return {"ok": False, "etapa": etapa,
                "detalle": f"alta de {tipo} {nombre!r} cancelada (nada se tocó): {e}", "codigo": None}

    if not commit:
        _cancelar(hform)
        _cerrar_forma(hform)
        return {"ok": True, "etapa": "preview",
                "detalle": f"Preview del alta de {tipo} {nombre!r} (código {codigo}) verificado en "
                           f"pantalla y DESCARTADO (sin --commit).", "codigo": codigo}

    # COMMIT: Guardar (etapa AMBIGUA si falla)
    try:
        _guardar(hform)
    except Exception as e:
        return {"ok": False, "etapa": "guardar",
                "detalle": f"no pude confirmar el Guardar del alta de {tipo} {nombre!r}: {e}",
                "codigo": codigo}
    _cerrar_forma(hform)
    time.sleep(0.4)

    # verificación contra DBISAM
    try:
        ok_db, codigo_db, detalle_db = rdb.verificar(tipo, nombre, rif)
    except Exception as e:
        return {"ok": False, "etapa": "verificacion_db",
                "detalle": f"ficha guardada pero no pude verificar en DB: {e}", "codigo": codigo}

    if ok_db:
        return {"ok": True, "etapa": "commit", "detalle": detalle_db, "codigo": codigo_db}
    return {"ok": False, "etapa": "verificacion_db",
            "detalle": f"¡ALERTA! {detalle_db}", "codigo": codigo}


def registrar_cliente(nombre, rif, commit=False):
    return registrar("cliente", nombre, rif, commit=commit)


def registrar_proveedor(nombre, rif, commit=False):
    return registrar("proveedor", nombre, rif, commit=commit)


# ── CLI ───────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    raw = sys.argv[1:]
    args = [a for a in raw if not a.startswith("--")]
    rif = None
    if "--rif" in raw:
        i = raw.index("--rif")
        if i + 1 < len(raw):
            rif = raw[i + 1]
            args = [a for a in args if a != rif]
    if len(args) < 2 or not rif:
        print('Uso: python flujo_directorio_real.py <cliente|proveedor> "NOMBRE" --rif RIF [--commit]')
        sys.exit(1)

    tipo, nombre = args[0], args[1]
    try:
        res = registrar(tipo, nombre, rif, commit="--commit" in raw)
        print("\n=== RESULTADO ===")
        for k, v in res.items():
            print(f"  {k}: {v}")
    finally:
        try:
            import abrir_hybrid
            abrir_hybrid.cerrar_aislada()
        except Exception as e:
            print(f"(aviso: no pude cerrar la instancia aislada de Hybrid: {e})")
