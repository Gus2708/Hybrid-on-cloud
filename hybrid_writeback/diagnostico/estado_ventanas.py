"""estado_ventanas.py — Lista ventanas VCL visibles de HybridLiteOS (diagnóstico)."""
import win32gui
def cb(h, acc):
    if not win32gui.IsWindowVisible(h): return
    cls = win32gui.GetClassName(h) or ""
    txt = win32gui.GetWindowText(h) or ""
    if cls.startswith(("TF","TT","Tfrx","TForm")):
        acc.append((cls, txt))
acc=[]; win32gui.EnumWindows(cb, acc)
for cls, txt in acc:
    print(f"  {cls} :: {txt[:45]!r}")
