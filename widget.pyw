import tkinter as tk
from tkinter import messagebox
import urllib.request
import json
import threading
import math
import os
import sys
import socket
import time
from datetime import datetime, timezone

# --- Librerías de Terceros ---
try:
    from PIL import Image, ImageTk
    HAS_PIL = True
except ImportError:
    HAS_PIL = False

try:
    import pystray
    from pystray import MenuItem as item
    HAS_TRAY = True
except ImportError:
    HAS_TRAY = False

# --- Configuración ---
SUPABASE_REST_URL = "https://YOUR-PROJECT-REF.supabase.co"
SUPABASE_ANON_KEY = "REDACTED-JWT"

HYBRID_PATHS = [
    r'H:\HybridLite\HybridEmpresa\HybridDataBase\TInventario.dat',
    r'H:\HybridLite\HybridEmpresa\HybridDataBase\TCostoPrecioInv.Dat',
    r'H:\HybridLite\HybridEmpresa\HybridDataBase\TExistenciaInv.Dat',
    r'H:\HybridLite\HybridEmpresa\HybridDataBase\TTransaccionvta.dat',
    r'H:\HybridLite\HybridEmpresa\HybridDataBase\TDetalleVta.dat',
    r'H:\HybridLite\HybridEmpresa\HybridDataBase\TClientes.dat'
]

# --- Protección de Instancia Única ---
try:
    lock_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    lock_socket.bind(('127.0.0.1', 5006)) 
except:
    sys.exit(0)

