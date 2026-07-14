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
# Se intenta leer de config.py (que a su vez lee .env) para no desincronizar
# el widget si se rota la anon key. Si config.py falla o deja valores vacíos,
# se cae a los valores hardcodeados como respaldo (el widget nunca debe morir
# por esto: es la cara visible del sistema).
try:
    from config import SUPABASE_REST_URL, SUPABASE_ANON_KEY
    if not SUPABASE_REST_URL or not SUPABASE_ANON_KEY:
        raise ValueError("config.py devolvió valores vacíos")
except Exception:
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
# Se difiere al bloque __main__ para permitir la importación en tests sin interrumpir


def log_widget_error(msg):
    """Escribe en widget_error.log con rotación (sin conexión escribe cada 15s y crecía sin límite)."""
    try:
        base_dir = os.path.dirname(os.path.abspath(__file__))
        p = os.path.join(base_dir, "widget_error.log")
        if os.path.exists(p) and os.path.getsize(p) > 2 * 1024 * 1024:
            bak = p + ".1"
            if os.path.exists(bak): os.remove(bak)
            os.rename(p, bak)
        with open(p, "a", encoding="utf-8") as f:
            f.write(f"[{datetime.now()}] {msg}\n")
    except: pass

class SerruchoPremiumWidget:
    def __init__(self, root):
        self.root = root
        self.root.title("Serrucho Monitor")
        self.width = 310
        self.height_full = 335
        self.height_compact = 230
        self.integrity_visible = True
        self.waha_alert_shown = False
        
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
        
        # Indicador independiente de WhatsApp (WAHA)
        self.waha_dot = self.canvas.create_oval(198, 17, 208, 27, fill=self.colors["green"], outline="")
        self.canvas.create_text(188, 22, text="WA", fill=self.colors["subtext"], font=("Inter", 8, "bold"), anchor="e", tags="waha_label")

        self.status_dot = self.canvas.create_oval(260, 17, 270, 27, fill=self.colors["green"], outline="")
        # Anillo exterior del status_dot (se usa para drive/monitor status)
        self.status_ring = self.canvas.create_oval(258, 15, 272, 29, outline=self.colors["green"], width=1, state="hidden")
        
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
        
        # Botón Calculadora (%) con Estilo iOS
        self.calc_btn_bg = self.draw_rounded_rect(225, 10, 250, 35, 8, self.colors["card"], tags="calc_btn")
        self.calc_btn_txt = self.canvas.create_text(237, 22, text="%", fill=self.colors["blue"], font=("Inter", 11, "bold"), tags="calc_btn")
        
        # Efectos Hover y Clic
        self.canvas.tag_bind("calc_btn", "<Enter>", lambda e: self.canvas.itemconfig(self.calc_btn_bg, fill="#3A3A3C"))
        self.canvas.tag_bind("calc_btn", "<Leave>", lambda e: self.canvas.itemconfig(self.calc_btn_bg, fill=self.colors["card"]))
        self.canvas.tag_bind("calc_btn", "<Button-1>", lambda e: self.open_calculator())

        # Spinner de Carga (oculto por defecto)
        self.spinner = self.canvas.create_arc(257, 14, 273, 30, start=0, extent=60, outline=self.colors["blue"], width=2, style="arc", state="hidden")

        # Estado
        self.status_label = self.canvas.create_text(25, 50, text="Sistema Activo", fill=self.colors["text"], font=("Inter", 10, "bold"), anchor="w")
        self.detail_label = self.canvas.create_text(25, 68, text="Monitoreando archivos...", fill=self.colors["subtext"], font=("Inter", 8), anchor="w")

        # --- Switch de Writeback (estilo iOS) ---
        self.settings_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "writeback_settings.json")
        self.load_writeback_setting()
        
        self.wb_animation_running = False
        self.wb_hovered = False
        
        self.wb_text_label = self.canvas.create_text(
            235, 60, 
            text="Writeback", 
            fill="#FFFFFF" if self.writeback_enabled else self.colors["subtext"], 
            font=("Inter", 8, "bold"), 
            anchor="e", 
            tags="wb_toggle"
        )
        
        # Generate points for a smooth pill shape (switch background)
        pill_points = []
        steps = 16
        for i in range(steps + 1):
            angle = -math.pi / 2.0 + (math.pi * i / steps)
            x = 275 + 10 * math.cos(angle)
            y = 60 + 10 * math.sin(angle)
            pill_points.extend([x, y])
        for i in range(steps + 1):
            angle = math.pi / 2.0 + (math.pi * i / steps)
            x = 255 + 10 * math.cos(angle)
            y = 60 + 10 * math.sin(angle)
            pill_points.extend([x, y])

        self.wb_switch_bg = self.canvas.create_polygon(
            pill_points,
            fill=self.colors["green"] if self.writeback_enabled else "#3A3A3C",
            outline="",
            tags="wb_toggle"
        )
        
        kx = 275 if self.writeback_enabled else 255
        self.wb_switch_knob = self.canvas.create_oval(
            kx-8, 60-8, kx+8, 60+8, 
            fill="#FFFFFF", 
            outline="", 
            width=0,
            tags="wb_toggle"
        )
        self.canvas.tag_bind("wb_toggle", "<Button-1>", lambda e: self.toggle_writeback())
        self.canvas.tag_bind("wb_toggle", "<Enter>", lambda e: self.on_wb_hover(True))
        self.canvas.tag_bind("wb_toggle", "<Leave>", lambda e: self.on_wb_hover(False))

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
        self.load_calc_settings()
        self.animate()
        self.update_loop()
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
        base_dir = os.path.dirname(os.path.abspath(__file__))
        syncs = ["last_sync.json", "ventas_last_sync.json"]
        max_ts = 0
        for f in syncs:
            p = os.path.join(base_dir, f)
            if os.path.exists(p):
                try:
                    with open(p, "r") as fh:
                        data = json.load(fh)
                        if isinstance(data, dict):
                            ts = data.get("timestamp", 0)
                            if ts > max_ts:
                                max_ts = ts
                except Exception:
                    pass
        try:
            if max_ts > 0:
                now_str = datetime.fromtimestamp(max_ts).strftime("%d/%m %H:%M:%S")
                self.canvas.itemconfig(self.sync_time_label, text=f"Último Sync: {now_str}")
                self.last_synced_at = max_ts
            else:
                self.canvas.itemconfig(self.sync_time_label, text="Último Sync: Sin datos")
                self.last_synced_at = time.time()
        except Exception:
            self.last_synced_at = time.time()

    def load_writeback_setting(self):
        self.writeback_enabled = True
        try:
            if os.path.exists(self.settings_path):
                with open(self.settings_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    self.writeback_enabled = data.get("enabled", True)
        except Exception as e:
            log_widget_error(f"Error cargando writeback_settings: {repr(e)}")

    def save_writeback_setting(self):
        try:
            with open(self.settings_path, "w", encoding="utf-8") as f:
                json.dump({"enabled": self.writeback_enabled}, f, indent=2)
        except Exception as e:
            log_widget_error(f"Error guardando writeback_settings: {repr(e)}")

    def interpolate_color(self, color_start, color_end, t):
        def hex_to_rgb(hex_str):
            hex_str = hex_str.lstrip('#')
            return tuple(int(hex_str[i:i+2], 16) for i in (0, 2, 4))
        
        def rgb_to_hex(rgb):
            return '#{:02x}{:02x}{:02x}'.format(int(rgb[0]), int(rgb[1]), int(rgb[2]))

        rgb1 = hex_to_rgb(color_start)
        rgb2 = hex_to_rgb(color_end)
        
        r = rgb1[0] + (rgb2[0] - rgb1[0]) * t
        g = rgb1[1] + (rgb2[1] - rgb1[1]) * t
        b = rgb1[2] + (rgb2[2] - rgb1[2]) * t
        
        return rgb_to_hex((r, g, b))

    def update_wb_appearance(self):
        if self.wb_animation_running:
            return
        
        if self.writeback_enabled:
            bg_color = "#3AE359" if self.wb_hovered else self.colors["green"]
            text_color = "#FFFFFF"
            kx = 275
        else:
            bg_color = "#4A4A4C" if self.wb_hovered else "#3A3A3C"
            text_color = self.colors["subtext"]
            kx = 255
            
        self.canvas.itemconfig(self.wb_switch_bg, fill=bg_color)
        self.canvas.itemconfig(self.wb_text_label, fill=text_color)
        self.canvas.coords(self.wb_switch_knob, kx-8, 60-8, kx+8, 60+8)

    def on_wb_hover(self, hovered):
        self.wb_hovered = hovered
        self.update_wb_appearance()

    def animate_toggle(self, start_time, duration=0.18):
        elapsed = time.time() - start_time
        t = min(1.0, elapsed / duration)
        t_eased = t * (2 - t) # ease-out-quad
        
        current_x = self.x_start + (self.x_end - self.x_start) * t_eased
        current_color = self.interpolate_color(self.c_start, self.c_end, t_eased)
        
        self.canvas.itemconfig(self.wb_switch_bg, fill=current_color)
        self.canvas.coords(self.wb_switch_knob, current_x-8, 60-8, current_x+8, 60+8)
        
        if t < 1.0:
            self.root.after(15, lambda: self.animate_toggle(start_time, duration))
        else:
            self.wb_animation_running = False
            self.update_wb_appearance()

    def toggle_writeback(self):
        if self.wb_animation_running:
            return
            
        self.writeback_enabled = not self.writeback_enabled
        self.save_writeback_setting()
        
        # Configurar animación
        self.wb_animation_running = True
        self.x_start = 255 if self.writeback_enabled else 275
        self.x_end = 275 if self.writeback_enabled else 255
        self.c_start = "#3A3A3C" if self.writeback_enabled else self.colors["green"]
        self.c_end = self.colors["green"] if self.writeback_enabled else "#3A3A3C"
        
        # Cambiar el color de la etiqueta de texto inmediatamente para que se sienta responsivo
        text_color = "#FFFFFF" if self.writeback_enabled else self.colors["subtext"]
        self.canvas.itemconfig(self.wb_text_label, fill=text_color)
        
        self.animate_toggle(time.time(), duration=0.18)

    def load_calc_settings(self):
        self.last_discount = 0.0
        self.last_sale_percent = 30.0
        self.calc_history = []
        try:
            base_dir = os.path.dirname(os.path.abspath(__file__))
            p = os.path.join(base_dir, "calc_settings.json")
            if os.path.exists(p):
                with open(p, "r") as fh:
                    data = json.load(fh)
                    self.last_discount = data.get("last_discount", 0.0)
                    self.last_sale_percent = data.get("last_sale_percent", 30.0)
                    self.calc_history = data.get("history", [])
        except: pass

    def save_calc_settings(self, val):
        self.last_discount = val
        # Actualizar historial: nuevo valor al principio, eliminar duplicados, máximo 5
        if val > 0:
            if val in self.calc_history: self.calc_history.remove(val)
            self.calc_history.insert(0, val)
            self.calc_history = self.calc_history[:5]
            
        try:
            base_dir = os.path.dirname(os.path.abspath(__file__))
            p = os.path.join(base_dir, "calc_settings.json")
            with open(p, "w") as fh:
                json.dump({
                    "last_discount": self.last_discount,
                    "last_sale_percent": getattr(self, "last_sale_percent", 30.0),
                    "history": self.calc_history
                }, fh)
        except: pass

    def save_sale_settings(self, val):
        self.last_sale_percent = val
        try:
            base_dir = os.path.dirname(os.path.abspath(__file__))
            p = os.path.join(base_dir, "calc_settings.json")
            with open(p, "w") as fh:
                json.dump({
                    "last_discount": self.last_discount,
                    "last_sale_percent": self.last_sale_percent,
                    "history": self.calc_history
                }, fh)
        except: pass

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

    def verify_loop(self):
        self._verify_running = True
        def task():
            while self._verify_running:
                try:
                    req = urllib.request.Request("http://localhost:5000/api/v1/sync/status")
                    with urllib.request.urlopen(req, timeout=10) as resp:
                        data = json.loads(resp.read().decode())
                        backend_syncing = data.get("is_syncing", False)
                        if not getattr(self, "manual_sync_trigger", False):
                            self.is_syncing = backend_syncing
                        self.root.after(0, lambda d=data: self._update_ui_full(d))
                except: pass
                time.sleep(3 if self.is_syncing else 15)
        t = threading.Thread(target=task, daemon=True)
        t.start()

    def _update_ui_full(self, data):
        self.update_integrity_ui(data.get("entities", {}))
        last_mon = data.get("last_monitor", "--/-- --:--")
        self.canvas.itemconfig(self.check_time_label, text=f"Último Monitoreo: {last_mon}")
        if not self.is_syncing:
            self.load_last_sync_time()

    def draw_rounded_rect(self, x1, y1, x2, y2, r, color, tags=""):
        p = self.get_rounded_points(x1, y1, x2, y2, r)
        return self.canvas.create_polygon(p, smooth=True, fill=color, tags=tags)

    def trigger_sync_flow(self):
        if self.is_syncing: return
        self.is_syncing = True
        self.manual_sync_trigger = True
        
        self.canvas.itemconfig(self.btn_bg, fill="#3A3A3C")
        self.canvas.itemconfig(self.btn_text, text="Sincronizando...", fill="#8E8E93")
        self.canvas.itemconfig(self.integrity_card_bg, fill="#1C1C1E") 
        for lbl in self.integrity_labels.values():
            self.canvas.itemconfig(lbl, text="Actualizando...", fill=self.colors["subtext"])
        
        def run():
            try:
                req = urllib.request.Request("http://localhost:5000/api/v1/sync/run", method="POST")
                with urllib.request.urlopen(req, timeout=10) as resp: pass
            except: pass
            time.sleep(2)
            self.manual_sync_trigger = False
            self.last_synced_at = time.time()
            
        threading.Thread(target=run, daemon=True).start()

    def force_verify(self):
        """Ejecuta una verificación de integridad fuera del loop normal."""
        try:
            req = urllib.request.Request("http://localhost:5000/api/v1/sync/status")
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read().decode())
                self.update_integrity_ui(data.get("entities", {}))
        except: pass

    def reset_ui(self):
        self.canvas.itemconfig(self.btn_bg, fill=self.colors["blue"])
        self.canvas.itemconfig(self.btn_text, text="Sincronizar Ahora", fill="#FFFFFF")
        self.canvas.itemconfig(self.detail_label, text="Datos al día ✓")
        self.canvas.itemconfig(self.integrity_ui_bg, fill=self.colors["card"])
        now_str = datetime.now().strftime("%d/%m %H:%M:%S")
        self.canvas.itemconfig(self.sync_time_label, text=f"Último Sync: {now_str}")
        self.root.after(3000, lambda: self.canvas.itemconfig(self.detail_label, text="Monitoreando archivos..."))

    def update_integrity_ui(self, entities):
        for key, info in entities.items():
            if key in self.integrity_labels:
                local, cloud, ok = info.get("local", 0), info.get("cloud", -1), info.get("ok", False)
                if cloud < 0: txt, color = "Error Nube", self.colors["red"]
                elif ok: txt, color = f"{local:,} ✓", self.colors["green"]
                else: txt, color = f"{local:,} | {cloud:,}", self.colors["yellow"]
                lbl = self.integrity_labels[key]
                self.canvas.itemconfig(lbl, text=txt, fill=color)

    def update_loop(self):
        def task():
            while True:
                # 1. Obtener tasas de Supabase (aislado)
                try:
                    url = f"{SUPABASE_REST_URL}/rest/v1/tazas?nombre=eq.actual&limit=1"
                    headers = {"apikey": SUPABASE_ANON_KEY, "Authorization": f"Bearer {SUPABASE_ANON_KEY}"}
                    req = urllib.request.Request(url, headers=headers)
                    with urllib.request.urlopen(req, timeout=5) as resp:
                        data = json.loads(resp.read().decode())
                        if data:
                            bcv, bnb = data[0].get("bcv_usd", 0), data[0].get("binance_p2p", 0)
                            self.root.after(0, lambda bcv=bcv, bnb=bnb: self._update_rates_ui(bcv, bnb))
                except Exception as e:
                    try:
                        self.root.after(0, lambda: self.canvas.itemconfig(self.diff_label, text="Brecha: --.--% (Sin conexión)"))
                        log_widget_error(f"Error tazas Supabase: {repr(e)}")
                    except: pass
                
                # 2. Obtener estado de la API Local (aislado)
                try:
                    h_req = urllib.request.Request("http://localhost:5000/health")
                    with urllib.request.urlopen(h_req, timeout=5) as h_resp:
                        h_data = json.loads(h_resp.read().decode())
                        self.root.after(0, lambda d=h_data: self._update_health_ui(d))
                        self._health_failures = 0
                except Exception as e:
                    self.root.after(0, lambda: self.canvas.itemconfig(self.status_ring, state="normal", outline=self.colors["red"]))
                    self.root.after(0, lambda: self.canvas.itemconfig(self.detail_label, text="⚠️ API local no responde — reiniciando..."))
                    log_widget_error(f"Error API local: {repr(e)}")
                
                time.sleep(15)
        threading.Thread(target=task, daemon=True).start()

    def _update_rates_ui(self, bcv, bnb):
        try:
            self.canvas.itemconfig(self.rate_label, text=f"BCV: {bcv:,.2f} | BNB: {bnb:,.2f}")
            if bcv > 0:
                diff = ((bnb / bcv) - 1) * 100
                self.canvas.itemconfig(self.diff_label, text=f"Brecha: +{diff:.2f}%")
        except: pass

    def _update_health_ui(self, h_data):
        try:
            checks = h_data.get("checks", {})
            drive_ok = checks.get("drive_h", {}).get("ok", False)
            mon_ok = checks.get("monitor", {}).get("ok", False)
            sup_ok = checks.get("supabase", {}).get("ok", False)
            
            # WAHA Check
            waha_check = checks.get("waha", {})
            waha_ok = waha_check.get("ok", False)
            waha_status = waha_check.get("status", "UNKNOWN")
            
            # Mapear color del dot de WAHA independientemente
            waha_color = self.colors["green"] if waha_ok else self.colors["red"]
            self.canvas.itemconfig(self.waha_dot, fill=waha_color)
            
            # Alerta emergente del sistema (Popup no bloqueante) si se cae
            if not waha_ok:
                if not self.waha_alert_shown:
                    self.waha_alert_shown = True
                    if waha_status == "SCAN_QR_CODE":
                        title_box = "Vincular WhatsApp (El Serrucho)"
                        msg_box = "La sesión de WhatsApp del bot se cerró.\n\nPor favor, abre el panel de WAHA (http://localhost:3000) e inicia sesión con admin_serrucho para escanear el código QR."
                    elif waha_status == "FAILED":
                        title_box = "Sesión Fallida de WhatsApp"
                        msg_box = "La sesión de WhatsApp (WAHA) falló.\n\nRevisa el panel de control de WAHA para reiniciar la sesión o re-vincular."
                    elif waha_status == "OFFLINE":
                        title_box = "Servidor WhatsApp Offline"
                        msg_box = "El servidor de WhatsApp (WAHA) no responde.\n\nComprueba que Docker Desktop esté en ejecución y los contenedores estén activos."
                    else:
                        title_box = "WhatsApp Desconectado"
                        msg_box = f"La sesión de WhatsApp del bot no está activa (Estado: {waha_status}).\n\nPor favor, verifica la conexión."
                    
                    def show_popup():
                        try:
                            messagebox.showwarning(title_box, msg_box)
                        except: pass
                    
                    threading.Thread(target=show_popup, daemon=True).start()
            else:
                self.waha_alert_shown = False

            # El anillo del backend/sistema mantiene sus propios checks originales
            ring_color = self.colors["green"] if (drive_ok and mon_ok and sup_ok) else self.colors["red"]
            self.canvas.itemconfig(self.status_ring, state="normal", outline=ring_color)
            
            # Prioridad de mensajes en el label de detalle
            if not waha_ok:
                if waha_status == "SCAN_QR_CODE":
                    self.canvas.itemconfig(self.detail_label, text="⚠️ WhatsApp: Escanear QR en panel")
                elif waha_status == "FAILED":
                    self.canvas.itemconfig(self.detail_label, text="⚠️ WhatsApp: Sesión fallida")
                elif waha_status == "OFFLINE":
                    self.canvas.itemconfig(self.detail_label, text="⚠️ WhatsApp: Servidor offline")
                else:
                    self.canvas.itemconfig(self.detail_label, text=f"⚠️ WhatsApp: Desconectado ({waha_status})")
            elif not sup_ok:
                self.canvas.itemconfig(self.detail_label, text="⚠️ Supabase no responde")
            elif not drive_ok:
                self.canvas.itemconfig(self.detail_label, text="⚠️ Unidad H: desconectada")
            elif not mon_ok:
                self.canvas.itemconfig(self.detail_label, text="⚠️ Monitor caído — reiniciar backend")
            else:
                self.canvas.itemconfig(self.detail_label, text="Monitoreando archivos...")
        except: pass

    def animate(self):
        self.anim_f += 2
        
        pulse = (math.sin(self.anim_f / 5) + 1) / 2
        self.canvas.coords(self.status_dot, 260-pulse, 17-pulse, 270+pulse, 27+pulse)
        
        if self.is_syncing:
            self.canvas.itemconfig(self.spinner, state="normal", start=self.anim_f % 360, outline=self.colors["blue"])
            color = self.colors["yellow"]
        else:
            self.canvas.itemconfig(self.spinner, state="hidden")
            color = self.colors["green"]
            
        self.canvas.itemconfig(self.status_dot, fill=color)
        self.root.after(100, self.animate)

    def start_move(self, event): self.x, self.y = event.x, event.y
    def do_move(self, event): self.root.geometry(f"+{self.root.winfo_x()+(event.x-self.x)}+{self.root.winfo_y()+(event.y-self.y)}")
    def quit_app(self):
        if HAS_TRAY and hasattr(self, "tray_icon"): self.tray_icon.stop()
        self.root.quit(); sys.exit()

    def open_calculator(self):
        if hasattr(self, "calc_win") and self.calc_win.winfo_exists():
            self.calc_win.lift()
            return
        self.calc_win = tk.Toplevel(self.root)
        DiscountCalculator(self.calc_win, self.colors, self.last_discount, self.last_sale_percent, self.calc_history, self.save_calc_settings, self.save_sale_settings)

