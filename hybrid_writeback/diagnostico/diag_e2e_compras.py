import sys, os, time
from dataclasses import dataclass
from typing import List, Dict, Any, Optional

BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
HW_DIR = os.path.join(BASE_DIR, 'hybrid_writeback')
if HW_DIR not in sys.path: sys.path.insert(0, HW_DIR)
if BASE_DIR not in sys.path: sys.path.insert(0, BASE_DIR)

import listener_base as lb
import listener_compras as lc
import flujo_compra_real as fcr
import colisiones

@dataclass
class PhaseRecord:
    name: str
    duration_ms: float
    status: str
    details: str = ''

class FlowTracker:
    def __init__(self, name: str):
        self.name = name
        self.records: List[PhaseRecord] = []
        self.start_time = time.perf_counter()

    def track(self, phase_name: str):
        class PhaseContext:
            def __init__(self, tracker, pname):
                self.tracker = tracker
                self.pname = pname
                self.details = ''
                self.status = 'OK'
            def __enter__(self):
                self.t0 = time.perf_counter()
                return self
            def __exit__(self, exc_type, exc_val, exc_tb):
                dt = (time.perf_counter() - self.t0) * 1000.0
                if exc_type:
                    self.status = 'ERROR'
                    self.details = str(exc_val)
                self.tracker.records.append(
                    PhaseRecord(name=self.pname, duration_ms=dt, status=self.status, details=self.details)
                )
                return False
            def set_details(self, msg: str):
                self.details = msg
        return PhaseContext(self, phase_name)

    def print_report(self):
        total_ms = (time.perf_counter() - self.start_time) * 1000.0
        print('\n' + '=' * 80)
        print(f' REPORTE DE AUDITORIA Y TRACKER E2E COMPRAS: {self.name.upper()}')
        print('=' * 80)
        header_line = "{:<42} | {:>14} | {:<8} | {}".format("ETAPA", "TIEMPO", "ESTADO", "DETALLES")
        print(header_line)
        print('-' * 80)
        for r in self.records:
            t_str = f"{r.duration_ms:>10.2f} ms"
            line = f"{r.name:<42} | {t_str} | {r.status:<8} | {r.details}"
            print(line)
        print('-' * 80)
        tot_line = "{:<42} | {:>10.2f} ms ({:.3f}s)".format("TIEMPO TOTAL DEL PIPELINE", total_ms, total_ms / 1000.0)
        print(tot_line)
        print('=' * 80 + '\n')

def ejecutar_tracker_compra_68(commit=False):
    tracker = FlowTracker(f'Compra 68 (commit={commit})')

    # 1. Fetch Supabase
    compra = None
    items = []
    with tracker.track('1. Listener: Consulta Supabase') as p:
        compras = lb.rest('GET', 'compras_app?id=eq.68')
        if not compras:
            raise ValueError('No se encontro compra 68')
        compra = compras[0]
        items = lc.get_items(68)
        prov = compra.get('proveedor_codigo')
        p.set_details(f"Proveedor {prov} con {len(items)} items")

    # 2. Pre-vuelo Altas
    with tracker.track('2. Pre-vuelo: Chequeo Altas') as p:
        nuevos = [it for it in items if it.get('es_nuevo')]
        p.set_details(f"{len(nuevos)} items marcados es_nuevo (ej: T-SCCA2X14AWG-RB ya existe en maestro)")

    # 3. Pre-vuelo Colisiones
    claves_busqueda = {}
    with tracker.track('3. Pre-vuelo: Revision Colisiones') as p:
        cods = [it['codigo'] for it in items]
        claves_busqueda, problemas = colisiones.revisar_lote(cods)
        if problemas:
            raise ValueError(f'Colisiones no resueltas: {problemas}')
        p.set_details(f"{len(claves_busqueda)} claves seguras")

    # 4. Ejecución del Flujo de Compra
    res = None
    with tracker.track(f'4. Flujo Compra Real (commit={commit})') as p:
        prov_cod = compra.get('proveedor_codigo')
        prov_nom = compra.get('proveedor_nombre')
        doc_num = str(compra.get('numero_documento') or compra['id'])
        res = fcr.registrar_compra(prov_cod, items, doc_num, commit=commit, proveedor_nombre=prov_nom)
        etapa_str = res.get('etapa')
        ok_str = res.get('ok')
        p.set_details(f"Resultado: {etapa_str} - ok={ok_str}")

    tracker.print_report()
    return tracker, res

if __name__ == '__main__':
    commit_mode = '--commit' in sys.argv
    ejecutar_tracker_compra_68(commit=commit_mode)
