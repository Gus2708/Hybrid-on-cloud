import sys, os, time
from dataclasses import dataclass
from typing import List, Dict, Any

BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
HW_DIR = os.path.join(BASE_DIR, 'hybrid_writeback')
if HW_DIR not in sys.path: sys.path.insert(0, HW_DIR)
if BASE_DIR not in sys.path: sys.path.insert(0, BASE_DIR)

import alias_manager as am
import colisiones
import flujo_pedido_real as fpr

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
        print(f' REPORTE DE AUDITORIA Y TRACKER E2E: {self.name.upper()}')
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

def correr_audit_e2e():
    tracker = FlowTracker('Pipeline Completo Pedidos')
    items_raw = [
        {'codigo': '01404', 'cantidad': 2.0, 'precio': None},
        {'codigo': 'THINNER-01', 'cantidad': 1.0, 'precio': 3.50},
    ]

    items_resueltos = []
    with tracker.track('1. Listener: Parseo & Alias') as p:
        for it in items_raw:
            c_orig = str(it['codigo']).strip()
            c_res = am.resolver_alias(c_orig)
            it_c = dict(it)
            it_c['codigo'] = c_res
            items_resueltos.append(it_c)
        nuevo_cod = items_resueltos[1]['codigo']
        p.set_details(f"{len(items_raw)} items procesados (THINNER-01 -> {nuevo_cod})")

    with tracker.track('2. Pre-vuelo: Validacion Duplicados') as p:
        cods = [str(x['codigo']).strip().lower() for x in items_resueltos]
        dups = {c for c in cods if cods.count(c) > 1}
        if dups: raise ValueError(f'Duplicados: {dups}')
        p.set_details('0 duplicados detectados')

    with tracker.track('3. Pre-vuelo: Revision Colisiones') as p:
        cods_check = [it['codigo'] for it in items_resueltos]
        claves, probs = colisiones.revisar_lote(cods_check)
        if probs: raise ValueError(f'Problemas: {probs}')
        p.set_details(f'{len(claves)} claves seguras asignadas')

    header, detalle = None, []
    with tracker.track('4. DBISAM : Lectura Ultimo Pedido') as p:
        header, detalle = fpr._ultimo_pedido_db()
        doc = header.get('THT_DOCUMENTO') if header else 'N/A'
        p.set_details(f'Doc: {doc} ({len(detalle)} lineas)')

    with tracker.track('5. DBISAM : Evaluacion de Reglas') as p:
        if header and detalle:
            mock = [{'codigo': str(detalle[0].get('TBT_CODIGO')).strip(), 'cantidad': float(detalle[0].get('TBT_CANTIDAD') or 0)}]
            ok, msg, _ = fpr._evaluar_pedido_db(header, detalle, header.get('THT_RIFCLIENTE'), mock)
            p.set_details(f'Verificado: ok={ok} ({msg[:40]}...)')

    tracker.print_report()
    return tracker

if __name__ == '__main__':
    correr_audit_e2e()
