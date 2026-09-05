"""
flujo_stock_real.py — Ajuste de CANTIDAD (stock) en HybridLiteOS con INPUT REAL.

Hace un documento de ajuste por CONTEO físico (kardex-safe), replicando la grabación
del dueño (2026-07-07):

  Menú Inventario → 'Ajustes de inventario' (TFormHTransaccion_Ajustes)
    → celda Código: teclear código (numérico, guion = '-' del numpad) → ENTER (carga)
    → celda Conteo: teclear la cantidad deseada → ENTER (recalcula Diferencia)
    → [verificar código y diferencia leyendo las celdas]
    → commit: Totalizar → Confirmación '&SI' → cerrar comprobante (Vista Previa)
    → Salir de la ventana de Ajustes (no dejar el comprobante nuevo abierto)
    → verificación final contra DBISAM (TExistenciaInv.EIN_EXISTENCIA)

MODELO: el 'Conteo' es la cantidad ABSOLUTA que quedará. Con --delta, la cantidad
dada se SUMA a la existencia actual (conteo = existencia + delta).

⚠️ Cada commit crea un DOCUMENTO PERMANENTE de kardex + comprobante. No se descarta
como el precio. Preview (sin --commit) llena y CANCELA (no crea documento).

USO:
    python flujo_stock_real.py 00-002-024 5          # preview: dejaría stock=5 (no guarda)
    python flujo_stock_real.py 00-002-024 5 --commit # aplica stock=5 y verifica
    python flujo_stock_real.py 00-002-024 3 --delta --commit   # suma 3 al stock actual
"""
import os
import sys
import time
import logging

import win32gui

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

import flujo_precio as fp
import realinput as ri
import read_db_existencia as dbex

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("stock_real")

DIR = os.path.dirname(os.path.abspath(__file__))
AJU_CLASS = "TFormHTransaccion_Ajustes"
CONF_CLASS = "TFConfirmacion"
PREVIEW_CLASS = "TfrxPreviewForm"
TOL = 0.001
ROW_H = 24  # alto de fila estándar de la grilla (según grabación del dueño)
MAX_FILAS_LOTE = 10  # filas por documento; 10*24px=240px cae holgado dentro del
                      # área visible de la grilla (~15 filas sin scroll). Lotes
                      # más largos se trocean en varios documentos consecutivos.


class StockError(Exception):
    pass


def _cerrar_aislada_cli():
    """Cierra la instancia AISLADA que abrió ESTA corrida standalone, para no
    dejar ventanas de Hybrid acumuladas (llegaron a verse 13 a la vez, y tantas
    ventanas de la misma clase desordenan el targeting: el input real acaba en
    la ventana equivocada).

    Solo se llama desde __main__. El listener es un proceso largo que REUTILIZA
    una sola instancia entre pasadas e importa ajustar_stock[_lote]
    directamente, así que no pasa por aquí y su reuso no se rompe. Mismo patrón
    que flujo_pedido_real / flujo_directorio_real."""
    try:
        import abrir_hybrid
        abrir_hybrid.cerrar_aislada()
    except Exception as e:
        print(f"(aviso: no pude cerrar la instancia aislada de Hybrid: {e})")


def _focus(hwnd):
    if not hwnd:
        return
    try:
        fp._win(hwnd).set_focus()
    except Exception:
        pass
    try:
        win32gui.SetForegroundWindow(hwnd)
    except Exception:
        pass
    time.sleep(0.25)


def _num(s):
    if s is None:
        return None
    s = str(s).strip().replace(",", "")
    if s in ("", "-"):
        return None
    try:
        return float(s)
    except ValueError:
        return None


# ── apertura ─────────────────────────────────────────────────────────────────
def _cerrar_ficha_si_abierta():
    """Cierra la Ficha de items (TTConfigForm) si quedó abierta de un flujo de
    precio/costo de forma instantánea enviando WM_CLOSE."""
    hf = fp._find_hwnd(fp.FICHA_CLASS)
    if not hf:
        return
    log.info("Cerrando la Ficha de items instantáneamente...")
    import win32con
    try:
        win32gui.PostMessage(hf, win32con.WM_CLOSE, 0, 0)
    except Exception:
        pass

    t0 = time.time()
    while time.time() - t0 < 1.5:
        if not fp._find_hwnd(fp.FICHA_CLASS):
            return
        time.sleep(0.03)


