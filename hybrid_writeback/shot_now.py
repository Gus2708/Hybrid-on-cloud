import os, sys, time
import win32gui, win32process
from PIL import ImageGrab
DIR = os.path.dirname(os.path.abspath(__file__))
name = sys.argv[1] if len(sys.argv) > 1 else "shot_now.png"

# listar ventanas top-level visibles con texto (para identificar la nueva)
out = []
def cb(h, _):
    if not win32gui.IsWindowVisible(h): return
    cls = win32gui.GetClassName(h) or ""
    txt = win32gui.GetWindowText(h) or ""
    try:
        _, pid = win32process.GetWindowThreadProcessId(h)
    except Exception:
        return
    if cls.startswith(("TF", "TForm", "TT", "TFH")) and (txt or cls):
        out.append((h, cls, txt, pid))
win32gui.EnumWindows(cb, None)
print("ventanas VCL (TF*/TForm*/TT*):")
for h, cls, txt, pid in out:
    r = win32gui.GetWindowRect(h)
    print(f"  cls={cls!r} title={txt!r} rect={r} pid={pid}")

ImageGrab.grab().save(os.path.join(DIR, name))
print("guardado", name)
