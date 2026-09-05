"""
hybrid_price_writer.py — Escritor de PRECIO con AUTO-VERIFICACIÓN para HybridLite.

Estrategia a prueba de fallos:
  1. Localiza el campo 'Precio con impuesto USD' por geometría (panel POtrasMonedas).
  2. Escribe el valor por teclado.
  3. LEE de vuelta: confirma que el valor cayó en el campo correcto (con-impuesto)
     y que el 'sin-impuesto' = target/(1+iva). Si no, REINTENTA (hasta N veces).
  4. Si tras los reintentos no cuadra -> ABORTA pulsando 'Salir' (no compromete nada).
  5. Solo si la previsualización es correcta y commit=True: pulsa 'Aceptar' (clic real),
     luego 'Guardar' en la ficha.
  6. VERIFICACIÓN FINAL contra la base DBISAM (registro TIPO=1, PVPCONIMPUESTO1).
     Si el valor guardado != target -> reporta ERROR (no se queda callado).

Por defecto commit=False (previsualiza y verifica, sin guardar).

Uso:
    python hybrid_price_writer.py 00-002-024 13.50            # preview + verify (NO guarda)
    python hybrid_price_writer.py 00-002-024 13.50 --commit    # aplica de verdad
    python hybrid_price_writer.py 00-002-024 13.50 --iva 0.16
"""
import sys
import time
import logging
import win32gui
import win32process
from pywinauto import Application

import read_db_precio  # reutiliza la ruta y lógica de lectura DBISAM

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("price_writer")

TOL = 0.01          # tolerancia de comparación (1 centavo exacto)
MAX_RETRIES = 4


class PriceWriteError(Exception):
    pass


# PID objetivo opcional (aislamiento multi-instancia). Cuando está seteado,
# _find_dialog() y _click_guardar_ficha() ignoran ventanas de cualquier OTRA
# instancia de HybridLite — p.ej. la que un empleado tenga abierta mientras el
# bot trabaja en una instancia aparte. flujo_precio.set_target_pid() lo mantiene
# en sync con su propio filtro (ver ese módulo). None = sin restricción.
_target_pid = None


def set_target_pid(pid):
    global _target_pid
    _target_pid = pid


def clear_target_pid():
    global _target_pid
    _target_pid = None


def _pid_ok(hwnd):
    """True si `hwnd` pertenece al PID objetivo (o si no hay restricción)."""
    if _target_pid is None:
        return True
    try:
        return win32process.GetWindowThreadProcessId(hwnd)[1] == _target_pid
    except Exception:
        return False


def _num(s):
    """Convierte '7,929.98' / '14.00' / '1,556.38%' -> float."""
    if s is None:
        return None
    s = str(s).strip().replace(",", "").rstrip("%").strip()
    if s in ("", "-"):
        return None
    try:
        return float(s)
    except ValueError:
        return None


def _find_dialog():
    handles = []
    win32gui.EnumWindows(lambda h, _: handles.append(h), None)
    for h in handles:
        if (win32gui.GetClassName(h) == "TFHCostosPrecios"
                and win32gui.IsWindowVisible(h) and _pid_ok(h)):
            pid = win32process.GetWindowThreadProcessId(h)[1]
            app = Application(backend="win32").connect(process=pid, timeout=5)
            return app, app.window(class_name="TFHCostosPrecios")
    raise PriceWriteError("El diálogo 'Costos y Precios' no está abierto/visible.")


def _usd_fields(dlg):
    """Devuelve (campo_sin, campo_con) USD del panel POtrasMonedas:
    columna izquierda (x<900); el de arriba = sin impuesto, el de abajo = con impuesto."""
    panel = dlg.child_window(title="POtrasMonedas", class_name="TPanel")
    izq = sorted(
        [(c.rectangle().top, c) for c in panel.descendants(class_name="THybridEditNumber")
         if c.rectangle().left < 900],
        key=lambda t: t[0],
    )
    if len(izq) < 2:
        raise PriceWriteError("No ubiqué los dos campos USD (sin/con impuesto).")
    return izq[0][1], izq[-1][1]   # (sin, con)


