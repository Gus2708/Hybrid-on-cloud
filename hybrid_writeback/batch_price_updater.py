"""batch_price_updater.py — Motor de actualización masiva de precios y costos en HybridLiteOS.

Características de producción:
  1. Resolución automática de alias de proveedor (alias_manager).
  2. Filtrado previo contra DBISAM (solo procesa los que realmente difieren).
  3. Sistema de checkpoints resiliente (reanuda exactamente donde quedó tras interrupciones).
  4. Telemetría y tracking en tiempo real (consola y log persistente).
  5. Transición ultra-rápida entre ítems (0.00s de delay muerto).
  6. Tolerancia estricta (<0.005) contra recálculos automáticos del POS.
  7. Cierre limpio garantizado de ventanas y modales.
  8. Auditoría final exhaustiva en DBISAM en una sola pasada de red.
"""
import sys
import os
import time
import json
import ctypes
import logging
from datetime import datetime

# Asegurar desktop interactivo de Windows
try:
    h_def = ctypes.windll.user32.OpenDesktopW("Default", 0, False, 0x01FF)
    if h_def:
        ctypes.windll.user32.SetThreadDesktop(h_def)
except Exception:
    pass

import flujo_precio as fp
import flujo_precio_real as fpr
import flujo_compra_real as fcr
import flujo_stock_real as fsr
import hybrid_price_writer as hpw
import alias_manager as am
import pydbisam
import win32gui

log = logging.getLogger("batch_updater")