class SerruchoPremiumWidget:
    def __init__(self, root):
        self.root = root
        self.root.title("Serrucho Monitor")
        self.width = 310
        self.height_full = 335
        self.height_compact = 230
        self.integrity_visible = True
        
        # Estética iOS 17
        self.root.overrideredirect(True)
        self.root.attributes("-topmost", True)
        self.root.attributes("-transparentcolor", "#010101")
        self.root.config(bg="#010101")
        
        screen_w = self.root.winfo_screenwidth()
        self.root.geometry(f"{self.width}x{self.height_full}+{screen_w - self.width - 20}+20")
        
        self.colors = {
            "bg": "#1C1C1E", "card": "#2C2C2E",
            "green": "#32D74B", "blue": "#0A84FF",
            "yellow": "#FFD60A", "red": "#FF453A",
            "text": "#FFFFFF", "subtext": "#8E8E93"
        }
        
        self.canvas = tk.Canvas(root, width=self.width, height=500, bg="#010101", highlightthickness=0, bd=0)
        self.canvas.pack()
        
        # Fondo Principal
        self.bg_rect = self.draw_rounded_rect(0, 0, self.width, self.height_full, 28, self.colors["bg"], tags="bg_layer")
        
        # Cabecera
        self.canvas.create_text(25, 22, text="El Serrucho", fill=self.colors["text"], font=("Inter", 12, "bold"), anchor="w", tags="title")
        self.status_dot = self.canvas.create_oval(260, 17, 270, 27, fill=self.colors["green"], outline="")
        
        base_dir = os.path.dirname(os.path.abspath(__file__))
        logo_path = os.path.join(base_dir, "assets", "logo.png")
        if os.path.exists(logo_path) and HAS_PIL:
            try:
                pil_img = Image.open(logo_path).resize((22, 22), Image.Resampling.LANCZOS)
                self.logo_img = ImageTk.PhotoImage(pil_img)
                self.canvas.create_image(18, 22, image=self.logo_img, anchor="w")
                self.canvas.move(self.canvas.find_withtag("title"), 30, 0)
            except: pass
        self.canvas.create_text(290, 22, text="✕", fill=self.colors["subtext"], font=("Inter", 10, "bold"), tags="close_btn")
        self.canvas.tag_bind("close_btn", "<Button-1>", lambda e: self.hide_to_tray())

        # Estado
        self.status_label = self.canvas.create_text(25, 50, text="Sistema Activo", fill=self.colors["text"], font=("Inter", 10, "bold"), anchor="w")
        self.detail_label = self.canvas.create_text(25, 68, text="Monitoreando archivos...", fill=self.colors["subtext"], font=("Inter", 8), anchor="w")

        # --- Card de Tasas ---
        self.draw_rounded_rect(15, 85, 295, 135, 12, self.colors["card"])
        self.rate_label = self.canvas.create_text(155, 103, text="BCV: --.-- | BNB: --.--", fill=self.colors["text"], font=("Inter", 10, "bold"))
        self.diff_label = self.canvas.create_text(155, 122, text="Brecha: --.--%", fill=self.colors["yellow"], font=("Inter", 8, "bold"))

        # --- Card de Integridad ---
        self.canvas.create_text(25, 153, text="INTEGRIDAD DE DATOS", fill=self.colors["subtext"], font=("Inter", 7, "bold"), anchor="w", tags="integrity_header")
        self.toggle_btn = self.canvas.create_text(285, 153, text="▼", fill=self.colors["subtext"], font=("Inter", 7, "bold"), anchor="e", tags="integrity_header")
        
        self.integrity_card_bg = self.draw_rounded_rect(15, 165, 295, 235, 12, self.colors["card"], tags="integrity_ui")
        self.integrity_labels = {}
        y_start = 182
        for i, (key, label) in enumerate([("productos", "Productos"), ("ventas", "Ventas"), ("detalle", "Detalle"), ("clientes", "Clientes")]):
            y = y_start + i * 13
            self.canvas.create_text(30, y, text=label, fill=self.colors["subtext"], font=("Inter", 8), anchor="w", tags="integrity_ui")
            self.integrity_labels[key] = self.canvas.create_text(280, y, text="...", fill=self.colors["subtext"], font=("Inter", 8), anchor="e", tags="integrity_ui")
        
        self.canvas.tag_bind("integrity_header", "<Button-1>", lambda e: self.toggle_integrity())

        # --- Footer ---
        self.btn_bg = self.draw_rounded_rect(15, 248, 295, 285, 12, self.colors["blue"], tags="footer_ui")
        self.btn_text = self.canvas.create_text(155, 267, text="Sincronizar Ahora", fill="#FFFFFF", font=("Inter", 9, "bold"), tags="footer_ui")
        self.sync_time_label = self.canvas.create_text(155, 298, text="Último Sync: ...", fill=self.colors["subtext"], font=("Inter", 7), tags="footer_ui")
        self.check_time_label = self.canvas.create_text(155, 308, text="Último Monitoreo: --/-- --:--", fill=self.colors["subtext"], font=("Inter", 7), tags="footer_ui")
        
        # IP Label
        self.ip_addr = self.get_local_ip()
        self.ip_label = self.canvas.create_text(155, 320, text=f"IP Local: {self.ip_addr}", fill="#444444", font=("Inter", 6), tags="footer_ui")
        
        self.canvas.tag_bind("bg_layer", "<ButtonPress-1>", self.start_move)
        self.canvas.tag_bind("bg_layer", "<B1-Motion>", self.do_move)
        self.canvas.tag_bind("footer_ui", "<Button-1>", lambda e: self.trigger_sync_flow())
        self.root.bind("<Button-3>", lambda e: self.quit_app())

        self.is_syncing = False
        self.anim_f = 0
        self.load_last_sync_time()
        self.animate()
        self.update_loop()
        self.check_loop()
        self.verify_loop()
        if HAS_TRAY: threading.Thread(target=self.setup_tray, daemon=True).start()

    def get_rounded_points(self, x1, y1, x2, y2, r):
        return [x1+r, y1, x1+r, y1, x2-r, y1, x2-r, y1, x2, y1, x2, y1+r, x2, y1+r, x2, y2-r, x2, y2-r, x2, y2, x2-r, y2, x2-r, y2, x1+r, y2, x1+r, y2, x1, y2, x1, y2-r, x1, y2-r, x1, y1+r, x1, y1+r, x1, y1]

    def toggle_integrity(self):
        self.integrity_visible = not self.integrity_visible
        if self.integrity_visible:
            self.canvas.itemconfig("integrity_ui", state="normal")
            self.canvas.itemconfig(self.toggle_btn, text="▼")
            dy, h = 75, self.height_full
        else:
            self.canvas.itemconfig("integrity_ui", state="hidden")
            self.canvas.itemconfig(self.toggle_btn, text="▶")
            dy, h = -105, self.height_compact

        self.canvas.move("footer_ui", 0, dy)
        # CORRECCIÓN: Recalcular puntos del polígono para que no se rompa el fondo
        new_pts = self.get_rounded_points(0, 0, self.width, h, 28)
        self.canvas.coords(self.bg_rect, *new_pts)
        self.root.geometry(f"{self.width}x{h}")

    def get_local_ip(self):
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect(("8.8.8.8", 80))
            ip = s.getsockname()[0]
            s.close()
            return ip
        except:
            return "127.0.0.1"

    def load_last_sync_time(self):
        try:
            base_dir = os.path.dirname(os.path.abspath(__file__))
            syncs = ["last_sync.json", "ventas_last_sync.json"]
            max_ts = 0
            for f in syncs:
                p = os.path.join(base_dir, f)
                if os.path.exists(p):
                    with open(p, "r") as fh:
                        ts = json.load(fh).get("timestamp", 0)
                        if ts > max_ts: max_ts = ts
            if max_ts > 0:
                now_str = datetime.fromtimestamp(max_ts).strftime("%d/%m %H:%M:%S")
                self.canvas.itemconfig(self.sync_time_label, text=f"Último Sync: {now_str}")
                self.last_synced_at = max_ts
            else: self.last_synced_at = time.time()
        except: self.last_synced_at = time.time()

    def setup_tray(self):
        try:
            base_dir = os.path.dirname(os.path.abspath(__file__))
            logo_path = os.path.join(base_dir, "assets", "logo.png")
            icon_img = Image.open(logo_path) if os.path.exists(logo_path) else Image.new('RGB', (64, 64), (52, 199, 89))
            menu = (item('Mostrar Monitor', self.show_from_tray, default=True), item('Salir', self.quit_app))
            self.tray_icon = pystray.Icon("Serrucho", icon_img, "El Serrucho", menu)
            self.tray_icon.run()
        except: pass

    def hide_to_tray(self): self.root.withdraw()
    def show_from_tray(self):
        self.root.deiconify()
        self.root.attributes("-topmost", True)

    def check_loop(self):
        def task():
            try:
                has_changes = False
                for path in HYBRID_PATHS:
                    if os.path.exists(path) and os.path.getmtime(path) > (self.last_synced_at + 5):
                        has_changes = True; break
                if has_changes and not self.is_syncing: self.root.after(0, self.trigger_sync_flow)
                now_str = datetime.now().strftime("%d/%m %H:%M:%S")
                self.root.after(0, lambda: self.canvas.itemconfig(self.check_time_label, text=f"Último Monitoreo: {now_str}"))
            except: pass
            self.root.after(5000, self.check_loop)
        threading.Thread(target=task, daemon=True).start()

    def verify_loop(self):
        def task():
            if self.is_syncing or not self.integrity_visible:
                self.root.after(15000, self.verify_loop); return
            try:
                req = urllib.request.Request("http://localhost:5000/api/v1/sync/status")
                with urllib.request.urlopen(req, timeout=10) as resp:
                    data = json.loads(resp.read().decode())
                    entities = data.get("entities", {})
                    for key, info in entities.items():
                        if key in self.integrity_labels:
                            local, cloud, ok = info.get("local", 0), info.get("cloud", -1), info.get("ok", False)
                            if cloud < 0: txt, color = "Sin conexión", self.colors["red"]
                            elif ok: txt, color = f"{local:,} ✓", self.colors["green"]
                            else: txt, color = f"Local: {local:,} | Nube: {cloud:,}", self.colors["yellow"]
                            lbl = self.integrity_labels[key]
                            self.root.after(0, lambda l=lbl, t=txt, c=color: self.canvas.itemconfig(l, text=t, fill=c))
            except: pass
            self.root.after(15000, self.verify_loop)
        threading.Thread(target=task, daemon=True).start()

    def draw_rounded_rect(self, x1, y1, x2, y2, r, color, tags=""):
        p = self.get_rounded_points(x1, y1, x2, y2, r)
        return self.canvas.create_polygon(p, smooth=True, fill=color, tags=tags)

    def trigger_sync_flow(self):
        if self.is_syncing: return
        self.is_syncing = True
        self.canvas.itemconfig(self.btn_bg, fill=self.colors["card"])
        self.canvas.itemconfig(self.btn_text, text="Procesando...")
        def run():
            steps = [("Sincronizando Inventario...", "http://localhost:5000/api/v1/sync/inventory"),
                     ("Sincronizando Ventas...", "http://localhost:5000/api/v1/sync/sales")]
            for msg, url in steps:
                self.root.after(0, lambda m=msg: self.canvas.itemconfig(self.detail_label, text=m))
                try:
                    req = urllib.request.Request(url, method="POST")
                    with urllib.request.urlopen(req, timeout=120) as resp: pass
                except: pass
            self.last_synced_at = time.time()
            self.is_syncing = False
            self.root.after(0, self.reset_ui)
        threading.Thread(target=run, daemon=True).start()

    def reset_ui(self):
        self.canvas.itemconfig(self.btn_bg, fill=self.colors["blue"])
        self.canvas.itemconfig(self.btn_text, text="Sincronizar Ahora")
        self.canvas.itemconfig(self.detail_label, text="Sincronización Completada ✓")
        now_str = datetime.now().strftime("%d/%m %H:%M:%S")
        self.canvas.itemconfig(self.sync_time_label, text=f"Último Sync: {now_str}")
        self.root.after(3000, lambda: self.canvas.itemconfig(self.detail_label, text="Monitoreando archivos..."))

    def update_loop(self):
        def task():
            try:
                url = f"{SUPABASE_REST_URL}/rest/v1/tazas?nombre=eq.actual&limit=1"
                headers = {"apikey": SUPABASE_ANON_KEY, "Authorization": f"Bearer {SUPABASE_ANON_KEY}"}
                req = urllib.request.Request(url, headers=headers)
                with urllib.request.urlopen(req, timeout=5) as resp:
                    data = json.loads(resp.read().decode())
                    if data:
                        bcv, bnb = data[0].get("bcv_usd", 0), data[0].get("binance_p2p", 0)
                        self.root.after(0, lambda: self.canvas.itemconfig(self.rate_label, text=f"BCV: {bcv:,.2f} | BNB: {bnb:,.2f}"))
                        if bcv > 0:
                            diff = ((bnb / bcv) - 1) * 100
                            self.root.after(0, lambda: self.canvas.itemconfig(self.diff_label, text=f"Brecha: +{diff:.2f}%"))
            except: pass
            self.root.after(10000, self.update_loop)
        threading.Thread(target=task, daemon=True).start()

    def animate(self):
        self.anim_f += 0.1
        color = self.colors["yellow"] if self.is_syncing else self.colors["green"]
        self.canvas.itemconfig(self.status_dot, fill=color)
        self.root.after(50, self.animate)

    def start_move(self, event): self.x, self.y = event.x, event.y
    def do_move(self, event): self.root.geometry(f"+{self.root.winfo_x()+(event.x-self.x)}+{self.root.winfo_y()+(event.y-self.y)}")
    def quit_app(self):
        if HAS_TRAY and hasattr(self, "tray_icon"): self.tray_icon.stop()
        self.root.quit(); sys.exit()

if __name__ == "__main__":
    root = tk.Tk()
    app = SerruchoPremiumWidget(root)
    root.mainloop()