def _type_value(dlg, field, value_str):
    """Enfoca el campo, selecciona todo y teclea el valor; Tab para commit+recalc."""
    dlg.set_focus()
    field.click_input()
    time.sleep(0.2)
    # seleccionar todo de forma robusta (Ctrl+A y además Home+Shift+End)
    field.type_keys("^a", set_foreground=False)
    field.type_keys("{HOME}+{END}", set_foreground=False)
    time.sleep(0.1)
    field.type_keys("{DELETE}", set_foreground=False)
    time.sleep(0.1)
    field.type_keys(value_str, with_spaces=False, set_foreground=False)
    time.sleep(0.15)
    field.type_keys("{TAB}", set_foreground=False)
    time.sleep(0.4)


def _write_with_verify(dlg, target, iva):
    """Escribe target en 'con impuesto' y verifica que cayó bien. Reintenta.
    Devuelve dict con los valores leídos si OK; lanza PriceWriteError si no converge."""
    sin_field, con_field = _usd_fields(dlg)
    target_str = f"{target:.2f}"

    for intento in range(1, MAX_RETRIES + 1):
        _type_value(dlg, con_field, target_str)
        con_val = _num(con_field.window_text())
        sin_val = _num(sin_field.window_text())
        esperado_sin = target / (1.0 + iva)
        log.info("Intento %d: con=%.4f sin=%.4f (esperado_sin=%.4f)",
                 intento, con_val or -1, sin_val or -1, esperado_sin)

        con_ok = con_val is not None and abs(con_val - target) <= TOL
        sin_ok = sin_val is not None and abs(sin_val - esperado_sin) <= max(TOL, esperado_sin * 0.01)
        if con_ok and sin_ok:
            return {"con": con_val, "sin": sin_val}
        log.warning("Intento %d no cuadró (con_ok=%s sin_ok=%s). Reintentando...",
                    intento, con_ok, sin_ok)

    raise PriceWriteError(
        f"No logré fijar el precio con impuesto en {target} tras {MAX_RETRIES} intentos. "
        f"Último: con={con_val}, sin={sin_val}. NO se compromete nada."
    )


def _abort(dlg):
    """Descarta el diálogo sin guardar (botón Salir)."""
    try:
        dlg.set_focus()
        dlg.child_window(title="Salir", class_name="TButton").click_input()
        log.info("Diálogo descartado con 'Salir'.")
    except Exception as e:
        log.error("No pude pulsar 'Salir' automáticamente: %s. Ciérralo a mano.", e)


def _db_valores_usd(codigo):
    """Lee precio y costo USD en una SOLA pasada de DBISAM. Devuelve (precio, costo)."""
    db = read_db_precio.pydbisam.PyDBISAM(read_db_precio.RUTA)
    campos = db.fields()
    idx = {n: i for i, n in enumerate(campos)}
    cod_i = idx.get("TPC_CODIGOPRODUCTO")
    tipo_i = idx.get("TPC_TIPO")
    pvp_i = idx.get("TPC_PVPCONIMPUESTO1")
    costo_i = idx.get("TPC_COSTOACTUAL")
    if cod_i is None or tipo_i is None:
        return None, None
    c_target = codigo.strip()
    for row in db.rows():
        if str(row[cod_i]).strip() == c_target and row[tipo_i] == 1:
            precio = float(row[pvp_i]) if pvp_i is not None and row[pvp_i] is not None else None
            costo = float(row[costo_i]) if costo_i is not None and row[costo_i] is not None else None
            return precio, costo
    return None, None


def _db_valores_usd_batch(codigos):
    """Lee precios y costos USD para una lista de códigos en una SOLA pasada de DBISAM.
    Devuelve dict {codigo: (precio, costo)}."""
    cod_set = {str(c).strip() for c in codigos}
    db = read_db_precio.pydbisam.PyDBISAM(read_db_precio.RUTA)
    campos = db.fields()
    idx = {n: i for i, n in enumerate(campos)}
    cod_i = idx.get("TPC_CODIGOPRODUCTO")
    tipo_i = idx.get("TPC_TIPO")
    pvp_i = idx.get("TPC_PVPCONIMPUESTO1")
    costo_i = idx.get("TPC_COSTOACTUAL")
    res = {}
    if cod_i is None or tipo_i is None:
        return res
    for row in db.rows():
        c = str(row[cod_i]).strip()
        if c in cod_set and row[tipo_i] == 1:
            precio = float(row[pvp_i]) if pvp_i is not None and row[pvp_i] is not None else None
            costo = float(row[costo_i]) if costo_i is not None and row[costo_i] is not None else None
            res[c] = (precio, costo)
            if len(res) == len(cod_set):
                break
    return res