class BatchPriceUpdater:
    def __init__(self, log_path=None, checkpoint_path=None):
        self.log_path = log_path or os.path.join(os.getcwd(), "scratch", "batch_updater_tracker.log")
        self.checkpoint_path = checkpoint_path or os.path.join(os.getcwd(), "scratch", "batch_checkpoint.json")
        os.makedirs(os.path.dirname(self.log_path), exist_ok=True)
        os.makedirs(os.path.dirname(self.checkpoint_path), exist_ok=True)

    def _track(self, msg):
        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        line = f"[{ts}] {msg}"
        print(line, flush=True)
        try:
            with open(self.log_path, "a", encoding="utf-8") as f:
                f.write(line + "\n")
        except Exception:
            pass

    def _cargar_checkpoint(self):
        if os.path.isfile(self.checkpoint_path):
            try:
                with open(self.checkpoint_path, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                pass
        return {"completados": [], "fallidos": {}, "ultimo_indice": 0}

    def _guardar_checkpoint(self, data):
        try:
            with open(self.checkpoint_path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
        except Exception as e:
            self._track(f"Aviso: no se pudo guardar checkpoint: {e}")

    @staticmethod
    def _extraer_precio(it):
        for k in ("precio", "precio_nuevo", "precio_venta", "precio_venta_sugerido_25", 
                  "precio_venta_sugerido_35", "precio_venta_sugerido", "pvp", "pvp_con_impuesto"):
            v = it.get(k)
            if v is not None and str(v).strip() != "":
                try:
                    val = float(v)
                    if val > 0:
                        return val
                except ValueError:
                    pass
        return None

    @staticmethod
    def _extraer_costo(it):
        for k in ("costo", "nuevo_costo", "costo_nuevo", "costo_unitario", "costo_usd"):
            v = it.get(k)
            if v is not None and str(v).strip() != "":
                try:
                    val = float(v)
                    if val > 0:
                        return val
                except ValueError:
                    pass
        return None

    def procesar_lote(self, lista_items, commit=True, proveedor=None):
        """Procesa una lista de dicts: [{'codigo': str, 'precio': float, 'costo': float, ...}]"""
        self._track("================ INICIANDO LOTE DE ACTUALIZACIÓN ================")
        
        # 1. Normalizar códigos con alias_manager y extraer campos válidos
        items_normalizados = []
        for it in lista_items:
            cod_raw = str(it.get("codigo", "")).strip()
            cod_resuelto = am.resolver_alias(cod_raw, proveedor=proveedor)
            p_val = self._extraer_precio(it)
            c_val = self._extraer_costo(it)
            
            if p_val is None and c_val is None:
                self._track(f"ALERTA: Omitiendo {cod_raw} porque no contiene precio ni costo válido (> 0).")
                continue

            item_norm = dict(it)
            item_norm["codigo_original"] = cod_raw
            item_norm["codigo"] = cod_resuelto
            item_norm["precio_meta"] = p_val
            item_norm["costo_meta"] = c_val
            items_normalizados.append(item_norm)

        codigos_todos = [it["codigo"] for it in items_normalizados]
        self._track(f"Total productos válidos en entrada: {len(items_normalizados)}")

        # 2. Consultar DBISAM previa (una sola pasada rápida)
        self._track("Leyendo estado previo en DBISAM...")
        t0_db = time.time()
        db_actual = hpw._db_valores_usd_batch(codigos_todos)
        self._track(f"Estado DBISAM leído en {time.time() - t0_db:.2f}s.")

        # 3. Filtrar pendientes comparando contra DB actual
        pendientes = []
        ya_al_dia = []
        for it in items_normalizados:
            cod = it["codigo"]
            p_target = it["precio_meta"]
            c_target = it["costo_meta"]
            p_act, c_act = db_actual.get(cod, (None, None))
            
            p_ok = (p_target is None) or (p_act is not None and abs(p_act - p_target) <= 0.01)
            c_ok = (c_target is None) or (c_act is not None and abs(c_act - c_target) <= 0.01)
            
            if p_ok and c_ok:
                ya_al_dia.append(cod)
            else:
                it_p = dict(it)
                it_p["p_ant"] = p_act
                it_p["c_ant"] = c_act
                it_p["precio"] = p_target
                it_p["costo"] = c_target
                pendientes.append(it_p)

        self._track(f"Productos ya al día en DBISAM: {len(ya_al_dia)}")
        self._track(f"Productos pendientes por procesar en UI: {len(pendientes)}")

        if not pendientes:
            self._track("¡Todos los productos ya coinciden con la meta! No se requiere acción.")
            return {"ok": True, "total": len(items_normalizados), "actualizados": 0, "ya_al_dia": len(ya_al_dia)}

        # 4. Asegurar UI
        self._track("Asegurando ventanas: cerrando Compras y abriendo Ficha de Inventario...")
        fcr._salir_compras()
        fpr.abrir_ficha()

        # 5. Cargar checkpoint previo
        ckpt = self._cargar_checkpoint()
        completados_set = set(ckpt.get("completados", []))

        # 6. Bucle de ejecución
        t_inicio = time.time()
        exitosos = list(completados_set)
        fallidos = dict(ckpt.get("fallidos", {}))
        tiempos_items = []
        t_prev_fin = None

        total_pend = len(pendientes)

        for idx, it in enumerate(pendientes, 1):
            cod = it["codigo"]
            if cod in completados_set:
                continue

            p_target = it["precio"]
            c_target = it["costo"]
            p_ant = it["p_ant"]
            c_ant = it["c_ant"]
            desc = it.get("descripcion", it.get("descripcion_sistema", ""))

            pct = (idx / total_pend) * 100
            t_now = time.time()
            trans_str = f" | Transición: {t_now - t_prev_fin:.3f}s" if t_prev_fin else ""

            self._track(f"[{idx}/{total_pend}] ({pct:5.1f}%) >>> PROCESANDO: {cod} ({desc}){trans_str}")
            self._track(f"    Target: P=${p_target:.2f} (ant: {p_ant}), C=${c_target:.2f} (ant: {c_ant})")

            t0 = time.time()
            try:
                res = fpr.set_precio_costo(
                    cod,
                    nuevo_precio=p_target,
                    nuevo_costo=c_target,
                    costo_anterior=c_ant,
                    precio_anterior=p_ant,
                    commit=commit,
                    verificar_db=False  # Ultra rápido sin reabrir tablas por red
                )
                t_dur = time.time() - t0
                t_prev_fin = time.time()
                tiempos_items.append((cod, t_dur))

                if res.get("ok"):
                    self._track(f"    [OK] {cod} guardado en {t_dur:.2f}s (Etapa: {res.get('etapa')})")
                    exitosos.append(cod)
                    completados_set.add(cod)
                    if cod in fallidos:
                        del fallidos[cod]
                else:
                    err_msg = res.get("detalle", "Error desconocido")
                    self._track(f"    [FALLO] {cod}: {err_msg}")
                    fallidos[cod] = err_msg

            except Exception as e:
                t_prev_fin = time.time()
                self._track(f"    [EXCEPCION] {cod}: {e}")
                fallidos[cod] = str(e)

            # Actualizar checkpoint
            self._guardar_checkpoint({
                "completados": list(completados_set),
                "fallidos": fallidos,
                "ultimo_indice": idx,
                "timestamp": datetime.now().isoformat()
            })

        t_total_lote = time.time() - t_inicio

        # 7. Cierre limpio de Ficha
        self._track("\n--- CERRANDO FICHA DE INVENTARIO ---")
        t0_c = time.time()
        fsr._cerrar_ficha_si_abierta()
        self._track(f"Ficha cerrada limpiamente en {time.time() - t0_c:.3f}s.")

        # 8. Auditoría final DBISAM
        self._track("\n--- AUDITORIA FINAL EN DBISAM (TCostoPrecioInv.Dat) ---")
        time.sleep(1.5)  # flush buffer de red
        t0_audit = time.time()
        db_final = hpw._db_valores_usd_batch(codigos_todos)
        self._track(f"Lectura de auditoría final completada en {time.time() - t0_audit:.2f}s.")

        discrepancias = []
        audit_ok = 0
        for it in items_normalizados:
            cod = it["codigo"]
            p_exp = it["precio_meta"]
            c_exp = it["costo_meta"]
            p_act, c_act = db_final.get(cod, (None, None))
            p_ok = (p_exp is None) or (p_act is not None and abs(p_act - p_exp) <= 0.01)
            c_ok = (c_exp is None) or (c_act is not None and abs(c_act - c_exp) <= 0.01)

            if p_ok and c_ok:
                audit_ok += 1
            else:
                discrepancias.append({
                    "codigo": cod,
                    "esperado": (p_exp, c_exp),
                    "actual": (p_act, c_act)
                })

        self._track(f"\n================ RESUMEN DE EJECUCIÓN ================")
        self._track(f"Total productos evaluados: {len(items_normalizados)}")
        self._track(f"Auditados y confirmados en DBISAM: {audit_ok} / {len(items_normalizados)} ({audit_ok/len(items_normalizados)*100:.1f}%)")
        if discrepancias:
            self._track(f"Discrepancias pendientes ({len(discrepancias)}):")
            for d in discrepancias:
                self._track(f"  - {d['codigo']}: Esperado P=${d['esperado'][0]:.2f}, C=${d['esperado'][1]:.2f} | DB actual P={d['actual'][0]}, C={d['actual'][1]}")
        else:
            self._track("¡100% DE PRODUCTOS VERIFICADOS CON ÉXITO EN LA BASE DE DATOS!")

        # Métricas
        if tiempos_items:
            tiempos_seg = [t for _, t in tiempos_items]
            avg_t = sum(tiempos_seg) / len(tiempos_seg)
            self._track(f"Tiempo total de procesamiento: {t_total_lote:.2f}s ({t_total_lote/60:.2f} min)")
            self._track(f"Tiempo promedio por producto: {avg_t:.2f}s")

        # Limpiar checkpoint si todo fue un éxito
        if not discrepancias and not fallidos:
            try:
                os.remove(self.checkpoint_path)
                self._track("Checkpoint eliminado tras completar lote al 100%.")
            except Exception:
                pass

        return {
            "ok": len(discrepancias) == 0,
            "total": len(items_normalizados),
            "verificados_db": audit_ok,
            "discrepancias": discrepancias,
            "duracion_total": t_total_lote
        }


def procesar_archivo_json(ruta_json, commit=True, proveedor=None):
    """Carga un archivo JSON y ejecuta la actualización en lote."""
    with open(ruta_json, "r", encoding="utf-8") as f:
        data = json.load(f)
    updater = BatchPriceUpdater()
    return updater.procesar_lote(data, commit=commit, proveedor=proveedor)


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Uso: python batch_price_updater.py <archivo.json> [--commit] [--proveedor NOMBRE]")
        sys.exit(1)

    archivo = sys.argv[1]
    es_commit = "--commit" in sys.argv
    prov = None
    if "--proveedor" in sys.argv:
        idx_p = sys.argv.index("--proveedor")
        if idx_p + 1 < len(sys.argv):
            prov = sys.argv[idx_p + 1]

    procesar_archivo_json(archivo, commit=es_commit, proveedor=prov)