def abrir_ajustes():
    import json
    ha = fp._find_hwnd(AJU_CLASS)
    if ha:
        return ha
    _cerrar_ficha_si_abierta()
    hmain = fp._find_hwnd(fp.MAIN_CLASS)
    if not hmain:
        raise StockError("HybridLiteOS no está abierto.")
    main = fp._win(hmain)
    _focus(hmain)
    try:
        b = main.child_window(title="Ajustes de inventario", class_name="TAdvGlassButton")
        b.wait("exists visible", timeout=1.5)
    except Exception:
        puntos = json.load(open(os.path.join(DIR, "calib_puntos.json"), encoding="utf-8"))
        rel = puntos["menu_inventario"]["rel"]
        L, T, _, _ = win32gui.GetWindowRect(hmain)
        ri.click(L + rel[0], T + rel[1])
        time.sleep(0.4)
        b = main.child_window(title="Ajustes de inventario", class_name="TAdvGlassButton")
        b.wait("exists visible", timeout=6)
    r = b.rectangle()
    ri.click((r.left + r.right) // 2, (r.top + r.bottom) // 2)
    t0 = time.time()
    while time.time() - t0 < 15:
        ha = fp._find_hwnd(AJU_CLASS)
        if ha:
            time.sleep(0.5)
            return ha
        time.sleep(0.3)
    raise StockError("No abrió la ventana de Ajustes de inventario.")


# ── grilla y celdas ──────────────────────────────────────────────────────────
def _grilla(aj):
    grids = aj.descendants(class_name="TAdvStringGrid")
    if not grids:
        raise StockError("No encontré la grilla de ítems.")
    return max(grids, key=lambda c: (lambda r: (r.right - r.left) * (r.bottom - r.top))(c.rectangle()))


def _celdas(aj, grid, fila=0):
    """Controles de la fila activa: {codigo, conteo, existencia, diferencia}.
    OJO: en la columna Código conviven un editor VACÍO superpuesto (x~17) y la
    celda con el valor (x~18); para 'codigo' se prefiere el que TIENE texto.
    Los numéricos (Conteo/Existencia/Diferencia) están en x distintos y ordenados.

    'fila' (default 0) desplaza la ventana de búsqueda a la fila N-ésima de la
    grilla (0 = primera fila de datos), para poder verificar lotes multi-fila.
    Con fila=0 el comportamiento es IDÉNTICO al original (usado por el flujo
    single vía cargar_y_fijar). Solo la fila ACTIVA (con foco) tiene editores
    THybridEdit/THybridEditNumber vivos: si no se encuentran, reintenta hasta
    3 veces (0.4s) antes de devolver celdas vacías."""
    gr = grid.rectangle()
    y0, y1 = gr.top + fila * ROW_H, gr.top + fila * ROW_H + 46

    for intento in range(3):
        edits = [c for c in aj.descendants(class_name="THybridEdit")
                 if y0 < c.rectangle().top < y1 and gr.left <= c.rectangle().left < gr.right]
        nums = [c for c in aj.descendants(class_name="THybridEditNumber")
                if y0 < c.rectangle().top < y1 and gr.left <= c.rectangle().left < gr.right]
        if edits or nums:
            break
        if intento < 2:
            time.sleep(0.2)
    edits.sort(key=lambda c: c.rectangle().left)
    nums.sort(key=lambda c: c.rectangle().left)

    # código = celda de la columna Código (left < 270) que tenga texto; si ninguna, la 1a
    cod_cands = [e for e in edits if e.rectangle().left < 270]
    codigo = None
    for e in cod_cands:
        if (e.window_text() or "").strip():
            codigo = e
            break
    if codigo is None and cod_cands:
        codigo = cod_cands[0]

    conteo = nums[0] if len(nums) >= 1 else None
    existencia = nums[1] if len(nums) >= 2 else None
    diferencia = nums[2] if len(nums) >= 3 else None
    return {"codigo": codigo, "conteo": conteo, "existencia": existencia,
            "diferencia": diferencia}


def _leer(aj, grid, fila=0):
    c = _celdas(aj, grid, fila)
    def txt(x): return (x.window_text() if x else "") or ""
    return {
        "codigo": txt(c["codigo"]).strip(),
        "conteo": _num(txt(c["conteo"])),
        "existencia": _num(txt(c["existencia"])),
        "diferencia": _num(txt(c["diferencia"])),
    }


# ── pasos ────────────────────────────────────────────────────────────────────
def _borrar_items(aj):
    """Vacía la grilla (botón 'Borrar items'), confirmando si preguntara."""
    try:
        aj.child_window(title="&Borrar items", class_name="TFlatButton").click_input()
        time.sleep(0.4)
    except Exception:
        return
    for _ in range(2):
        h = fp._find_hwnd(CONF_CLASS) or fp._find_hwnd("TMessageForm")
        if not h:
            break
        m = fp._win(h)
        for t in ("&SI", "SI", "Sí", "&Sí", "&Yes", "Yes", "Aceptar"):
            try:
                m.child_window(title=t).click_input(); break
            except Exception:
                continue
        time.sleep(0.4)


def cargar_y_fijar(aj, grid, codigo, target, codigo_esperado=None):
    """Flujo single (UN producto): limpia residuo si la grilla trae otro código
    cargado, y delega la coreografía de carga/verificación/posteo en
    cargar_y_fijar_fila con fila=0 (clic inicial en la celda Código de la 1a
    fila de datos + la misma verificación código/conteo antes de postear).
    La coreografía en sí -- FIEL a la grabación del dueño (2026-07-08) que SÍ
    postea la fila: clic celda Código → teclear código LENTO → ENTER (carga y
    el cursor SALTA a la celda Conteo) → teclear la cantidad DIRECTO → ENTER →
    ENTER -- vive únicamente en cargar_y_fijar_fila.

    codigo_esperado: si se da, `codigo` es solo la BÚSQUEDA (p.ej. un código de
    barras usado como alias para esquivar una colisión código interno<->barras,
    ver hybrid-colision-codigo-barras) y la verificación de fila se hace contra
    codigo_esperado (el código interno real que debe quedar cargado), no contra
    el texto tecleado. Por defecto (None) el comportamiento es IDÉNTICO al
    original: se verifica contra el propio `codigo`."""
    objetivo = (codigo_esperado or codigo).strip()
    d = _leer(aj, grid)
    if d["codigo"] and d["codigo"].lower() != objetivo.lower():
        _borrar_items(aj)          # limpiar residuo/otro producto
        time.sleep(0.4)

    return cargar_y_fijar_fila(aj, grid, codigo, target, fila=0, codigo_esperado=codigo_esperado)


def cargar_y_fijar_fila(aj, grid, codigo, target, fila, codigo_esperado=None):
    """Igual que cargar_y_fijar, pero para la fila N-ésima de un LOTE multi-fila
    (fila=0 es idéntico al flujo single: mismo punto de clic, misma verificación).
    Tras postear una fila (ENTER,ENTER) HybridLite deja el cursor en la celda
    Código de la fila SIGUIENTE ya seleccionada (confirmado por el dueño
    2026-07-12), así que SOLO la fila 0 clica/enfoca: las filas siguientes se
    tipean directo sobre ese cursor auto-posicionado -- clicar/re-enfocar lo
    perturbaría.
        (fila 0) clic celda Código → código LENTO → ENTER (carga, salta a
        Conteo) → cantidad DIRECTO → verificar → ENTER, ENTER (postea).
    Verifica código y conteo ANTES de postear, leyendo la ventana de la fila
    'fila' (vía _leer(..., fila)). NO hace _borrar_items por residuo (el lote
    limpia la grilla una única vez al inicio, en ajustar_stock_lote).

    codigo_esperado: ver cargar_y_fijar -- si se da, `codigo` es la BÚSQUEDA
    tecleada y la fila se valida contra codigo_esperado en vez de contra
    `codigo`. None (default) preserva el comportamiento original al pie de la
    letra (se compara contra el propio `codigo` tecleado)."""
    objetivo = (codigo_esperado or codigo).strip()
    if fila == 0:
        gr = grid.rectangle()
        _focus(fp._find_hwnd(AJU_CLASS))
        ri.click(gr.left + 196, gr.top + 40)   # celda Código, fila 0 (la única que se clica)
        time.sleep(0.15)
    ri.type_code(codigo)                       # LENTO (evita truncado/búsqueda)
    time.sleep(0.2)
    ri.press("ENTER")                          # carga el producto y salta a Conteo
    time.sleep(0.6)

    # verificar que cargó el producto correcto ANTES de tocar la cantidad
    datos = None
    for _ in range(6):
        datos = _leer(aj, grid, fila)
        if datos["codigo"].lower() == objetivo.lower():
            break
        time.sleep(0.2)
    if not datos or datos["codigo"].lower() != objetivo.lower():
        raise StockError(f"La grilla NO cargó {objetivo} (buscado como {codigo!r}) en la "
                         f"fila {fila} (código en grilla={datos['codigo'] if datos else None!r}). "
                         f"Abortando para no ajustar otro producto.")
    existencia_ui = datos["existencia"]
    log.info("Fila %s: %s cargado (buscado como %s). Existencia=%s, Conteo actual=%s.",
             fila, objetivo, codigo, existencia_ui, datos["conteo"])

    # el cursor ya está en Conteo: teclear el objetivo DIRECTO (reemplaza el auto-relleno)
    ri.type_number(f"{target:g}")
    time.sleep(0.15)

    # VERIFICAR ANTES de postear (la fila aún es editable y sus celdas son legibles).
    # Tras el 2º ENTER la fila se 'postea' y queda estática -> ya no se puede leer.
    datos = _leer(aj, grid, fila)
    log.info("Fila %s antes de postear: código=%s conteo=%s existencia=%s",
             fila, datos["codigo"], datos["conteo"], datos["existencia"])
    if datos["codigo"].lower() != objetivo.lower():
        raise StockError(f"La grilla muestra {datos['codigo']!r} en la fila {fila}, no {objetivo}. "
                         f"Abortando (NADA se guarda).")
    if datos["conteo"] is None or abs(datos["conteo"] - target) > TOL:
        raise StockError(f"El Conteo no quedó en {target} en la fila {fila} "
                         f"(quedó {datos['conteo']}). NADA se guarda.")
    if existencia_ui is None:
        existencia_ui = datos["existencia"]

    # postear la fila: ENTER (confirma conteo) + ENTER (postea -> lista para la siguiente)
    ri.press("ENTER")
    time.sleep(0.25)
    ri.press("ENTER")
    time.sleep(0.3)
    datos["existencia"] = existencia_ui
    log.info("Fila %s: %s existencia=%s target=%s", fila, codigo, existencia_ui, target)
    return datos


def _cancelar(aj):
    """Descarta el documento sin guardar (Cancelar)."""
    for titulo in ("C&ancelar", "Cancelar"):
        try:
            aj.child_window(title=titulo, class_name="TFlatButton").click_input()
            time.sleep(0.4)
            break
        except Exception:
            continue
    # confirm 'No' si preguntara
    for _ in range(2):
        h = fp._find_hwnd(CONF_CLASS) or fp._find_hwnd("TMessageForm")
        if not h:
            break
        m = fp._win(h)
        for t in ("&NO", "No", "&No"):
            try:
                m.child_window(title=t).click_input(); break
            except Exception:
                continue
        time.sleep(0.5)


def _totalizar_y_guardar(aj):
    """Totalizar → Confirmación '&SI' → cerrar comprobante (Vista Previa)."""
    ha = fp._find_hwnd(AJU_CLASS)
    _focus(ha)
    b = aj.child_window(title="&Totalizar", class_name="TFlatButton")
    r = b.rectangle()
    ri.click((r.left + r.right) // 2, (r.top + r.bottom) // 2)
    time.sleep(1.0)

    # Confirmación TFConfirmacion -> &SI
    t0 = time.time()
    confirmado = False
    while time.time() - t0 < 6:
        h = fp._find_hwnd(CONF_CLASS)
        if h:
            _focus(h)
            for t in ("&SI", "&Sí", "SI", "Sí", "&Yes"):
                try:
                    bb = fp._win(h).child_window(title=t, class_name="TFlatButton")
                    rr = bb.rectangle()
                    ri.click((rr.left + rr.right) // 2, (rr.top + rr.bottom) // 2)
                    confirmado = True
                    log.info("Confirmación '%s' pulsada.", t)
                    break
                except Exception:
                    continue
            if confirmado:
                break
        time.sleep(0.3)

    # cerrar el comprobante (Vista Previa) si aparece — Escape real + fallbacks
    import win32con
    t0 = time.time()
    while time.time() - t0 < 8:
        h = fp._find_hwnd(PREVIEW_CLASS)
        if h:
            time.sleep(0.5)
            try:
                win32gui.SetForegroundWindow(h)
                time.sleep(0.3)
                ri.press("ESC")
                time.sleep(0.5)
                if fp._find_hwnd(PREVIEW_CLASS):
                    win32gui.PostMessage(h, win32con.WM_SYSCOMMAND, win32con.SC_CLOSE, 0)
                    time.sleep(0.5)
                if fp._find_hwnd(PREVIEW_CLASS):
                    win32gui.PostMessage(h, win32con.WM_CLOSE, 0, 0)
                log.info("Comprobante (Vista Previa) cerrado.")
            except Exception:
                pass
            time.sleep(0.8)
            break
        time.sleep(0.3)
    # asegurar que no quedó ningún comprobante bloqueando
    for _ in range(3):
        h = fp._find_hwnd(PREVIEW_CLASS)
        if not h:
            break
        try:
            win32gui.PostMessage(h, win32con.WM_CLOSE, 0, 0)
        except Exception:
            pass
        time.sleep(0.4)
    return confirmado


def _salir_ajustes(aj):
    """Cierra la ventana de Ajustes (botón 'Salir') al terminar el flujo.

    Tras Cancelar o Totalizar, HybridLite deja un comprobante nuevo VACÍO abierto
    (ej. 00000213*). Sin este paso esa ventana queda colgada y el próximo item
    la reutiliza en un estado sucio. Se llama SIEMPRE después de cancelar o
    totalizar, es decir cuando el documento actual ya no tiene cambios pendientes,
    así 'Salir' no dispara un diálogo de "¿guardar cambios?".
    """
    ha = fp._find_hwnd(AJU_CLASS)
    if not ha:
        return  # ya cerrada
    _focus(ha)
    for titulo in ("&Salir", "Salir"):
        try:
            b = aj.child_window(title=titulo, class_name="TFlatButton")
            r = b.rectangle()
            ri.click((r.left + r.right) // 2, (r.top + r.bottom) // 2)
            time.sleep(0.4)
            break
        except Exception:
            continue
    # confirmar si preguntara (el doc visible está vacío -> se sale, no se guarda)
    for _ in range(2):
        h = fp._find_hwnd(CONF_CLASS) or fp._find_hwnd("TMessageForm")
        if not h:
            break
        m = fp._win(h)
        for t in ("&SI", "SI", "Sí", "&Sí", "&Yes", "Yes", "Aceptar"):
            try:
                m.child_window(title=t).click_input(); break
            except Exception:
                continue
        time.sleep(0.4)
    # fallback: si el botón no cerró la ventana, forzar cierre por mensaje
    import win32con
    for _ in range(3):
        h = fp._find_hwnd(AJU_CLASS)
        if not h:
            break
        try:
            win32gui.PostMessage(h, win32con.WM_CLOSE, 0, 0)
        except Exception:
            pass
        time.sleep(0.4)


# ── orquestador ──────────────────────────────────────────────────────────────
def ajustar_stock(codigo, cantidad, commit=False, delta=False, codigo_esperado=None):
    """codigo_esperado: ver cargar_y_fijar -- si se da, `codigo` es solo la
    búsqueda (alias/código de barras) y todo lo demás (lectura DB antes/después,
    verificación de fila) se hace contra codigo_esperado, el código interno
    real. None (default): comportamiento idéntico al original."""
    cantidad = float(cantidad)
    objetivo = (codigo_esperado or codigo).strip()

    # asegurar que Hybrid esté abierto y logueado (lo lanza si está cerrado)
    import abrir_hybrid
    ok, msg = abrir_hybrid.asegurar_hybrid()
    if not ok:
        return {"ok": False, "etapa": "abrir_hybrid", "detalle": msg}

    total_antes, filas_antes = dbex.existencia(objetivo)
    log.info("Existencia en DB ANTES de %s: %s", objetivo, total_antes)

    # fallo abriendo la ventana = 100% pre-commit -> etapa reintentable
    try:
        ha = abrir_ajustes()
        aj = fp._win(ha)
        grid = _grilla(aj)
    except StockError as e:
        return {"ok": False, "etapa": "carga/conteo", "detalle": str(e), "db_antes": total_antes}

    # objetivo: absoluto o (con --delta) existencia_DB + cantidad
    target = total_antes + cantidad if delta else cantidad
    log.info("Objetivo de conteo (absoluto) = %s  (%s)", target,
             f"delta {cantidad} sobre {total_antes}" if delta else "absoluto")

    try:
        datos = cargar_y_fijar(aj, grid, codigo, target, codigo_esperado=codigo_esperado)
    except StockError as e:
        _cancelar(aj)
        _salir_ajustes(aj)
        return {"ok": False, "etapa": "carga/conteo", "detalle": str(e), "db_antes": total_antes}
    existencia_ui = datos["existencia"] if datos["existencia"] is not None else total_antes

    if not commit:
        _cancelar(aj)
        _salir_ajustes(aj)
        return {"ok": True, "etapa": "preview",
                "detalle": f"Verificado en pantalla y DESCARTADO (sin --commit). "
                           f"Dejaría stock={target} (dif {datos['diferencia']}).",
                "codigo": objetivo, "existencia": existencia_ui, "target": target,
                "db_antes": total_antes}

    # COMMIT (crea documento permanente)
    if not _totalizar_y_guardar(aj):
        return {"ok": False, "etapa": "totalizar",
                "detalle": "No pude confirmar el guardado (Totalizar/SÍ).", "db_antes": total_antes}

    # cerrar la ventana de Ajustes (comprobante nuevo vacío) tras guardar
    _salir_ajustes(aj)

    time.sleep(1.2)
    total_despues, _ = dbex.existencia(objetivo)
    log.info("Existencia en DB DESPUÉS de %s: %s", objetivo, total_despues)
    if abs(total_despues - target) <= 0.01:
        return {"ok": True, "etapa": "commit",
                "detalle": f"Stock ajustado y VERIFICADO en DB: {total_despues}",
                "db_antes": total_antes, "db_despues": total_despues, "target": target}
    return {"ok": False, "etapa": "verificacion_db",
            "detalle": f"¡ALERTA! DB quedó en {total_despues}, no en {target}. Revisar.",
            "db_antes": total_antes, "db_despues": total_despues, "target": target}


def _lote_fallo_uniforme(items_lote, etapa, detalle):
    """Arma el resultado de fallo para TODO el lote con el mismo motivo (usado
    para duplicados, abrir_hybrid, lectura de existencia previa, y 'totalizar')."""
    resultados = {it["item_id"]: {"ok": False, "etapa": etapa, "detalle": detalle}
                  for it in items_lote}
    return {"ok": False, "etapa": etapa, "detalle": detalle, "resultados": resultados}


def _lote_un_documento(items_chunk, targets, existencias_antes, commit):
    """Procesa UN documento de ajuste para items_chunk (a lo sumo MAX_FILAS_LOTE
    ítems). Abre la ventana de Ajustes, limpia la grilla, llena y verifica cada
    fila, y cierra el documento (cancelado en preview/fallo, o totalizado y
    verificado contra DB en commit).

    targets / existencias_antes: dict[item_id -> float], ya calculados por
    ajustar_stock_lote para el LOTE COMPLETO (no solo este chunk).

    Return: mismo shape que ajustar_stock_lote, pero acotado a items_chunk:
        {"ok": bool, "etapa": str, "detalle": str, "resultados": dict[item_id, dict]}
    """
    # fallo abriendo la ventana = 100% pre-commit -> etapa reintentable
    try:
        ha = abrir_ajustes()
        aj = fp._win(ha)
        grid = _grilla(aj)
    except StockError as e:
        log.error("Lote: no se pudo abrir la ventana de Ajustes: %s", e)
        return _lote_fallo_uniforme(items_chunk, "carga/conteo", str(e))
    _borrar_items(aj)   # grilla limpia al inicio de CADA documento

    # 1) llenar y verificar fila por fila (fila = índice DENTRO del chunk)
    detalle_por_item = {}
    culpable = None
    for fila, it in enumerate(items_chunk):
        codigo, target = it["codigo"], targets[it["item_id"]]
        try:
            datos = cargar_y_fijar_fila(aj, grid, codigo, target, fila,
                                        codigo_esperado=it.get("codigo_esperado"))
        except StockError as e:
            culpable = it
            detalle_por_item[it["item_id"]] = str(e)
            break
        detalle_por_item[it["item_id"]] = (
            f"Verificado en pantalla: existencia_db={existencias_antes[it['item_id']]} "
            f"target={target} (dif {datos['diferencia']}).")

    if culpable is not None:
        # CUALQUIER fila falló su verificación -> cancelar este documento, nada se aplicó
        _cancelar(aj)
        _salir_ajustes(aj)
        resultados = {}
        for it in items_chunk:
            if it["item_id"] == culpable["item_id"]:
                detalle = detalle_por_item[it["item_id"]]
            else:
                detalle = f"lote cancelado por fallo en {culpable['codigo']}"
            resultados[it["item_id"]] = {"ok": False, "etapa": "carga/conteo", "detalle": detalle}
        detalle_global = (f"Lote CANCELADO (nada se aplicó): fallo en {culpable['codigo']} "
                          f"- {detalle_por_item[culpable['item_id']]}")
        log.error(detalle_global)
        return {"ok": False, "etapa": "carga/conteo", "detalle": detalle_global,
                "resultados": resultados}

    # 2) preview: todas las filas verificadas -> cancelar (no crea documento)
    if not commit:
        _cancelar(aj)
        _salir_ajustes(aj)
        resultados = {it["item_id"]: {"ok": True, "etapa": "preview",
                                       "detalle": detalle_por_item[it["item_id"]]}
                      for it in items_chunk}
        detalle_global = (f"Preview de {len(items_chunk)} ítem(s) verificado(s) en pantalla y "
                          f"DESCARTADO (sin --commit).")
        return {"ok": True, "etapa": "preview", "detalle": detalle_global, "resultados": resultados}

    # 3) COMMIT: Totalizar UNA sola vez para este documento
    if not _totalizar_y_guardar(aj):
        detalle = "No pude confirmar el guardado (Totalizar/SÍ). Estado AMBIGUO, no reintentable."
        log.error(detalle)
        return _lote_fallo_uniforme(items_chunk, "totalizar", detalle)

    _salir_ajustes(aj)
    time.sleep(1.2)

    # 4) verificación DB por item
    resultados = {}
    todos_ok = True
    for it in items_chunk:
        codigo, target = it["codigo"], targets[it["item_id"]]
        codigo_db = it.get("codigo_esperado") or codigo
        total_despues, _ = dbex.existencia(codigo_db)
        log.info("Lote verificación DB: item_id=%s codigo=%s despues=%s target=%s",
                 it["item_id"], codigo_db, total_despues, target)
        if total_despues is not None and abs(total_despues - target) <= 0.01:
            resultados[it["item_id"]] = {"ok": True, "etapa": "commit",
                "detalle": f"Stock ajustado y VERIFICADO en DB: {total_despues}"}
        else:
            todos_ok = False
            resultados[it["item_id"]] = {"ok": False, "etapa": "verificacion_db",
                "detalle": f"¡ALERTA! DB quedó en {total_despues}, no en {target}. Revisar."}

    etapa_global = "commit" if todos_ok else "verificacion_db"
    detalle_global = (f"Lote de {len(items_chunk)} ítem(s) totalizado y guardado. "
                      f"{'Todos verificados en DB.' if todos_ok else 'ALERTA: hay ítems que no cuadran en DB, revisar resultados.'}")
    return {"ok": todos_ok, "etapa": etapa_global, "detalle": detalle_global, "resultados": resultados}


def ajustar_stock_lote(items_lote, commit=False):
    """Ajusta N productos en HybridLite, troceando en documentos de a lo sumo
    MAX_FILAS_LOTE ítems (la grilla de Ajustes solo muestra ~15 filas sin
    scroll, que no se maneja). Con len(items_lote) <= MAX_FILAS_LOTE el
    comportamiento es IDÉNTICO a un único documento (mismo caso validado en vivo).

    items_lote: list[dict] con claves:
        "item_id" (int)  — id de ordenes_cambio_items (para el mapa de resultados)
        "codigo"  (str)  — código del producto
        "delta"   (float)— cambio RELATIVO de stock (target = existencia_DB + delta)

    Return: {
        "ok":     bool,   # True solo si TODOS los items de TODOS los documentos quedaron ok
        "etapa":  str,    # "commit" | "preview" si todos ok; si no, la etapa del PRIMER
                          # item fallido ("abrir_hybrid" | "carga/conteo" | "totalizar"
                          # | "verificacion_db")
        "detalle": str,   # resumen humano del lote completo (todos los documentos)
        "resultados": dict[int, dict],  # item_id -> {"ok": bool, "etapa": str, "detalle": str}
    }

    Política de fallo entre documentos: si un documento falla en cualquier etapa,
    los documentos restantes NO se intentan (sus items quedan como "no intentado,
    reintentable"). Los documentos ya commiteados ANTES del fallo quedan aplicados
    (no se deshacen) — un reintento posterior solo reprocesará los items pendientes,
    sin duplicar lo ya aplicado.
    """
    if not items_lote:
        return {"ok": False, "etapa": "carga/conteo", "detalle": "Lote vacío.", "resultados": {}}

    # 1) duplicados de código -> abortar SIN tocar la UI (sobre el LOTE COMPLETO)
    # (dedupe por el código REAL -- codigo_esperado si viene -- no por la búsqueda,
    # para no confundir dos alias legítimos que apuntan a productos distintos)
    codigos_norm = [(it.get("codigo_esperado") or it["codigo"]).strip().lower()
                    for it in items_lote]
    vistos, dups = set(), set()
    for c in codigos_norm:
        (dups if c in vistos else vistos).add(c)
    if dups:
        detalle = f"Códigos duplicados en el lote: {sorted(dups)}. Nada se tocó."
        log.error(detalle)
        return _lote_fallo_uniforme(items_lote, "carga/conteo", detalle)

    # 2) asegurar que Hybrid esté abierto y logueado (lo lanza si está cerrado) — UNA vez
    import abrir_hybrid
    ok, msg = abrir_hybrid.asegurar_hybrid()
    if not ok:
        return _lote_fallo_uniforme(items_lote, "abrir_hybrid", msg)

    # 3) leer existencia DB de TODOS los códigos ANTES de empezar (targets absolutos) — UNA vez.
    #    Los targets quedan fijos antes de tocar cualquier documento: como los duplicados ya
    #    están vetados, ningún chunk commiteado puede alterar el target de otro.
    existencias_antes = {}
    for it in items_lote:
        codigo = it.get("codigo_esperado") or it["codigo"]
        try:
            total_antes, _ = dbex.existencia(codigo)
        except Exception:
            total_antes = None
        if total_antes is None:
            detalle = f"No se pudo leer la existencia en DB de {codigo}. Nada se tocó."
            log.error(detalle)
            return _lote_fallo_uniforme(items_lote, "carga/conteo", detalle)
        existencias_antes[it["item_id"]] = total_antes

    targets = {it["item_id"]: existencias_antes[it["item_id"]] + float(it["delta"])
               for it in items_lote}
    for it in items_lote:
        log.info("Lote: item_id=%s codigo=%s existencia_db=%s delta=%s target=%s",
                 it["item_id"], it["codigo"], existencias_antes[it["item_id"]],
                 it["delta"], targets[it["item_id"]])

    # 4) trocear en chunks de MAX_FILAS_LOTE, preservando el orden, y procesar
    #    los documentos EN SECUENCIA.
    chunks = [items_lote[i:i + MAX_FILAS_LOTE]
              for i in range(0, len(items_lote), MAX_FILAS_LOTE)]
    total_chunks = len(chunks)

    resultados = {}
    detalles_doc = []
    detenido = False
    motivo_detencion = None
    primera_etapa_fallo = None
    primer_res_doc = None
    for i, chunk in enumerate(chunks, start=1):
        if detenido:
            for it in chunk:
                resultados[it["item_id"]] = {
                    "ok": False, "etapa": "carga/conteo",
                    "detalle": f"lote detenido: fallo en un documento anterior "
                               f"({motivo_detencion}); este item no se intentó (reintentable)."}
            continue

        log.info("Lote: documento %s/%s con %s item(s)", i, total_chunks, len(chunk))
        res_doc = _lote_un_documento(chunk, targets, existencias_antes, commit)
        if primer_res_doc is None:
            primer_res_doc = res_doc
        resultados.update(res_doc["resultados"])
        detalles_doc.append(f"documento {i}/{total_chunks} ({res_doc['etapa']}): {res_doc['detalle']}")

        if not res_doc["ok"]:
            detenido = True
            motivo_detencion = res_doc["detalle"]
            if primera_etapa_fallo is None:
                primera_etapa_fallo = res_doc["etapa"]

    # caso corto (un solo documento): comportamiento IDÉNTICO al flujo previo a trocear
    # (mismos "etapa"/"detalle", validados en vivo) — el agregado del punto 5 solo aplica
    # cuando el lote realmente se dividió en más de un documento.
    if total_chunks == 1:
        return {"ok": primer_res_doc["ok"], "etapa": primer_res_doc["etapa"],
                "detalle": primer_res_doc["detalle"], "resultados": resultados}

    # 5) agregado global (lote troceado en 2+ documentos)
    todos_ok = all(r["ok"] for r in resultados.values())
    n_ok = sum(1 for r in resultados.values() if r["ok"])
    n_no_intentados = sum(1 for r in resultados.values() if "no se intentó" in r.get("detalle", ""))
    n_fallidos = len(items_lote) - n_ok - n_no_intentados

    if todos_ok:
        etapa_global = "commit" if commit else "preview"
    else:
        etapa_global = primera_etapa_fallo

    resumen = f"Lote de {len(items_lote)} ítem(s) en {total_chunks} documento(s): {n_ok} ok"
    if n_fallidos > 0:
        resumen += f", {n_fallidos} fallido(s)"
    if n_no_intentados > 0:
        resumen += f", {n_no_intentados} no intentado(s)"
    resumen += ". " + " | ".join(detalles_doc)

    return {"ok": todos_ok, "etapa": etapa_global, "detalle": resumen, "resultados": resultados}


if __name__ == "__main__":
    if "--lote" in sys.argv:
        idx = sys.argv.index("--lote")
        try:
            spec = sys.argv[idx + 1]
        except IndexError:
            print("Uso: python flujo_stock_real.py --lote \"COD1:delta1[:alias1],COD2:delta2\" [--commit]")
            sys.exit(1)
        items_lote = []
        for n, par in enumerate(spec.split(","), start=1):
            partes = par.split(":")
            if len(partes) not in (2, 3):
                print(f"Par inválido en --lote: {par!r} (formato codigo:delta[:alias])")
                sys.exit(1)
            codigo = partes[0].strip()
            delta = partes[1].strip()
            alias = partes[2].strip() if len(partes) == 3 else None
            if not codigo or not delta:
                print(f"Par inválido en --lote: {par!r} (formato codigo:delta[:alias])")
                sys.exit(1)
            try:
                delta_val = float(delta)
            except ValueError:
                print(f"Delta inválido en --lote: {par!r}")
                sys.exit(1)
            # alias: lo que se TECLEA para encontrar el producto (p.ej. su código de
            # barras) cuando el propio código interno colisiona con el de OTRO
            # producto (ver hybrid-colision-codigo-barras); codigo sigue siendo el
            # código interno REAL, usado para verificar/leer la DB.
            item = {"item_id": n, "codigo": alias or codigo, "delta": delta_val}
            if alias:
                item["codigo_esperado"] = codigo
            items_lote.append(item)
        try:
            res = ajustar_stock_lote(items_lote, commit="--commit" in sys.argv)
            print("\n=== RESULTADO LOTE ===")
            for k, v in res.items():
                if k == "resultados":
                    print("  resultados:")
                    for item_id, r in v.items():
                        print(f"    item_id={item_id}: {r}")
                else:
                    print(f"  {k}: {v}")
        finally:
            _cerrar_aislada_cli()
        sys.exit(0)

    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    if len(args) < 2:
        print("Uso: python flujo_stock_real.py <codigo> <cantidad> [--commit] [--delta]")
        print("     python flujo_stock_real.py --lote \"COD1:delta1,COD2:delta2\" [--commit]")
        sys.exit(1)
    try:
        res = ajustar_stock(args[0], args[1],
                            commit="--commit" in sys.argv, delta="--delta" in sys.argv)
        print("\n=== RESULTADO ===")
        for k, v in res.items():
            print(f"  {k}: {v}")
    finally:
        _cerrar_aislada_cli()
