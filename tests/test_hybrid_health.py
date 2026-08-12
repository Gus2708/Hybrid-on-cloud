"""Tests de hybrid_health: detección de HybridLite colgado y kill de recuperación.

La primitiva `responde()` (SendMessageTimeout/IsHungAppWindow) se valida contra
Windows real, no acá; estos tests cubren la LÓGICA DE DECISIÓN, que es la que
puede matar la sesión de un empleado si se equivoca: qué cuenta como síntoma,
que la gracia descarte un freeze pasajero, y que el kill se dispare solo con el
cuelgue confirmado.
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "hybrid_writeback")))

hh = pytest.importorskip("hybrid_health", reason="requiere pywin32 (solo Windows)")


@pytest.fixture
def sin_esperas(monkeypatch):
    """Gracia y pausas mínimas para que los tests no duerman de verdad."""
    monkeypatch.setattr(hh, "PAUSA_RECHEQUEO", 0.001)
    monkeypatch.setattr(hh, "ESPERA_TRAS_MATAR", 0)


def _fingir(monkeypatch, pids, ventanas, responden=True, edad=3600):
    """Simula el estado de Windows: `pids` vivos, `ventanas` = [(hwnd, pid, cls)],
    todos los procesos con `edad` segundos de vida."""
    monkeypatch.setattr(hh, "pids_hybrid", lambda: set(pids))
    monkeypatch.setattr(hh, "ventanas_visibles", lambda _pids: list(ventanas))
    monkeypatch.setattr(hh, "responde", lambda hwnd, timeout_ms=None: responden)
    monkeypatch.setattr(hh, "edad_proceso", lambda _pid: edad)


# ─── _sintoma: qué cuenta como Hybrid enfermo ───────────────────────────────
def test_sintoma_none_si_todas_las_ventanas_responden(monkeypatch):
    _fingir(monkeypatch, {10, 20}, [(1, 10, "TF_MainHybridCashMG"), (2, 20, "TApplication")])
    assert hh._sintoma({10, 20}) is None


def test_sintoma_detecta_ventana_que_no_responde(monkeypatch):
    _fingir(monkeypatch, {10}, [(1, 10, "TF_MainHybridCashMG")], responden=False)
    sintoma = hh._sintoma({10})
    assert "sin responder" in sintoma
    assert "TF_MainHybridCashMG (PID 10)" in sintoma


def test_sintoma_detecta_proceso_fantasma_sin_ventana(monkeypatch):
    """Un PID vivo sin ventana visible es el caso clásico que traba el arranque,
    aunque OTRA instancia esté sana y responda."""
    _fingir(monkeypatch, {10, 99}, [(1, 10, "TF_MainHybridCashMG")])
    sintoma = hh._sintoma({10, 99})
    assert "[99]" in sintoma
    assert "fantasma" in sintoma


def test_sintoma_perdona_al_proceso_que_recien_arranca(monkeypatch):
    """Hybrid arrancando (o el de un empleado abriéndose) todavía no dibujó su
    ventana: no es fantasma, matarlo sería matarle el arranque."""
    _fingir(monkeypatch, {10, 99}, [(1, 10, "TF_MainHybridCashMG")],
            edad=hh.EDAD_MIN_FANTASMA - 1)
    assert hh._sintoma({10, 99}) is None


def test_sintoma_no_mata_si_no_puede_leer_la_edad(monkeypatch):
    """Sin edad legible se asume recién nacido (fail-safe: no se mata)."""
    _fingir(monkeypatch, {10, 99}, [(1, 10, "TF_MainHybridCashMG")], edad=None)
    assert hh._sintoma({10, 99}) is None


def test_sintoma_none_sin_procesos(monkeypatch):
    _fingir(monkeypatch, set(), [])
    assert hh._sintoma(set()) is None


# ─── diagnosticar: la gracia evita matar por un freeze pasajero ─────────────
def test_diagnosticar_none_si_hybrid_no_esta_corriendo(monkeypatch, sin_esperas):
    monkeypatch.setattr(hh, "pids_hybrid", lambda: set())
    assert hh.diagnosticar(gracia=0.05) is None


def test_diagnosticar_descarta_freeze_pasajero(monkeypatch, sin_esperas):
    """Colgado en el primer chequeo, sano en el segundo -> NO es cuelgue."""
    monkeypatch.setattr(hh, "pids_hybrid", lambda: {10})
    sintomas = iter(["ventana sin responder", None, None])
    monkeypatch.setattr(hh, "_sintoma", lambda _pids: next(sintomas))
    assert hh.diagnosticar(gracia=5) is None


def test_diagnosticar_confirma_cuelgue_sostenido(monkeypatch, sin_esperas):
    monkeypatch.setattr(hh, "pids_hybrid", lambda: {10})
    monkeypatch.setattr(hh, "_sintoma", lambda _pids: "ventana sin responder")
    confirmado = hh.diagnosticar(gracia=0.05)
    assert "ventana sin responder" in confirmado
    assert "sostenido" in confirmado


def test_diagnosticar_none_si_los_procesos_mueren_solos(monkeypatch, sin_esperas):
    """Si Hybrid se cierra durante la gracia no queda nada que matar."""
    pids = iter([{10}, set(), set()])
    monkeypatch.setattr(hh, "pids_hybrid", lambda: next(pids))
    monkeypatch.setattr(hh, "_sintoma", lambda _pids: "ventana sin responder")
    assert hh.diagnosticar(gracia=5) is None


# ─── recuperar_si_colgado: el kill solo con cuelgue confirmado ──────────────
def test_recuperar_no_mata_si_esta_sano(monkeypatch, sin_esperas):
    monkeypatch.setattr(hh, "diagnosticar", lambda gracia=None, logger=None: None)
    monkeypatch.setattr(hh, "matar_todo", lambda **_: pytest.fail("no debía matar nada"))
    assert hh.recuperar_si_colgado() == ("sano", None)


def test_recuperar_mata_todo_con_cuelgue_confirmado(monkeypatch, sin_esperas):
    monkeypatch.setattr(hh, "diagnosticar", lambda gracia=None, logger=None: "colgado")
    llamadas = []
    monkeypatch.setattr(hh, "matar_todo", lambda **_: (llamadas.append(1), (True, "matadas 2."))[1])
    accion, detalle = hh.recuperar_si_colgado()
    assert (accion, len(llamadas)) == ("recuperado", 1)
    assert "colgado" in detalle


def test_recuperar_falla_si_el_kill_esta_deshabilitado(monkeypatch, sin_esperas):
    monkeypatch.setattr(hh, "MATAR_HABILITADO", False)
    monkeypatch.setattr(hh, "diagnosticar", lambda gracia=None, logger=None: "colgado")
    monkeypatch.setattr(hh, "matar_todo", lambda **_: pytest.fail("HYBRID_HANG_KILL=0 no debe matar"))
    accion, detalle = hh.recuperar_si_colgado()
    assert accion == "fallo"
    assert "HYBRID_HANG_KILL=0" in detalle


def test_recuperar_falla_si_quedan_procesos_vivos(monkeypatch, sin_esperas):
    monkeypatch.setattr(hh, "diagnosticar", lambda gracia=None, logger=None: "colgado")
    monkeypatch.setattr(hh, "matar_todo", lambda **_: (False, "quedaron procesos vivos: [7]."))
    accion, detalle = hh.recuperar_si_colgado()
    assert accion == "fallo"
    assert "[7]" in detalle


# ─── matar_todo / matar_huerfanos ───────────────────────────────────────────
def test_matar_todo_sin_procesos_no_llama_taskkill(monkeypatch, sin_esperas):
    monkeypatch.setattr(hh, "pids_hybrid", lambda: set())
    monkeypatch.setattr(hh.subprocess, "run", lambda *a, **k: pytest.fail("nada que matar"))
    ok, detalle = hh.matar_todo()
    assert ok
    assert "no había procesos" in detalle


def test_matar_todo_reporta_fallo_si_sobreviven(monkeypatch, sin_esperas):
    monkeypatch.setattr(hh, "TIMEOUT_MUERTE", 0)
    monkeypatch.setattr(hh, "pids_hybrid", lambda: {10})
    monkeypatch.setattr(hh.subprocess, "run", lambda *a, **k: None)
    monkeypatch.setattr(hh.time, "sleep", lambda _s: None)
    ok, detalle = hh.matar_todo()
    assert not ok
    assert "[10]" in detalle


def test_matar_huerfanos_solo_toca_pids_nuevos_sin_ventana(monkeypatch):
    """El PID del empleado (preexistente) y el que sí abrió ventana no se tocan."""
    monkeypatch.setattr(hh, "pids_hybrid", lambda: {10, 20, 30})
    monkeypatch.setattr(hh, "ventanas_visibles", lambda _pids: [(1, 20, "TFUserPassMainForm")])
    matados = []
    monkeypatch.setattr(hh.subprocess, "run",
                        lambda cmd, **k: matados.append(cmd[-1]))
    assert hh.matar_huerfanos({10}) == 1
    assert matados == ["30"]