def _db_precio_usd(codigo):
    """Lee de DBISAM el PVPCONIMPUESTO1 del registro TIPO=1 (USD)."""
    p, _ = _db_valores_usd(codigo)
    return p


def _db_costo_usd(codigo):
    """Lee de DBISAM el TPC_COSTOACTUAL del registro TIPO=1 (USD), SOLO LECTURA."""
    _, c = _db_valores_usd(codigo)
    return c


def set_price(codigo, target, iva=0.16, commit=False):
    """Punto de entrada. Devuelve dict resultado."""
    target = float(target)
    db_antes = _db_precio_usd(codigo)
    log.info("Precio USD en DB ANTES: %s", db_antes)

    app, dlg = _find_dialog()

    try:
        preview = _write_with_verify(dlg, target, iva)
    except PriceWriteError as e:
        _abort(dlg)
        return {"ok": False, "etapa": "escritura", "detalle": str(e), "db_antes": db_antes}

    log.info("Previsualización correcta: con=%.2f sin=%.4f", preview["con"], preview["sin"])

    if not commit:
        return {"ok": True, "etapa": "preview", "detalle": "Valor fijado y verificado en pantalla "
                "(NO guardado). Usa --commit para aplicar.",
                "preview": preview, "db_antes": db_antes}

    # --- COMMIT ---
    log.info("Pulsando 'Aceptar' (clic real)...")
    dlg.set_focus()
    dlg.child_window(title="Aceptar", class_name="TButton").click_input()
    time.sleep(0.8)
    if win32gui.IsWindow(dlg.handle) and win32gui.IsWindowVisible(dlg.handle):
        log.warning("El diálogo sigue visible tras Aceptar; reintento clic...")
        try:
            dlg.child_window(title="Aceptar", class_name="TButton").click_input()
            time.sleep(0.8)
        except Exception:
            pass

    # Guardar en la ficha
    guardado = _click_guardar_ficha()
    if not guardado:
        return {"ok": False, "etapa": "guardar",
                "detalle": "Aceptar OK pero no pude pulsar 'Guardar' en la ficha. "
                           "Revisa manualmente.", "db_antes": db_antes}

    time.sleep(1.0)
    db_despues = _db_precio_usd(codigo)
    log.info("Precio USD en DB DESPUÉS: %s", db_despues)

    if db_despues is not None and abs(db_despues - target) <= TOL:
        return {"ok": True, "etapa": "commit", "detalle": f"Precio aplicado y VERIFICADO en DB: {db_despues}",
                "db_antes": db_antes, "db_despues": db_despues}
    return {"ok": False, "etapa": "verificacion_db",
            "detalle": f"¡ALERTA! El DB quedó en {db_despues}, no en {target}. Revisar.",
            "db_antes": db_antes, "db_despues": db_despues}


def _click_guardar_ficha():
    """Busca la ventana de la Ficha de Inventario y pulsa 'Guardar'."""
    handles = []
    win32gui.EnumWindows(lambda h, _: handles.append(h), None)
    for h in handles:
        title = (win32gui.GetWindowText(h) or "")
        if "Ficha de Inventario" in title and win32gui.IsWindowVisible(h) and _pid_ok(h):
            pid = win32process.GetWindowThreadProcessId(h)[1]
            app = Application(backend="win32").connect(process=pid, timeout=5)
            win = app.window(handle=h)
            try:
                win.set_focus()
                win.child_window(title="Guardar", class_name="TButton").click_input()
                log.info("'Guardar' pulsado en la ficha.")
                return True
            except Exception as e:
                log.error("No encontré/clic 'Guardar' en la ficha: %s", e)
                return False
    log.error("No encontré la ventana 'Ficha de Inventario' para Guardar.")
    return False


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    if len(args) < 2:
        print("Uso: python hybrid_price_writer.py <codigo> <precio_usd> [--commit] [--iva 0.16]")
        sys.exit(1)
    codigo = args[0]
    target = float(args[1])
    commit = "--commit" in sys.argv
    iva = 0.16
    if "--iva" in sys.argv:
        iva = float(sys.argv[sys.argv.index("--iva") + 1])

    res = set_price(codigo, target, iva=iva, commit=commit)
    print("\n=== RESULTADO ===")
    for k, v in res.items():
        print(f"  {k}: {v}")