class DiscountCalculator:
    def __init__(self, root, colors, initial_discount, initial_sale_percent, history, save_callback, save_sale_callback):
        self.root = root
        self.colors = colors
        self.history = history
        self.save_callback = save_callback
        self.save_sale_callback = save_sale_callback
        self.history_menu_win = None
        self.calc_mode = "sub"
        self.root.title("Calculadora de Descuento")
        self.width, self.height = 300, 260
        
        # Estética iOS
        self.root.overrideredirect(True)
        self.root.attributes("-topmost", True)
        self.root.attributes("-transparentcolor", "#010101")
        self.root.config(bg="#010101")
        
        # Posicionar cerca del widget principal
        parent_x = self.root.master.winfo_x()
        parent_y = self.root.master.winfo_y()
        self.root.geometry(f"{self.width}x{self.height}+{parent_x - 20}+{parent_y + 50}")
        
        self.canvas = tk.Canvas(root, width=self.width, height=self.height, bg="#010101", highlightthickness=0, bd=0)
        self.canvas.pack()
        
        # Fondo
        self.draw_rounded_rect(0, 0, self.width, self.height, 24, self.colors["bg"], tags="drag")
        
        # Título y Cerrar
        self.canvas.create_text(20, 25, text="Calculadora Proovedor", fill=self.colors["text"], font=("Inter", 10, "bold"), anchor="w", tags="drag")
        self.canvas.create_text(self.width-20, 25, text="✕", fill=self.colors["subtext"], font=("Inter", 10, "bold"), tags="close")
        self.canvas.tag_bind("close", "<Button-1>", lambda e: self.root.destroy())
        
        # Fila 1: Inputs
        self.canvas.create_text(20, 55, text="PRECIO", fill=self.colors["subtext"], font=("Inter", 7, "bold"), anchor="w")
        self.price_entry = self.create_entry(20, 68, 145, 98)
        
        self.canvas.create_text(155, 55, text="PORCENTAJE", fill=self.colors["subtext"], font=("Inter", 7, "bold"), anchor="w")
        
        # Segmented control toggle (- / +)
        self.mode_toggle_bg = self.draw_rounded_rect(225, 44, 280, 64, 9, "#2C2C2E", tags="mode_toggle")
        self.mode_indicator = self.draw_rounded_rect(227, 46, 252, 62, 8, self.colors["blue"], tags="mode_toggle")
        self.mode_sub_txt = self.canvas.create_text(239, 54, text="-", fill="#FFFFFF", font=("Inter", 10, "bold"), tags="mode_toggle")
        self.mode_add_txt = self.canvas.create_text(266, 54, text="+", fill=self.colors["subtext"], font=("Inter", 10, "bold"), tags="mode_toggle")
        self.canvas.tag_bind("mode_toggle", "<Button-1>", lambda e: self.toggle_mode())

        # Fondo completo del input de descuento
        self.draw_rounded_rect(155, 68, 280, 98, 8, self.colors["card"])
        # Widget Entry más corto para no tapar el chevron
        self.pct_entry = self.create_entry_widget(155, 68, 250, 98)
        self.pct_entry.insert(0, str(initial_discount) if initial_discount > 0 else "")
        
        # Chevron para Historial (ahora visible)
        self.draw_chevron(268, 83)
        
        # Fila 2: Precio con Descuento
        self.draw_rounded_rect(20, 115, 280, 165, 12, self.colors["card"])
        self.cost_title_label = self.canvas.create_text(35, 130, text="COSTO NETO (-%)", fill=self.colors["subtext"], font=("Inter", 7, "bold"), anchor="w")
        self.res_label = self.canvas.create_text(35, 148, text="0.00", fill=self.colors["text"], font=("Inter", 14, "bold"), anchor="w")
        
        # Botón Copiar Costo (Personalizado y Alineado)
        self.draw_copy_icon(245, 132, self.res_label)

        # Fila 3: Precio Venta (+Editable%)
        self.draw_rounded_rect(20, 180, 280, 240, 12, self.colors["card"])
        
        # Elementos interactivos del porcentaje de venta
        self.canvas.create_text(35, 195, text="PRECIO VENTA (+", fill=self.colors["green"], font=("Inter", 7, "bold"), anchor="w")
        
        # Entrada de porcentaje de venta con fondo oscuro redondeado
        self.draw_rounded_rect(122, 185, 162, 205, 5, self.colors["bg"])
        self.sale_pct_entry = tk.Entry(self.root, bg=self.colors["bg"], fg="#FFFFFF", font=("Inter", 9), borderwidth=0, highlightthickness=0, insertbackground="white", justify="center")
        self.canvas.create_window(142, 195, window=self.sale_pct_entry, width=32, height=16)
        self.sale_pct_entry.insert(0, str(initial_sale_percent) if initial_sale_percent > 0 else "30.0")
        
        self.canvas.create_text(166, 195, text="%)", fill=self.colors["green"], font=("Inter", 7, "bold"), anchor="w")
        
        self.profit_label = self.canvas.create_text(35, 218, text="0.00", fill=self.colors["text"], font=("Inter", 16, "bold"), anchor="w")
        
        # Botones de Acción (Alineados a la derecha)
        self.round_btn_bg = self.canvas.create_oval(205, 203, 230, 228, outline=self.colors["blue"], width=1.5)
        self.round_btn_txt = self.canvas.create_text(218, 215, text="R", fill=self.colors["blue"], font=("Inter", 10, "bold"))
        self.canvas.tag_bind(self.round_btn_bg, "<Button-1>", lambda e: self.round_up())
        self.canvas.tag_bind(self.round_btn_txt, "<Button-1>", lambda e: self.round_up())
        
        self.draw_copy_icon(245, 207, self.profit_label)

        # Eventos
        self.price_entry.bind("<KeyRelease>", lambda e: self.calculate())
        self.pct_entry.bind("<KeyRelease>", lambda e: self.calculate())
        self.sale_pct_entry.bind("<KeyRelease>", lambda e: self.calculate())
        self.canvas.tag_bind("drag", "<ButtonPress-1>", self.start_move)
        self.canvas.tag_bind("drag", "<B1-Motion>", self.do_move)
        
        # Focus inicial
        self.price_entry.focus_set()

    def draw_chevron(self, x, y):
        tag = "chevron_btn"
        # Chevron estilo iOS más grande y apuntando abajo
        self.canvas.create_line(x-6, y-3, x, y+3, fill=self.colors["blue"], width=2, tags=tag)
        self.canvas.create_line(x, y+3, x+6, y-3, fill=self.colors["blue"], width=2, tags=tag)
        self.canvas.tag_bind(tag, "<Button-1>", lambda e: self.show_history_menu())

    def show_history_menu(self):
        if not self.history: return
        
        # Lógica de Toggle
        if self.history_menu_win and self.history_menu_win.winfo_exists():
            self.history_menu_win.destroy()
            self.history_menu_win = None
            return
            
        self.history_menu_win = tk.Toplevel(self.root)
        self.history_menu_win.overrideredirect(True)
        self.history_menu_win.attributes("-topmost", True)
        self.history_menu_win.attributes("-transparentcolor", "#010101")
        self.history_menu_win.config(bg="#010101")
        
        w, h_item = 125, 25
        h = len(self.history) * h_item + 10
        
        canvas = tk.Canvas(self.history_menu_win, width=w, height=h, bg="#010101", highlightthickness=0, bd=0)
        canvas.pack()
        
        self.draw_rounded_rect_custom(canvas, 0, 0, w, h, 12, self.colors["card"])
        
        def select(val):
            self.pct_entry.delete(0, tk.END)
            self.pct_entry.insert(0, str(val))
            self.calculate()
            self.history_menu_win.destroy()
            self.history_menu_win = None

        for i, val in enumerate(self.history):
            y_item = 5 + i * h_item
            rect = canvas.create_rectangle(5, y_item, w-5, y_item+h_item, fill="", outline="", tags=f"item_{i}")
            txt = canvas.create_text(w/2, y_item+h_item/2, text=f"{val}%", fill=self.colors["text"], font=("Inter", 9), tags=f"item_{i}")
            canvas.tag_bind(f"item_{i}", "<Enter>", lambda e, r=rect: canvas.itemconfig(r, fill="#3A3A3C"))
            canvas.tag_bind(f"item_{i}", "<Leave>", lambda e, r=rect: canvas.itemconfig(r, fill=""))
            canvas.tag_bind(f"item_{i}", "<Button-1>", lambda e, v=val: select(v))

        self.update_menu_position()

    def update_menu_position(self):
        if self.history_menu_win and self.history_menu_win.winfo_exists():
            x = self.root.winfo_x() + 155
            y = self.root.winfo_y() + 100
            self.history_menu_win.geometry(f"+{x}+{y}")

    def get_rounded_points(self, x1, y1, x2, y2, r):
        return [x1+r, y1, x1+r, y1, x2-r, y1, x2-r, y1, x2, y1, x2, y1+r, x2, y1+r, x2, y2-r, x2, y2-r, x2, y2, x2-r, y2, x2-r, y2, x1+r, y2, x1+r, y2, x1, y2, x1, y2-r, x1, y2-r, x1, y1+r, x1, y1+r, x1, y1]

    def toggle_mode(self):
        if self.calc_mode == "sub":
            self.calc_mode = "add"
            new_pts = self.get_rounded_points(253, 46, 278, 62, 8)
            self.canvas.coords(self.mode_indicator, *new_pts)
            self.canvas.itemconfig(self.mode_sub_txt, fill=self.colors["subtext"])
            self.canvas.itemconfig(self.mode_add_txt, fill="#FFFFFF")
            self.canvas.itemconfig(self.cost_title_label, text="COSTO NETO (+%)")
        else:
            self.calc_mode = "sub"
            new_pts = self.get_rounded_points(227, 46, 252, 62, 8)
            self.canvas.coords(self.mode_indicator, *new_pts)
            self.canvas.itemconfig(self.mode_sub_txt, fill="#FFFFFF")
            self.canvas.itemconfig(self.mode_add_txt, fill=self.colors["subtext"])
            self.canvas.itemconfig(self.cost_title_label, text="COSTO NETO (-%)")
        self.calculate()

    def draw_rounded_rect_custom(self, canvas, x1, y1, x2, y2, r, color):
        def get_pts(x1, y1, x2, y2, r):
            return [x1+r, y1, x1+r, y1, x2-r, y1, x2-r, y1, x2, y1, x2, y1+r, x2, y1+r, x2, y2-r, x2, y2-r, x2, y2, x2-r, y2, x2-r, y2, x1+r, y2, x1+r, y2, x1, y2, x1, y2-r, x1, y2-r, x1, y1+r, x1, y1+r, x1, y1]
        return canvas.create_polygon(get_pts(x1, y1, x2, y2, r), smooth=True, fill=color)

    def draw_copy_icon(self, x, y, label_id):
        tag = f"copy_{label_id}"
        # Área de colisión (hitbox) invisible de 24x24 con el color de la tarjeta para capturar clics de forma confiable
        self.canvas.create_rectangle(x-4, y-4, x+20, y+20, fill=self.colors["card"], outline="", tags=tag)
        # Dibujamos dos rectángulos superpuestos estilo "outline"
        self.draw_rounded_rect_outline(x, y+4, x+12, y+16, 3, self.colors["subtext"], tags=tag) # Fondo
        self.draw_rounded_rect_outline(x+4, y, x+16, y+12, 3, self.colors["blue"], tags=tag) # Frente
        self.canvas.tag_bind(tag, "<Button-1>", lambda e: self.copy_to_clipboard(label_id))

    def draw_rounded_rect_outline(self, x1, y1, x2, y2, r, color, tags=""):
        def get_pts(x1, y1, x2, y2, r):
            return [x1+r, y1, x1+r, y1, x2-r, y1, x2-r, y1, x2, y1, x2, y1+r, x2, y1+r, x2, y2-r, x2, y2-r, x2, y2, x2-r, y2, x2-r, y2, x1+r, y2, x1+r, y2, x1, y2, x1, y2-r, x1, y2-r, x1, y1+r, x1, y1+r, x1, y1]
        return self.canvas.create_polygon(get_pts(x1, y1, x2, y2, r), smooth=True, fill="", outline=color, width=1.5, tags=tags)

    def create_entry(self, x1, y1, x2, y2):
        self.draw_rounded_rect(x1, y1, x2, y2, 8, self.colors["card"])
        return self.create_entry_widget(x1, y1, x2, y2)

    def create_entry_widget(self, x1, y1, x2, y2):
        entry = tk.Entry(self.root, bg=self.colors["card"], fg="#FFFFFF", font=("Inter", 11), borderwidth=0, highlightthickness=0, insertbackground="white")
        self.canvas.create_window((x1+x2)/2, (y1+y2)/2, window=entry, width=(x2-x1)-15, height=(y2-y1)-5)
        return entry

    def calculate(self):
        try:
            p_val = self.price_entry.get().replace(",", ".")
            d_val = self.pct_entry.get().replace(",", ".")
            s_val = self.sale_pct_entry.get().replace(",", ".")
            price = float(p_val) if p_val else 0.0
            pct = float(d_val) if d_val else 0.0
            sale_pct = float(s_val) if s_val else 0.0
            
            if self.calc_mode == "sub":
                costo_neto = price * (1 - (pct / 100))
            else:
                costo_neto = price * (1 + (pct / 100))
            precio_venta = costo_neto * (1 + (sale_pct / 100))
            
            self.canvas.itemconfig(self.res_label, text=f"{costo_neto:,.2f}")
            self.canvas.itemconfig(self.profit_label, text=f"{precio_venta:,.2f}")
            
            if pct > 0: self.save_callback(pct)
            if sale_pct >= 0: self.save_sale_callback(sale_pct)
        except:
            self.canvas.itemconfig(self.res_label, text="0.00")
            self.canvas.itemconfig(self.profit_label, text="0.00")

    def round_up(self):
        try:
            val = float(self.canvas.itemcget(self.profit_label, "text").replace(",", ""))
            if val <= 0: return
            
            # Lógica de Redondeo Inteligente
            # .00 - .15 -> .00
            # .16 - .65 -> .50
            # .66 - .99 -> 1.00
            integer_part = int(val)
            decimal_part = val - integer_part
            
            if decimal_part <= 0.15:
                rounded = float(integer_part)
            elif decimal_part <= 0.65:
                rounded = integer_part + 0.5
            else:
                rounded = float(integer_part + 1)
                
            self.canvas.itemconfig(self.profit_label, text=f"{rounded:,.2f}")
        except: pass

    def copy_to_clipboard(self, label_id):
        try:
            text = self.canvas.itemcget(label_id, "text").replace(",", "")
            self.root.clipboard_clear()
            self.root.clipboard_append(text)
            # Feedback visual
            old_color = self.canvas.itemcget(label_id, "fill")
            self.canvas.itemconfig(label_id, fill=self.colors["green"])
            self.root.after(500, lambda: self.canvas.itemconfig(label_id, fill=old_color))
        except: pass

    def draw_rounded_rect(self, x1, y1, x2, y2, r, color, tags=""):
        def get_pts(x1, y1, x2, y2, r):
            return [x1+r, y1, x1+r, y1, x2-r, y1, x2-r, y1, x2, y1, x2, y1+r, x2, y1+r, x2, y2-r, x2, y2-r, x2, y2, x2-r, y2, x2-r, y2, x1+r, y2, x1+r, y2, x1, y2, x1, y2-r, x1, y2-r, x1, y1+r, x1, y1+r, x1, y1]
        return self.canvas.create_polygon(get_pts(x1, y1, x2, y2, r), smooth=True, fill=color, tags=tags)

    def start_move(self, event): self.x, self.y = event.x, event.y
    def do_move(self, event): 
        self.root.geometry(f"+{self.root.winfo_x()+(event.x-self.x)}+{self.root.winfo_y()+(event.y-self.y)}")
        self.update_menu_position()


if __name__ == "__main__":
    # --- Protección de Instancia Única ---
    import socket
    try:
        lock_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        lock_socket.bind(('127.0.0.1', 5006)) 
    except:
        sys.exit(0)

    root = tk.Tk()
    app = SerruchoPremiumWidget(root)
    root.mainloop()
