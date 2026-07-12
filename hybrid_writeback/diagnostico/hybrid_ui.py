"""
hybrid_ui.py — Escritor hacia HybridLite vía automatización de interfaz (pywinauto).

POR QUÉ ASÍ:
  HybridLite usa DBISAM (motor cliente/servidor en PRINCIPAL:12005). La ÚNICA forma
  segura de escribir sin corromper índices/checksums/kardex es que lo haga el propio
  motor. Sin el driver ODBC, el motor solo es operable a través de la propia app.
  Por eso aquí manejamos la app real: ella hace el UPDATE/ajuste correctamente.

SEGURIDAD:
  * DRY_RUN=True por defecto: registra lo que HARÍA, sin tocar la app.
  * Si los pasos de UI no están calibrados, lanza NotCalibratedError (no hace clics
    a ciegas).
  * Pensado para cambios de bajo volumen (un precio, un ajuste), no cargas masivas.

CALIBRACIÓN (pendiente, requiere la app abierta):
  1. Abre HybridLitePro e inicia sesión.
  2. Ejecuta:  python inspect_hybrid.py --tree --snapshot
  3. Con ese volcado se rellenan las secciones marcadas  # >>> CALIBRAR <<<
  4. Probar con DRY_RUN=True, luego con UN producto de prueba, luego habilitar.
"""
import os
import time
import logging

logger = logging.getLogger("hybrid_ui")

# ─── Configuración ────────────────────────────────────────────────────────────
# Por defecto NO escribe. Cambia a "0" en el entorno solo cuando esté calibrado.
DRY_RUN = os.environ.get("HYBRID_WRITE_ENABLED", "0") != "1"

# Cliente local en esta estación (se conecta al servidor DBISAM de PRINCIPAL).
APP_EXE = os.environ.get("HYBRID_APP_EXE", r"C:\HybridLiteEstacion\HybridLiteOS.exe")
WINDOW_TITLE_HINTS = ("hybrid liteos", "modulo principal", "hybrid", "inventario")
MAIN_FORM_CLASS = "TF_MainHybridCashMG"  # ventana principal tras login

HYBRID_USER = os.environ.get("HYBRID_UI_USER", "")
HYBRID_PASS = os.environ.get("HYBRID_UI_PASS", "")

# Tiempos de espera (segundos)
T_CONNECT = 10
T_DIALOG = 8

_BACKEND = os.environ.get("HYBRID_UI_BACKEND", "win32")  # 'win32' (VCL) o 'uia'


class HybridUIError(Exception):
    """Error genérico operando la UI de HybridLite."""


class NotCalibratedError(HybridUIError):
    """Los pasos de UI todavía no se han calibrado contra la app real."""


# ─── Conexión a la app ────────────────────────────────────────────────────────
def connect_app(launch_if_needed=False):
    """
    Conecta a una instancia abierta de HybridLite. Devuelve el objeto Application.
    Lanza HybridUIError si no la encuentra (y launch_if_needed=False).
    """
    from pywinauto import Application, Desktop

    # 1. Buscar ventana ya abierta
    for w in Desktop(backend=_BACKEND).windows():
        try:
            title = (w.window_text() or "").lower()
        except Exception:
            continue
        if any(h in title for h in WINDOW_TITLE_HINTS):
            pid = w.process_id()
            logger.info("HybridLite encontrado (pid=%s, ventana=%r)", pid, w.window_text())
            return Application(backend=_BACKEND).connect(process=pid, timeout=T_CONNECT)

    # 2. Lanzar si se permite
    if launch_if_needed:
        if not os.path.exists(APP_EXE):
            raise HybridUIError(f"No existe el ejecutable: {APP_EXE}")
        logger.info("Lanzando HybridLite: %s", APP_EXE)
        app = Application(backend=_BACKEND).start(APP_EXE, timeout=T_CONNECT)
        time.sleep(3)
        return app

    raise HybridUIError(
        "No encontré HybridLite abierto. Ábrelo e inicia sesión, "
        "o usa launch_if_needed=True (requiere login automatizado calibrado)."
    )


