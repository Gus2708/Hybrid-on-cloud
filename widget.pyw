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
        self.width, self.height = 300, 220
        
        # Estética iOS 17 (Dark Mode)
        self.root.overrideredirect(True)
        self.root.attributes("-topmost", True)
        self.root.attributes("-transparentcolor", "#010101")
        self.root.config(bg="#010101")
        
        screen_w = self.root.winfo_screenwidth()
        self.root.geometry(f"{self.width}x{self.height}+{screen_w - self.width - 20}+20")
        
        self.colors = {
            "bg": "#1C1C1E",
            "card": "#2C2C2E",
            "green": "#32D74B", "green_glow": "#1A3D23",
            "blue": "#0A84FF",
            "yellow": "#FFD60A",
            "red": "#FF453A",
            "text": "#FFFFFF", "subtext": "#8E8E93"
        }
        
        self.canvas = tk.Canvas(root, width=self.width, height=self.height, bg="#010101", highlightthickness=0, bd=0)
        self.canvas.pack()
        
        # Fondo Redondeado
        self.draw_rounded_rect(0, 0, self.width, self.height, 28, self.colors["bg"], tags="bg")
        
        # Cabecera
        self.canvas.create_text(25, 25, text="El Serrucho", fill=self.colors["text"], font=("Inter", 12, "bold"), anchor="w", tags="title")
        self.status_dot = self.canvas.create_oval(250, 20, 260, 30, fill=self.colors["green"], outline="")
        
        # Línea de estado principal
        self.status_label = self.canvas.create_text(25, 55, text="Sistema Activo", fill=self.colors["text"], font=("Inter", 10, "bold"), anchor="w")
        self.detail_label = self.canvas.create_text(25, 75, text="Monitoreando archivos...", fill=self.colors["subtext"], font=("Inter", 8), anchor="w")
        
        # Logo
        self.logo_img = None
        base_dir = os.path.dirname(os.path.abspath(__file__))
        logo_path = os.path.join(base_dir, "assets", "logo.png")
        if os.path.exists(logo_path) and HAS_PIL:
            try:
                pil_img = Image.open(logo_path).resize((25, 25), Image.Resampling.LANCZOS)
                self.logo_img = ImageTk.PhotoImage(pil_img)
                self.canvas.create_image(20, 25, image=self.logo_img, anchor="w")
                # Mover título si hay logo
                self.canvas.move(self.canvas.find_withtag("title"), 35, 0)
            except: pass

        # Botón de Cerrar (X)
        self.close_btn = self.canvas.create_text(280, 25, text="✕", fill=self.colors["subtext"], font=("Inter", 10, "bold"))
        self.canvas.tag_bind(self.close_btn, "<Button-1>", lambda e: self.hide_to_tray())

        # Área de Tasas (Card)
        self.draw_rounded_rect(20, 100, 280, 155, 15, self.colors["card"])
        self.rate_label = self.canvas.create_text(150, 120, text="BCV: --.-- | BNB: --.--", fill=self.colors["text"], font=("Inter", 10, "bold"))
        self.diff_label = self.canvas.create_text(150, 140, text="Brecha: --.--%", fill=self.colors["yellow"], font=("Inter", 8, "bold"))
        
        # Botón de Sincronización
        self.btn_bg = self.draw_rounded_rect(20, 165, 280, 205, 12, self.colors["blue"], tags="btn")
        self.btn_text = self.canvas.create_text(150, 185, text="Sincronizar Ahora", fill="#FFFFFF", font=("Inter", 9, "bold"), tags="btn")
        
        # Eventos
        self.canvas.tag_bind("bg", "<ButtonPress-1>", self.start_move)
        self.canvas.tag_bind("bg", "<B1-Motion>", self.do_move)
        self.canvas.tag_bind("btn", "<Button-1>", lambda e: self.trigger_sync_flow())
        
        # Clic derecho para cerrar
        self.root.bind("<Button-3>", lambda e: self.quit_app())

        # Estado
        self.is_syncing = False
        self.anim_f = 0
        self.last_synced_at = time.time()  # Arrancar "al día" para no disparar sync inmediata
        
        self.animate()
        self.update_loop()
        self.check_loop()
        
        if HAS_TRAY:
            threading.Thread(target=self.setup_tray, daemon=True).start()

    def setup_tray(self):
        try:
            base_dir = os.path.dirname(os.path.abspath(__file__))
            logo_path = os.path.join(base_dir, "assets", "logo.png")
            icon_img = Image.open(logo_path) if os.path.exists(logo_path) else Image.new('RGB', (64, 64), (52, 199, 89))
            menu = (item('Mostrar Monitor', self.show_from_tray, default=True), item('Salir', self.quit_app))
            self.tray_icon = pystray.Icon("Serrucho", icon_img, "El Serrucho", menu)
            self.tray_icon.run()
        except: pass

    def hide_to_tray(self):
        self.root.withdraw()

    def show_from_tray(self):
        self.root.deiconify()
        self.root.attributes("-topmost", True)

    def check_loop(self):
        def task():
            try:
                # Comparar archivos locales contra nuestra última sincronización
                has_changes = False
                for path in HYBRID_PATHS:
                    if os.path.exists(path):
                        mtime = os.path.getmtime(path)
                        if mtime > (self.last_synced_at + 5):
                            has_changes = True
                            break
                
                if has_changes and not self.is_syncing:
                    self.root.after(0, self.trigger_sync_flow)
            except Exception as e:
                print(f"Error en check_loop: {e}")
            self.root.after(5000, self.check_loop)
        
        threading.Thread(target=task, daemon=True).start()

    def draw_rounded_rect(self, x1, y1, x2, y2, r, color, tags=""):
        p = [x1+r, y1, x1+r, y1, x2-r, y1, x2-r, y1, x2, y1, x2, y1+r, x2, y1+r, x2, y2-r, x2, y2-r, x2, y2, x2-r, y2, x2-r, y2, x1+r, y2, x1+r, y2, x1, y2, x1, y2-r, x1, y2-r, x1, y1+r, x1, y1+r, x1, y1]
        return self.canvas.create_polygon(p, smooth=True, fill=color, tags=tags)

    def trigger_sync_flow(self):
        if self.is_syncing: return
        self.is_syncing = True
        self.canvas.itemconfig(self.btn_bg, fill=self.colors["card"])
        self.canvas.itemconfig(self.btn_text, text="Procesando...")
        
        def run():
            steps = [
                ("Sincronizando Inventario...", "http://localhost:5000/api/v1/sync/inventory"),
                ("Sincronizando Ventas...", "http://localhost:5000/api/v1/sync/sales")
            ]
            
            for msg, url in steps:
                self.root.after(0, lambda m=msg: self.canvas.itemconfig(self.detail_label, text=m))
                try:
                    req = urllib.request.Request(url, method="POST")
                    with urllib.request.urlopen(req, timeout=120) as resp:
                        pass
                except Exception as e:
                    print(f"Error en {msg}: {e}")
            
            # CLAVE: Marcar el momento en que terminamos de sincronizar
            self.last_synced_at = time.time()
            self.is_syncing = False
            self.root.after(0, self.reset_ui)

        threading.Thread(target=run, daemon=True).start()

    def reset_ui(self):
        self.canvas.itemconfig(self.btn_bg, fill=self.colors["blue"])
        self.canvas.itemconfig(self.btn_text, text="Sincronizar Ahora")
        self.canvas.itemconfig(self.detail_label, text="Sincronización Completada ✓")
        self.root.after(3000, lambda: self.canvas.itemconfig(self.detail_label, text="Monitoreando archivos..."))

    def update_loop(self):
        def task():
            try:
                # Actualizar Tasas
                url = f"{SUPABASE_REST_URL}/rest/v1/tazas?nombre=eq.actual&limit=1"
                headers = {"apikey": SUPABASE_ANON_KEY, "Authorization": f"Bearer {SUPABASE_ANON_KEY}"}
                req = urllib.request.Request(url, headers=headers)
                with urllib.request.urlopen(req, timeout=5) as resp:
                    data = json.loads(resp.read().decode())
                    if data:
                        bcv = data[0].get("bcv_usd", 0)
                        bnb = data[0].get("binance_p2p", 0)
                        self.root.after(0, lambda: self.canvas.itemconfig(self.rate_label, text=f"BCV: {bcv:,.2f} | BNB: {bnb:,.2f}"))
                        
                        if bcv > 0:
                            diff = ((bnb / bcv) - 1) * 100
                            self.root.after(0, lambda: self.canvas.itemconfig(self.diff_label, text=f"Brecha: +{diff:.2f}%"))
            except: pass
            self.root.after(10000, self.update_loop)
        
        threading.Thread(target=task, daemon=True).start()

    def animate(self):
        self.anim_f += 0.1
        alpha = (math.sin(self.anim_f) + 1) / 2
        color = self.colors["yellow"] if self.is_syncing else self.colors["green"]
        self.canvas.itemconfig(self.status_dot, fill=color)
        self.root.after(50, self.animate)

    def start_move(self, event): self.x, self.y = event.x, event.y
    def do_move(self, event):
        self.root.geometry(f"+{self.root.winfo_x()+(event.x-self.x)}+{self.root.winfo_y()+(event.y-self.y)}")

    def quit_app(self):
        if HAS_TRAY and hasattr(self, "tray_icon"):
            self.tray_icon.stop()
        self.root.quit()
        sys.exit()

if __name__ == "__main__":
    root = tk.Tk()
    app = SerruchoPremiumWidget(root)
    root.mainloop()
