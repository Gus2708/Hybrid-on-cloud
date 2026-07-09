"""test_seleccion.py — Prueba cargar_producto (SIN tocar precio) con varios códigos
que NO son el primero de la lista. Reporta si la Ficha cargó el correcto."""
import sys, time
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass
import flujo_precio as fp
import flujo_precio_real as fpr

CODES = sys.argv[1:] or ["00-015-119", "01775", "03630", "205000011152", "00-002-024"]

resultados = []
for code in CODES:
    print(f"\n===== cargar {code} =====")
    try:
        fpr.cargar_producto(code)
        edits = fpr._ficha_edits()
        ok = fpr._ficha_muestra(code)
        print(f"  -> {'OK ' if ok else 'FALLO'} ficha={edits[:4]}")
        resultados.append((code, ok, edits[:3]))
    except Exception as e:
        print(f"  -> EXCEPCIÓN: {str(e)[:160]}")
        resultados.append((code, False, str(e)[:80]))
        fpr._cerrar_residuales()
    time.sleep(0.5)

print("\n===== RESUMEN =====")
for code, ok, info in resultados:
    print(f"  {code:18} {'OK' if ok else 'FALLO'}  {info}")