def _main_window(app):
    """Devuelve la ventana principal de la app conectada."""
    win = app.top_window()
    win.wait("exists ready", timeout=T_CONNECT)
    return win


# ─── Operación: cambiar PRECIO ────────────────────────────────────────────────
def set_price(codigo_producto: str, nuevo_precio: float) -> dict:
    """
    Cambia el PVP de un producto en HybridLite.
    Devuelve {'ok': bool, 'detalle': str, 'valor_anterior': float|None}.
    """
    logger.info("set_price(codigo=%s, nuevo=%s) DRY_RUN=%s",
                codigo_producto, nuevo_precio, DRY_RUN)

    if DRY_RUN:
        return {"ok": True, "detalle": f"[DRY_RUN] cambiaría precio de {codigo_producto} "
                                       f"a {nuevo_precio}", "valor_anterior": None}

    app = connect_app()
    win = _main_window(app)

    # ========================================================================
    # >>> CALIBRAR <<<  (rellenar con el volcado de inspect_hybrid.py)
    #   Flujo típico a programar:
    #     1. Abrir módulo de Inventario / Productos.
    #     2. Buscar por código `codigo_producto`.
    #     3. Entrar a edición de precios (TPC_PVPCONIMPUESTO1).
    #     4. Leer valor anterior (para snapshot/reversión).
    #     5. Escribir `nuevo_precio`, confirmar/Guardar.
    #     6. Verificar mensaje de éxito.
    # Ejemplo de cómo se verán los pasos (placeholders):
    #     win.menu_select("Inventario->Productos")
    #     dlg = app.window(title_re=".*Productos.*"); dlg.wait("ready", T_DIALOG)
    #     dlg.Edit_Busqueda.set_text(codigo_producto)
    #     dlg.Boton_Buscar.click()
    #     anterior = dlg.Edit_Precio.window_text()
    #     dlg.Edit_Precio.set_text(str(nuevo_precio))
    #     dlg.Boton_Guardar.click()
    # ========================================================================
    raise NotCalibratedError(
        "set_price todavía no está calibrado. Abre la app y ejecuta "
        "'python inspect_hybrid.py --tree --snapshot' para mapear las pantallas."
    )


# ─── Operación: ajustar STOCK (como ajuste de inventario, NO sobrescritura) ────
def adjust_stock(codigo_producto: str, delta: float, motivo: str) -> dict:
    """
    Registra un AJUSTE de inventario (+/- delta) para un producto.
    Importante: se hace como documento de ajuste (respeta el kardex/auditoría),
    NUNCA sobrescribiendo el saldo EIN_EXISTENCIA directamente.
    """
    logger.info("adjust_stock(codigo=%s, delta=%s, motivo=%r) DRY_RUN=%s",
                codigo_producto, delta, motivo, DRY_RUN)

    if not motivo or not motivo.strip():
        return {"ok": False, "detalle": "Un ajuste de stock requiere 'motivo' (auditoría).",
                "valor_anterior": None}

    if DRY_RUN:
        return {"ok": True, "detalle": f"[DRY_RUN] registraría ajuste {delta:+g} en "
                                       f"{codigo_producto} ({motivo})", "valor_anterior": None}

    app = connect_app()
    win = _main_window(app)

    # ========================================================================
    # >>> CALIBRAR <<<
    #   Flujo típico:
    #     1. Abrir módulo de Inventario -> Ajuste de inventario.
    #     2. Nuevo documento de ajuste.
    #     3. Agregar línea: producto `codigo_producto`, cantidad `delta`.
    #     4. Escribir `motivo` en observaciones.
    #     5. Guardar/Procesar el ajuste.
    # ========================================================================
    raise NotCalibratedError(
        "adjust_stock todavía no está calibrado. Necesito ver la pantalla de "
        "'Ajuste de inventario' con inspect_hybrid.py."
    )


# ─── Prueba manual ────────────────────────────────────────────────────────────
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    print(f"DRY_RUN = {DRY_RUN}  (export HYBRID_WRITE_ENABLED=1 para escribir de verdad)")
    print("Prueba precio:", set_price("DEMO123", 9.99))
    print("Prueba stock :", adjust_stock("DEMO123", -2, "prueba"))
