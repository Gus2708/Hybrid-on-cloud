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

# --- Librerías de Terceros (Pillow y Pystray) ---
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
    r'H:\HybridLite\HybridEmpresa\HybridDataBase\TExistenciaInv.Dat'
]

# --- Protección de Instancia Única ---
try:
    lock_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    lock_socket.bind(('127.0.0.1', 5005)) # Puerto nuevo para evitar bloqueos
except:
    sys.exit(0)

class SerruchoDefinitiveWidget:
    def __init__(self, root):
        self.root = root
        self.root.title("Serrucho Monitor")
        self.width, self.height = 300, 200 # Compactado
        self.root.geometry(f"{self.width}x{self.height}+80+80")
        
        # Estética iOS
        self.root.overrideredirect(True)
        self.root.attributes("-topmost", True)
        self.root.attributes("-transparentcolor", "#010101")
        self.root.config(bg="#010101")
        
        self.colors = {
            "bg": "#1C1C1E",
            "green": "#34C759", "green_glow": "#1A3D23",
            "red": "#FF3B30", "red_glow": "#3D1A1A",
            "yellow": "#FFCC00", "yellow_glow": "#423A00",
            "text": "#FFFFFF", "subtext": "#8E8E93", "btn": "#2C2C2E"
        }
        
        self.canvas = tk.Canvas(root, width=self.width, height=self.height, bg="#010101", highlightthickness=0, bd=0)
        self.canvas.pack()
        self.draw_rounded_rect(0, 0, self.width, self.height, 25, self.colors["bg"], tags="bg")
        
        # Logo y Título
        self.logo_img = None
        base_dir = os.path.dirname(os.path.abspath(__file__))
        logo_path = os.path.join(base_dir, "assets", "logo.png")
        if os.path.exists(logo_path) and HAS_PIL:
            try:
                pil_img = Image.open(logo_path).resize((30, 30), Image.Resampling.LANCZOS)
                self.logo_img = ImageTk.PhotoImage(pil_img)
                self.canvas.create_image(35, 30, image=self.logo_img)
            except: pass
        
        self.canvas.create_text(60, 30, text="Backend El Serrucho", fill=self.colors["text"], font=("Inter", 10, "bold"), anchor="w")
        
        # Glow y Status
        self.glow_layers = [self.canvas.create_oval(40-r, 75-r, 40+r, 75+r, fill=self.colors["bg"], outline="") for r in range(12, 5, -2)]
        self.status_dot = self.canvas.create_oval(34, 69, 46, 81, fill=self.colors["red"], outline="")
        self.status_label = self.canvas.create_text(60, 75, text="Iniciando...", anchor="w", fill=self.colors["subtext"], font=("Inter", 9))
        self.sync_label = self.canvas.create_text(self.width/2, 100, text="Verificando nube...", fill=self.colors["subtext"], font=("Inter", 8))
        self.rate_label = self.canvas.create_text(self.width/2, 120, text="BCV: --.-- | Binance: --.--", fill=self.colors["text"], font=("Inter", 9, "bold"))
        self.diff_label = self.canvas.create_text(self.width/2, 140, text="Brecha: --.--%", fill=self.colors["yellow"], font=("Inter", 8, "bold"))

        # Botones
        self.draw_rounded_rect(50, 160, 250, 190, 15, self.colors["btn"], tags="btn")
        self.btn_text = self.canvas.create_text(150, 175, text="Sincronizar Ahora", fill=self.colors["green"], font=("Inter", 9, "bold"))
        self.close_btn = self.canvas.create_text(275, 25, text="✕", fill=self.colors["subtext"], font=("Inter", 10, "bold"))

        # Eventos
        self.canvas.tag_bind("bg", "<ButtonPress-1>", self.start_move)
        self.canvas.tag_bind("bg", "<B1-Motion>", self.do_move)
        self.canvas.tag_bind("btn", "<Button-1>", lambda e: self.trigger_sync())
        self.canvas.tag_bind(self.btn_text, "<Button-1>", lambda e: self.trigger_sync())
        self.canvas.tag_bind(self.close_btn, "<Button-1>", lambda e: self.hide_to_tray())

        # Control
        self.anim_frame, self.is_online, self.needs_sync, self.is_syncing = 0, False, False, False
        self.last_cloud_ts = 0
        
        self.animate()
        self.check_loop()
        
        if HAS_TRAY:
            threading.Thread(target=self.setup_tray, daemon=True).start()

    def hide_to_tray(self):
        self.root.withdraw()

    def show_from_tray(self):
        self.root.deiconify()
        self.root.attributes("-topmost", True)

    def setup_tray(self):
        try:
            logo_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets", "logo.png")
            icon_img = Image.open(logo_path) if os.path.exists(logo_path) else Image.new('RGB', (64, 64), (52, 199, 89))
            menu = (item('Mostrar Monitor', self.show_from_tray, default=True), item('Salir', self.quit_app))
            self.tray_icon = pystray.Icon("Serrucho", icon_img, "El Serrucho", menu)
            self.tray_icon.run()
        except: pass

    def quit_app(self):
        if HAS_TRAY: self.tray_icon.stop()
        self.root.quit()
        sys.exit()

    def draw_rounded_rect(self, x1, y1, x2, y2, r, color, tags=""):
        p = [x1+r, y1, x1+r, y1, x2-r, y1, x2-r, y1, x2, y1, x2, y1+r, x2, y1+r, x2, y2-r, x2, y2-r, x2, y2, x2-r, y2, x2-r, y2, x1+r, y2, x1+r, y2, x1, y2, x1, y2-r, x1, y2-r, x1, y1+r, x1, y1+r, x1, y1]
        return self.canvas.create_polygon(p, smooth=True, fill=color, tags=tags)

    def check_loop(self):
        if self.is_syncing:
            self.root.after(5000, self.check_loop)
            return

        def task():
            try:
                url = f"{SUPABASE_REST_URL}/rest/v1/productos?select=actualizado_en&order=actualizado_en.desc&limit=1"
                req = urllib.request.Request(url, headers={"apikey": SUPABASE_ANON_KEY, "Authorization": f"Bearer {SUPABASE_ANON_KEY}"})
                with urllib.request.urlopen(req, timeout=5) as resp:
                    res = json.loads(resp.read().decode())
                    if res:
                        dt = datetime.fromisoformat(res[0]['actualizado_en'].replace('Z', '+00:00'))
                        self.last_cloud_ts = dt.timestamp()
                        # Mostrar siempre la fecha y hora exacta
                        status_text = f"Nube: {dt.astimezone().strftime('%d/%m %H:%M:%S')}"
                        self.root.after(0, lambda: self.canvas.itemconfig(self.sync_label, text=status_text))
                        self.is_online = True
            except: self.is_online = False

            # NUEVO: Obtener últimas tasas
            try:
                rate_url = f"{SUPABASE_REST_URL}/rest/v1/tazas?order=created_at.desc&limit=1"
                rate_req = urllib.request.Request(rate_url, headers={"apikey": SUPABASE_ANON_KEY, "Authorization": f"Bearer {SUPABASE_ANON_KEY}"})
                with urllib.request.urlopen(rate_req, timeout=5) as r_resp:
                    r_res = json.loads(r_resp.read().decode())
                    if r_res:
                        bcv = float(r_res[0].get('bcv_usd', 0))
                        binance = float(r_res[0].get('binance_p2p', 0))
                        
                        self.root.after(0, lambda: self.canvas.itemconfig(self.rate_label, text=f"BCV: {bcv:,.2f} | BNB: {binance:,.2f}"))
                        
                        if bcv > 0:
                            diff = ((binance / bcv) - 1) * 100
                            # Color según la brecha (amarillo si es > 5%, rojo si es > 10%)
                            color = self.colors["yellow"] if diff < 10 else self.colors["red"]
                            if diff < 3: color = self.colors["subtext"]
                            
                            self.root.after(0, lambda d=diff, c=color: self.canvas.itemconfig(self.diff_label, text=f"Brecha: +{d:.2f}%", fill=c))
            except Exception as e:
                print(f"[WIDGET] Error obteniendo tasas: {e}")

            has_changes = False
            for path in HYBRID_PATHS:
                if os.path.exists(path):
                    mtime = os.path.getmtime(path)
                    # Comparamos con un margen de 5 segundos para mayor sensibilidad
                    if mtime > (self.last_cloud_ts + 5):
                        has_changes = True
                        break
            
            self.needs_sync = has_changes
            self.root.after(0, self.update_ui)
            
            # Solo disparar sync automatico si hay cambios, estamos online y NO estamos ya sincronizando
            if self.needs_sync and self.is_online and not self.is_syncing:
                print(f"[WIDGET] Detectados cambios en HybridLite. Disparando sync automatico...")
                self.root.after(0, lambda: self.trigger_sync(auto=True))
            
            self.root.after(2000, self.check_loop) # Revisar cada 2 seg (Modo Instantáneo)
            
        threading.Thread(target=task, daemon=True).start()

    def update_ui(self):
        if self.is_syncing:
            self.canvas.itemconfig(self.status_label, text="Sincronizando...", fill=self.colors["yellow"])
        elif not self.is_online:
            self.canvas.itemconfig(self.status_label, text="Sin Conexión", fill=self.colors["red"])
        elif self.needs_sync:
            self.canvas.itemconfig(self.status_label, text="Cambios Detectados", fill=self.colors["yellow"])
        else:
            self.canvas.itemconfig(self.status_label, text="Inventario al Día", fill=self.colors["green"])

    def trigger_sync(self, *args):
        if self.is_syncing: return
        self.is_syncing = True
        self.canvas.itemconfig(self.btn_text, text="Procesando...")
        self.update_ui()
        
        def run():
            try:
                # Intentar llamar al endpoint de la API local
                # Usamos POST para mayor seguridad
                req = urllib.request.Request("http://localhost:5000/api/v1/sync/run", method="POST")
                with urllib.request.urlopen(req, timeout=120) as resp:
                    pass
            except Exception as e:
                print(f"[WIDGET] Error en trigger_sync: {e}")
            
            self.is_syncing = False
            self.root.after(0, lambda: (self.canvas.itemconfig(self.btn_text, text="Sincronizar Ahora"), self.update_ui()))
            # Forzar un chequeo inmediato para limpiar el estado de "Cambios Detectados"
            self.root.after(500, self.check_loop) 
        
        threading.Thread(target=run, daemon=True).start()

    def animate(self):
        self.anim_frame += 0.08
        f = (math.sin(self.anim_frame) + 1) / 2
        status = "green" if self.is_online and not self.needs_sync and not self.is_syncing else ("yellow" if (self.needs_sync or self.is_syncing) else "red")
        base_color = self.colors[status]
        glow_color = self.colors[status + "_glow"]
        self.canvas.itemconfig(self.status_dot, fill=base_color)
        for i, layer in enumerate(self.glow_layers):
            r1, g1, b1 = tuple(int(self.colors["bg"].lstrip('#')[j:j+2], 16) for j in (0, 2, 4))
            r2, g2, b2 = tuple(int(glow_color.lstrip('#')[j:j+2], 16) for j in (0, 2, 4))
            it = (1-(i/len(self.glow_layers)))*f
            self.canvas.itemconfig(layer, fill=f'#{int(r1+(r2-r1)*it):02x}{int(g1+(g2-g1)*it):02x}{int(b1+(b2-b1)*it):02x}')
        self.root.after(16, self.animate)

    def start_move(self, event): self.x, self.y = event.x, event.y
    def do_move(self, event):
        self.root.geometry(f"+{self.root.winfo_x()+(event.x-self.x)}+{self.root.winfo_y()+(event.y-self.y)}")

if __name__ == "__main__":
    root = tk.Tk()
    app = SerruchoDefinitiveWidget(root)
    root.mainloop()
