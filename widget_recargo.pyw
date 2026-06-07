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

# --- Configuración de Supabase (Copiada del Widget Original) ---
SUPABASE_REST_URL = "https://YOUR-PROJECT-REF.supabase.co"
SUPABASE_ANON_KEY = "REDACTED-JWT"

# --- Protección de Instancia Única en Puerto 5007 ---
try:
    lock_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    lock_socket.bind(('127.0.0.1', 5007))
except Exception:
    sys.exit(0)

class PriceRecargoWidget:
    def __init__(self, root):
        self.root = root
        self.root.title("Calculadora de Recargo")
        self.width = 330
        self.height = 120
        
        # Estética iOS 17 Premium Borderless
        self.root.overrideredirect(True)
        self.root.attributes("-topmost", True)
        self.root.attributes("-transparentcolor", "#010101")
        self.root.config(bg="#010101")
        
        # Ubicar en la esquina inferior derecha (exactamente en el recuadro rojo de la captura)
        screen_w = self.root.winfo_screenwidth()
        screen_h = self.root.winfo_screenheight()
        # Colocar a unos 20px del margen derecho y 115px del margen inferior (arriba de la botonera)
        x_pos = screen_w - self.width - 20
        y_pos = screen_h - self.height - 115
        self.root.geometry(f"{self.width}x{self.height}+{x_pos}+{y_pos}")
        
        # Paleta de colores premium iOS
        self.colors = {
            "bg": "#1C1C1E", 
            "card": "#2C2C2E",
            "green": "#32D74B", 
            "blue": "#0A84FF",
            "yellow": "#FFD60A", 
            "red": "#FF453A",
            "text": "#FFFFFF", 
            "subtext": "#8E8E93"
        }
        
        self.canvas = tk.Canvas(root, width=self.width, height=self.height, bg="#010101", highlightthickness=0, bd=0)
        self.canvas.pack()
        
        # Tasa BCV por defecto (se actualizará dinámicamente)
        self.bcv_rate = 0.0
        
        # Fondo Principal
        self.bg_rect = self.draw_rounded_rect(0, 0, self.width, self.height, 24, self.colors["bg"], tags="bg_layer")
        
        # Cabecera / Título
        self.canvas.create_text(38, 18, text="Precio a BS", fill=self.colors["text"], font=("Inter", 10, "bold"), anchor="w", tags="bg_layer")
        
        # Botón Cerrar
        self.canvas.create_text(self.width - 18, 18, text="✕", fill=self.colors["subtext"], font=("Inter", 10, "bold"), tags="close_btn")
        self.canvas.tag_bind("close_btn", "<Button-1>", lambda e: self.hide_to_tray())
        
        # Anillo pulsante y Dollar badge estilo iOS
        self.status_ring = self.canvas.create_oval(13, 8, 31, 26, outline=self.colors["blue"], width=1, tags="bg_layer")
        self.status_dot = self.canvas.create_oval(15, 10, 29, 24, fill=self.colors["blue"], outline="")
        self.canvas.create_text(22, 17, text="$", fill="#FFFFFF", font=("Inter", 8, "bold"))
        
        # Tasa BCV en cabecera
        self.rate_label = self.canvas.create_text(self.width - 45, 18, text="BCV: --.--", fill=self.colors["subtext"], font=("Inter", 8, "bold"), anchor="e", tags="bg_layer")
        
        # --- Columnas Izquierda (Entradas) ---
        # Precio Base
        self.canvas.create_text(15, 36, text="PRECIO BASE $", fill=self.colors["subtext"], font=("Inter", 7, "bold"), anchor="w", tags="bg_layer")
        self.price_entry = self.create_entry(15, 44, 145, 68)
        
        # Aumento %
        self.canvas.create_text(15, 78, text="% RECARGO", fill=self.colors["subtext"], font=("Inter", 7, "bold"), anchor="w", tags="bg_layer")
        self.pct_entry = self.create_entry(15, 86, 145, 110)
        
        # --- Columnas Derecha (Salidas) ---
        # Tarjeta USD ($)
        self.draw_rounded_rect(160, 38, 315, 70, 8, self.colors["card"], tags="bg_layer")
        self.canvas.create_text(170, 48, text="NUEVO PRECIO $", fill=self.colors["subtext"], font=("Inter", 7, "bold"), anchor="w")
        self.res_usd_label = self.canvas.create_text(170, 60, text="0.00", fill=self.colors["text"], font=("Inter", 11, "bold"), anchor="w")
        self.draw_copy_icon(295, 45, self.res_usd_label)
        
        # Tarjeta VES (Bs.)
        self.draw_rounded_rect(160, 78, 315, 110, 8, self.colors["card"], tags="bg_layer")
        self.canvas.create_text(170, 88, text="NUEVO PRECIO Bs.", fill=self.colors["green"], font=("Inter", 7, "bold"), anchor="w")
        self.res_ves_label = self.canvas.create_text(170, 100, text="0.00", fill=self.colors["text"], font=("Inter", 11, "bold"), anchor="w")
        self.draw_copy_icon(295, 85, self.res_ves_label)
        
        # Eventos para cálculos inmediatos al teclear
        self.price_entry.bind("<KeyRelease>", lambda e: self.calculate())
        self.pct_entry.bind("<KeyRelease>", lambda e: self.calculate())
        
        # Eventos para arrastrar el widget
        self.canvas.tag_bind("bg_layer", "<ButtonPress-1>", self.start_move)
        self.canvas.tag_bind("bg_layer", "<B1-Motion>", self.do_move)
        
        # Click derecho en la base para salir por completo
        self.root.bind("<Button-3>", lambda e: self.quit_app())
        
        # Inicialización
        self.anim_f = 0
        self.load_settings()
        self.pct_entry.insert(0, str(self.last_markup) if self.last_markup > 0 else "")
        self.price_entry.focus_set()
        
        # Forzar que la ventana siempre esté al frente de forma permanente
        self.keep_topmost()
        
        # Loops asíncronos
        self.animate()
        self.update_loop()
        if HAS_TRAY: threading.Thread(target=self.setup_tray, daemon=True).start()

    def get_rounded_points(self, x1, y1, x2, y2, r):
        return [
            x1+r, y1, x1+r, y1, 
            x2-r, y1, x2-r, y1, 
            x2, y1, 
            x2, y1+r, x2, y1+r, 
            x2, y2-r, x2, y2-r, 
            x2, y2, 
            x2-r, y2, x2-r, y2, 
            x1+r, y2, x1+r, y2, 
            x1, y2, 
            x1, y2-r, x1, y2-r, 
            x1, y1+r, x1, y1+r, 
            x1, y1
        ]

    def draw_rounded_rect(self, x1, y1, x2, y2, r, color, tags=""):
        p = self.get_rounded_points(x1, y1, x2, y2, r)
        return self.canvas.create_polygon(p, smooth=True, fill=color, tags=tags)

    def draw_rounded_rect_outline(self, x1, y1, x2, y2, r, color, tags=""):
        p = self.get_rounded_points(x1, y1, x2, y2, r)
        return self.canvas.create_polygon(p, smooth=True, fill="", outline=color, width=1.5, tags=tags)

    def create_entry(self, x1, y1, x2, y2):
        self.draw_rounded_rect(x1, y1, x2, y2, 6, self.colors["card"])
        entry = tk.Entry(self.root, bg=self.colors["card"], fg="#FFFFFF", font=("Inter", 10), borderwidth=0, highlightthickness=0, insertbackground="white")
        # Centrar el widget Entry en el rectángulo
        self.canvas.create_window((x1+x2)/2, (y1+y2)/2, window=entry, width=(x2-x1)-12, height=(y2-y1)-4)
        return entry

    def draw_copy_icon(self, x, y, label_id):
        tag = f"copy_{label_id}"
        # Hitbox invisible para interacción táctil/clic confiable
        self.canvas.create_rectangle(x-4, y-4, x+20, y+20, fill="", outline="", tags=tag)
        # Dos rectángulos superpuestos estilo "outline" iOS
        self.draw_rounded_rect_outline(x, y+4, x+12, y+16, 3, self.colors["subtext"], tags=tag)
        self.draw_rounded_rect_outline(x+4, y, x+16, y+12, 3, self.colors["blue"], tags=tag)
        self.canvas.tag_bind(tag, "<Button-1>", lambda e: self.copy_to_clipboard(label_id))

    def load_settings(self):
        self.last_markup = 0.0
        try:
            base_dir = os.path.dirname(os.path.abspath(__file__))
            p = os.path.join(base_dir, "calc_settings_usd.json")
            if os.path.exists(p):
                with open(p, "r") as fh:
                    data = json.load(fh)
                    self.last_markup = data.get("last_markup", 0.0)
        except Exception:
            pass

    def save_settings(self, val):
        self.last_markup = val
        try:
            base_dir = os.path.dirname(os.path.abspath(__file__))
            p = os.path.join(base_dir, "calc_settings_usd.json")
            with open(p, "w") as fh:
                json.dump({"last_markup": self.last_markup}, fh)
        except Exception:
            pass

    def calculate(self):
        try:
            p_val = self.price_entry.get().replace(",", ".")
            m_val = self.pct_entry.get().replace(",", ".")
            
            price = float(p_val) if p_val else 0.0
            markup = float(m_val) if m_val else 0.0
            
            new_price_usd = price * (1 + (markup / 100))
            new_price_ves = new_price_usd * self.bcv_rate
            
            self.canvas.itemconfig(self.res_usd_label, text=f"{new_price_usd:,.2f}")
            self.canvas.itemconfig(self.res_ves_label, text=f"{new_price_ves:,.2f}")
            
            # Guardar en caché asíncronamente si el porcentaje es válido
            if markup >= 0:
                self.save_settings(markup)
        except Exception:
            self.canvas.itemconfig(self.res_usd_label, text="0.00")
            self.canvas.itemconfig(self.res_ves_label, text="0.00")

    def copy_to_clipboard(self, label_id):
        try:
            text = self.canvas.itemcget(label_id, "text").replace(",", "")
            self.root.clipboard_clear()
            self.root.clipboard_append(text)
            
            # Feedback visual de éxito premium (se vuelve verde y regresa al color original)
            old_color = self.canvas.itemcget(label_id, "fill")
            self.canvas.itemconfig(label_id, fill=self.colors["green"])
            self.root.after(500, lambda: self.canvas.itemconfig(label_id, fill=old_color))
        except Exception:
            pass

    def update_loop(self):
        def task():
            while True:
                try:
                    url = f"{SUPABASE_REST_URL}/rest/v1/tazas?nombre=eq.actual&limit=1"
                    headers = {"apikey": SUPABASE_ANON_KEY, "Authorization": f"Bearer {SUPABASE_ANON_KEY}"}
                    req = urllib.request.Request(url, headers=headers)
                    with urllib.request.urlopen(req, timeout=5) as resp:
                        data = json.loads(resp.read().decode())
                        if data:
                            bcv = data[0].get("bcv_usd", 0)
                            self.root.after(0, lambda bcv=bcv: self._update_rates_ui(bcv))
                except Exception:
                    # En caso de desconexión, mostrar en rojo suave
                    self.root.after(0, lambda: self.canvas.itemconfig(self.status_ring, outline=self.colors["red"]))
                time.sleep(30)
        threading.Thread(target=task, daemon=True).start()

    def _update_rates_ui(self, bcv):
        try:
            self.bcv_rate = bcv
            self.canvas.itemconfig(self.rate_label, text=f"BCV: {bcv:,.2f}")
            self.canvas.itemconfig(self.status_ring, outline=self.colors["green"])
            self.calculate()
        except Exception:
            pass

    def animate(self):
        self.anim_f += 2
        
        # Animación de respiración/pulsación del anillo de status estilo iOS
        pulse = (math.sin(self.anim_f / 5) + 1) / 2
        self.canvas.coords(self.status_ring, 13-pulse, 8-pulse, 31+pulse, 26+pulse)
        
        self.root.after(100, self.animate)

    def start_move(self, event):
        self.x, self.y = event.x, event.y

    def do_move(self, event):
        self.root.geometry(f"+{self.root.winfo_x()+(event.x-self.x)}+{self.root.winfo_y()+(event.y-self.y)}")

    def setup_tray(self):
        try:
            base_dir = os.path.dirname(os.path.abspath(__file__))
            logo_path = os.path.join(base_dir, "assets", "logo.png")
            icon_img = Image.open(logo_path) if os.path.exists(logo_path) else Image.new('RGB', (64, 64), (10, 132, 255))
            menu = (item('Mostrar Calculadora', self.show_from_tray, default=True), item('Salir', self.quit_app))
            self.tray_icon = pystray.Icon("CalculadoraRecargo", icon_img, "Recargo de Precios", menu)
            self.tray_icon.run()
        except Exception:
            pass

    def hide_to_tray(self):
        if HAS_TRAY:
            self.root.withdraw()
        else:
            self.quit_app()

    def keep_topmost(self):
        try:
            self.root.attributes("-topmost", True)
            self.root.lift()
        except Exception:
            pass
        self.root.after(1000, self.keep_topmost)

    def show_from_tray(self):
        self.root.deiconify()
        self.root.attributes("-topmost", True)

    def quit_app(self):
        if HAS_TRAY and hasattr(self, "tray_icon"):
            try:
                self.tray_icon.stop()
            except Exception:
                pass
        self.root.quit()
        sys.exit()

if __name__ == "__main__":
    root = tk.Tk()
    app = PriceRecargoWidget(root)
    root.mainloop()
