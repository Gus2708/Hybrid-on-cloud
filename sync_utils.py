"""
sync_utils.py — Utilidades compartidas entre sync.py y sync_ventas.py.
"""
import sys
import subprocess


def set_priority_low():
    """Establece prioridad baja para no impactar el rendimiento de Windows."""
    if sys.platform == "win32":
        try:
            import win32api, win32process, win32con
            pid = win32api.GetCurrentProcessId()
            handle = win32api.OpenProcess(win32con.PROCESS_ALL_ACCESS, True, pid)
            win32process.SetPriorityClass(handle, win32process.BELOW_NORMAL_PRIORITY_CLASS)
        except Exception:
            pass


def _kill_proc(proc):
    """Mata un proceso forzadamente en Windows."""
    try:
        if proc.poll() is None:
            subprocess.run(
                ["taskkill", "/F", "/T", "/PID", str(proc.pid)],
                capture_output=True,
                timeout=5,
            )
            proc.wait(timeout=5)
    except Exception:
        pass


def safe_decimal(val) -> float:
    """Convierte un valor (incluyendo formato venezolano '1.500,50' y prefijo 'Bs.') a float."""
    if val is None:
        return 0.0
    s = str(val).replace("Bs.", "").replace(" ", "").strip()
    if not s:
        return 0.0
    if "," in s and "." in s:
        s = s.replace(".", "").replace(",", ".")
    elif "," in s:
        s = s.replace(",", ".")
    try:
        return float(s)
    except (ValueError, TypeError):
        return 0.0


def exponential_backoff(attempt: int) -> float:
    """Calcula delay de backoff exponencial con techo de 15 segundos."""
    return min(1.5 ** attempt, 15.0)


def filter_valid_detail_rows(rows, valid_codes):
    """Descarta líneas de detalle cuyo producto (TBT_CODIGO) ya no existe en el maestro.

    Esas líneas violan la FK fk_ventas_detalle_producto en Supabase. Si el maestro
    está vacío (lectura fallida) no se filtra nada, para no descartar todo el detalle.
    """
    if not valid_codes:
        return list(rows)
    return [r for r in rows if r.get("TBT_CODIGO", "").strip() in valid_codes]


def count_valid_detail_rows(detalle_path: str, maestro_path: str) -> int:
    """Cuenta líneas de detalle con producto existente en el maestro.

    Si falta alguno de los CSV, cae al conteo de filas crudas del detalle.
    """
    import csv
    import os
    try:
        if not os.path.exists(detalle_path):
            return 0
        if not os.path.exists(maestro_path):
            with open(detalle_path, "rb") as f:
                return max(0, sum(1 for _ in f) - 1)
        with open(maestro_path, "r", encoding="utf-8-sig", newline="") as f:
            valid = {r["CODIGO_INTERNO"].strip() for r in csv.DictReader(f)}
        with open(detalle_path, "r", encoding="utf-8-sig", newline="") as f:
            return len(filter_valid_detail_rows(csv.DictReader(f), valid))
    except Exception:
        return 0
