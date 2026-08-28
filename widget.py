import tkinter as tk
import custom_dialogs
import urllib.request
import json
import threading
import math
import os
import sys
import socket
import time
from datetime import datetime, timezone
import requests
import config

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

# --- Configuración (Desde config.py) ---
SUPABASE_REST_URL = config.SUPABASE_REST_URL
SUPABASE_ANON_KEY = config.SUPABASE_ANON_KEY

HYBRID_PATHS = [
    config.RUTA_INVENTARIO,
    config.RUTA_PRECIOS,
    config.RUTA_EXISTENCIA,
    config.RUTA_VENTAS,
    config.RUTA_VENTAS_DETALLE,
    config.RUTA_CLIENTES
]

# --- Protección de Instancia Única ---
try:
    lock_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    lock_socket.bind(('127.0.0.1', 58231)) # Puerto nuevo para evitar bloqueos
except Exception as e:
    print(f"Error binding socket: {e}")
    sys.exit(0)

class HybridCloudWidget:
    def __init__(self, root):
        self.root = root
        self.root.title(f"{config.SAAS_NAME} - {config.BUSINESS_NAME}")
        self.width, self.height = 300, 200 # Compactado
        self.root.geometry(f"{self.width}x{self.height}+80+80")
        
        # Estética iOS
        self.root.overrideredirect(True)
        self.root.attributes("-topmost", True)
        self.root.attributes("-transparentcolor", "#010101")
        self.root.config(bg="#010101")
        
        self.colors = {
            "bg": "#1C1C1E", "card": "#2C2C2E",
            "green": "#34C759", "green_glow": "#1A3D23",
            "red": "#FF3B30", "red_glow": "#3D1A1A",
            "yellow": "#FFCC00", "yellow_glow": "#423A00",
            "blue": "#0A84FF",
            "text": "#FFFFFF", "subtext": "#8E8E93", "btn": "#2C2C2E"
        }
        
        self.canvas = tk.Canvas(root, width=self.width, height=self.height, bg="#010101", highlightthickness=0, bd=0)
        self.canvas.pack()
        self.draw_rounded_rect(self.canvas, 0, 0, self.width, self.height, 25, self.colors["bg"], tags="bg")
        
        # Logo y Título
        self.logo_img = None
        base_dir = os.path.dirname(os.path.abspath(__file__))
        
        # Resolver ruta del logo (manejar rutas absolutas de descarga o relativas de assets)
        if os.path.isabs(config.BRAND_LOGO):
            logo_path = config.BRAND_LOGO
        else:
            logo_path = os.path.join(base_dir, config.BRAND_LOGO)

        if os.path.exists(logo_path) and HAS_PIL:
            try:
                pil_img = Image.open(logo_path).resize((30, 30), Image.Resampling.LANCZOS)
                self.logo_img = ImageTk.PhotoImage(pil_img)
                self.canvas.create_image(35, 30, image=self.logo_img)
            except Exception as e:
                print(f"[WIDGET] Error cargando logo: {e}")
        
        # Mostrar el Nombre del Negocio del cliente (o el nombre del SaaS por defecto)
        display_name = config.BUSINESS_NAME if config.BUSINESS_NAME else config.SAAS_NAME
        self.canvas.create_text(60, 30, text=display_name, fill=self.colors["text"], font=("Inter", 10, "bold"), anchor="w")
        
        # Glow y Status
        self.glow_layers = [self.canvas.create_oval(40-r, 75-r, 40+r, 75+r, fill=self.colors["bg"], outline="") for r in range(12, 5, -2)]
        self.status_dot = self.canvas.create_oval(34, 69, 46, 81, fill=self.colors["red"], outline="")
        self.status_label = self.canvas.create_text(60, 75, text="Iniciando...", anchor="w", fill=self.colors["subtext"], font=("Inter", 9))
        self.sync_label = self.canvas.create_text(self.width/2, 100, text="Verificando nube...", fill=self.colors["subtext"], font=("Inter", 8))
        self.rate_label = self.canvas.create_text(self.width/2, 120, text="BCV: --.-- | Binance: --.--", fill=self.colors["text"], font=("Inter", 9, "bold"))
        self.diff_label = self.canvas.create_text(self.width/2, 140, text="Brecha: --.--%", fill=self.colors["yellow"], font=("Inter", 8, "bold"))

        # Botones Principales
        self.btn_bg = self.draw_rounded_rect(self.canvas, 50, 160, 250, 190, 15, self.colors["btn"], tags="btn")
        self.btn_text = self.canvas.create_text(150, 175, text="Sincronizar Ahora", fill=self.colors["green"], font=("Inter", 9, "bold"), tags="btn")
        self.settings_btn = self.canvas.create_text(250, 25, text="⚙", fill=self.colors["subtext"], font=("Inter", 12, "bold"))
        self.close_btn = self.canvas.create_text(275, 25, text="✕", fill=self.colors["subtext"], font=("Inter", 10, "bold"))

        # --- Card de Integridad (Oculta por defecto) ---
        self.integrity_visible = False
        self.height_compact = 200
        self.height_full = 320
        
        # Separador y Toggle
        self.integrity_header = self.canvas.create_text(20, 210, text="ANALISIS DE INTEGRIDAD", fill=self.colors["subtext"], font=("Inter", 7, "bold"), anchor="w", tags="integrity_ui")
        self.toggle_btn = self.canvas.create_text(280, 210, text="▶", fill=self.colors["subtext"], font=("Inter", 8, "bold"), anchor="e", tags="integrity_ui")
        
        self.draw_rounded_rect(self.canvas, 15, 225, 285, 305, 12, self.colors["card"], tags="integrity_card")
        
        self.integrity_labels = {}
        y_start = 245
        for i, (key, label) in enumerate([("productos", "Productos"), ("ventas", "Ventas"), ("detalle", "Detalle"), ("clientes", "Clientes")]):
            y = y_start + i * 14
            self.canvas.create_text(30, y, text=label, fill=self.colors["subtext"], font=("Inter", 8), anchor="w", tags="integrity_card")
            self.integrity_labels[key] = self.canvas.create_text(270, y, text="...", fill=self.colors["subtext"], font=("Inter", 8, "bold"), anchor="e", tags="integrity_card")
        
        # Ocultar inicialmente
        self.canvas.itemconfig("integrity_card", state="hidden")

        # Eventos
        self.canvas.tag_bind("bg", "<ButtonPress-1>", self.start_move)
        self.canvas.tag_bind("bg", "<B1-Motion>", self.do_move)
        self.canvas.tag_bind("btn", "<Button-1>", lambda e: self.trigger_sync())
        self.canvas.tag_bind("btn", "<Enter>", lambda e: self.canvas.itemconfig(self.btn_bg, fill="#3A3A3C"))
        self.canvas.tag_bind("btn", "<Leave>", lambda e: self.canvas.itemconfig(self.btn_bg, fill=self.colors["btn"]))
        
        self.canvas.tag_bind(self.settings_btn, "<Button-1>", lambda e: self.open_settings())
        self.canvas.tag_bind(self.close_btn, "<Button-1>", lambda e: self.hide_to_tray())
        
        # Nueva área de click para toggle integridad
        self.canvas.tag_bind("integrity_ui", "<Button-1>", lambda e: self.toggle_integrity())

        # Control
        self.anim_frame, self.is_online, self.needs_sync, self.is_syncing = 0, False, False, False
        self.last_cloud_ts = 0
        self.last_heartbeat_time = 0
        self.hwid = "" # Se cargará al inicio
        
        # Intentar cargar HWID
        try:
            import security
            self.hwid = security.get_hwid()
        except: pass
        
        # Protocolo de cierre (Redirigir a bandeja)
        self.root.protocol("WM_DELETE_WINDOW", self.hide_to_tray)
        
        # Abrir configuración en el primer inicio si no hay .env
        if not (config.BASE_DIR / ".env").exists():
            self.root.after(500, self.open_settings)
            
        self.animate()
        self.check_loop()
        self.verify_loop()
        
        if HAS_TRAY:
            threading.Thread(target=self.setup_tray, daemon=True).start()

    def open_settings(self):
        settings_win = tk.Toplevel(self.root)
        win_w, win_h = 420, 680
        
        # Centrar
        sw = settings_win.winfo_screenwidth()
        sh = settings_win.winfo_screenheight()
        settings_win.geometry(f"{win_w}x{win_h}+{(sw-win_w)//2}+{(sh-win_h)//2}")
        
        settings_win.overrideredirect(True)
        settings_win.attributes("-topmost", True)
        settings_win.attributes("-transparentcolor", "#010101")
        settings_win.config(bg="#010101")
        
        cv = tk.Canvas(settings_win, width=win_w, height=win_h, bg="#010101", highlightthickness=0, bd=0)
        cv.pack()
        self.draw_rounded_rect(cv, 0, 0, win_w, win_h, 25, self.colors["bg"])
        
        # Barra de título personalizada
        cv.create_text(win_w//2, 25, text="Configuración", fill=self.colors["text"], font=("Inter", 11, "bold"))
        close_btn = cv.create_text(win_w - 30, 25, text="✕", fill=self.colors["subtext"], font=("Inter", 12, "bold"))
        cv.tag_bind(close_btn, "<Button-1>", lambda e: settings_win.destroy())
        cv.tag_bind(close_btn, "<Enter>", lambda e: cv.itemconfig(close_btn, fill=self.colors["red"]))
        cv.tag_bind(close_btn, "<Leave>", lambda e: cv.itemconfig(close_btn, fill=self.colors["subtext"]))
        
        # Dragging
        def start_move(e): settings_win.x, settings_win.y = e.x, e.y
        def do_move(e): settings_win.geometry(f"+{settings_win.winfo_x()+(e.x-settings_win.x)}+{settings_win.winfo_y()+(e.y-settings_win.y)}")
        cv.bind("<Button-1>", start_move)
        cv.bind("<B1-Motion>", do_move)
        
        # Contenedor de contenido
        content = tk.Frame(settings_win, bg=self.colors["bg"])
        cv.create_window(win_w//2, 350, window=content, width=380, height=600)
        
        fields = [
            ("Nombre del Negocio:", "BUSINESS_NAME", config.BUSINESS_NAME),
            ("Logo (ruta):", "BRAND_LOGO", config.BRAND_LOGO),
            ("Ruta Inventario (.dat):", "RUTA_INVENTARIO", config.RUTA_INVENTARIO),
            ("Ruta Precios (.dat):", "RUTA_PRECIOS", config.RUTA_PRECIOS),
            ("Ruta Existencia (.dat):", "RUTA_EXISTENCIA", config.RUTA_EXISTENCIA),
            ("Ruta Ventas (.dat):", "RUTA_VENTAS", config.RUTA_VENTAS),
            ("Ruta Detalle Ventas (.dat):", "RUTA_VENTAS_DETALLE", config.RUTA_VENTAS_DETALLE),
            ("Ruta Clientes (.dat):", "RUTA_CLIENTES", config.RUTA_CLIENTES)
        ]
        
        entries = {}
        for i, (label_text, key, default_val) in enumerate(fields):
            tk.Label(content, text=label_text, bg=self.colors["bg"], fg=self.colors["text"], font=("Inter", 9)).pack(anchor="w", padx=10, pady=(5, 0))
            ent = tk.Entry(content, bg=self.colors["btn"], fg="#FFFFFF", insertbackground="#FFFFFF", relief="flat", font=("Inter", 10), bd=8)
            ent.insert(0, str(default_val))
            ent.pack(fill="x", padx=10, pady=2)
            entries[key] = ent
            
        startup_folder = os.path.join(os.getenv('APPDATA', ''), r'Microsoft\Windows\Start Menu\Programs\Startup')
        shortcut_path = os.path.join(startup_folder, 'SerruchoBackend.lnk')
        
        start_with_win = tk.BooleanVar(value=os.path.exists(shortcut_path))
        chk = tk.Checkbutton(content, text="Iniciar automáticamente con Windows", variable=start_with_win, 
                           bg=self.colors["bg"], fg=self.colors["text"], selectcolor=self.colors["btn"], 
                           activebackground=self.colors["bg"], activeforeground="#FFFFFF", font=("Inter", 9))
        chk.pack(anchor="w", padx=10, pady=15)
        
        def save_and_restart():
            env_path = config.BASE_DIR / ".env"
            env_vars = {}
            if env_path.exists():
                with open(env_path, "r", encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if line and not line.startswith("#") and "=" in line:
                            k, v = line.split("=", 1)
                            env_vars[k.strip()] = v.strip()
            
            for k, ent in entries.items():
                env_vars[k] = ent.get().strip()
                
            with open(env_path, "w", encoding="utf-8") as f:
                for k, v in env_vars.items():
                    f.write(f"{k}={v}\n")
                    
            import subprocess
            if start_with_win.get():
                script_path = os.path.join(str(config.BASE_DIR), "start_backend.vbs")
                work_dir = str(config.BASE_DIR)
                ps_command = f"$s=(New-Object -COM WScript.Shell).CreateShortcut('{shortcut_path}');$s.TargetPath='wscript.exe';$s.Arguments='\"\"\"{script_path}\"\"\"';$s.WorkingDirectory='{work_dir}';$s.Save()"
                subprocess.run(["powershell", "-Command", ps_command], creationflags=subprocess.CREATE_NO_WINDOW)
            else:
                if os.path.exists(shortcut_path):
                    try: os.remove(shortcut_path)
                    except: pass
                    
            custom_dialogs.show_info("Configuración", "Configuración guardada.\nLa aplicación se cerrará para aplicar los cambios.")
            self.quit_app()
            
        btn_frame = tk.Frame(content, bg=self.colors["bg"])
        btn_frame.pack(pady=10)
        tk.Button(btn_frame, text="Cancelar", command=settings_win.destroy, bg=self.colors["btn"], fg="#FFFFFF", font=("Inter", 10), relief="flat", padx=15, pady=6).pack(side="left", padx=10)
        tk.Button(btn_frame, text="Guardar Cambios", command=save_and_restart, bg=self.colors["green"], fg="#FFFFFF", font=("Inter", 10, "bold"), relief="flat", padx=15, pady=6).pack(side="left", padx=10)

    def hide_to_tray(self):
        """Oculta la ventana principal. La app sigue corriendo en la bandeja."""
        self.root.withdraw()

    def show_from_tray(self, icon=None, item=None):
        """Muestra la ventana principal desde la bandeja."""
        self.root.deiconify()
        self.root.attributes("-topmost", True)
        self.root.focus_force()

    def setup_tray(self):
        try:
            # Intentar cargar desde el config (ruta base del .exe)
            logo_path = str(config.BASE_DIR / config.BRAND_LOGO)
            
            if not os.path.exists(logo_path):
                # Fallback al icono compilado dentro del exe (assets/icon.ico)
                nuitka_dir = os.path.dirname(os.path.abspath(__file__))
                logo_path = os.path.join(nuitka_dir, "assets", "icon.ico")
                
            icon_img = Image.open(logo_path) if os.path.exists(logo_path) else Image.new('RGB', (64, 64), (52, 199, 89))
            menu = (item('Mostrar Monitor', self.show_from_tray, default=True), item('Salir', self.quit_app))
            self.tray_icon = pystray.Icon(config.SAAS_NAME, icon_img, f"{config.SAAS_NAME} - {config.BUSINESS_NAME}", menu)
            self.tray_icon.run()
        except Exception as e: 
            print("Tray error:", e)

    def quit_app(self):
        if HAS_TRAY: self.tray_icon.stop()
        self.root.quit()
        sys.exit()

    def draw_rounded_rect(self, canvas, x1, y1, x2, y2, r, color, tags=""):
        p = [x1+r, y1, x1+r, y1, x2-r, y1, x2-r, y1, x2, y1, x2, y1+r, x2, y1+r, x2, y2-r, x2, y2-r, x2, y2, x2-r, y2, x2-r, y2, x1+r, y2, x1+r, y2, x1, y2, x1, y2-r, x1, y2-r, x1, y1+r, x1, y1+r, x1, y1]
        return canvas.create_polygon(p, smooth=True, fill=color, tags=tags)

    def toggle_integrity(self):
        self.integrity_visible = not self.integrity_visible
        if self.integrity_visible:
            self.canvas.itemconfig("integrity_card", state="normal")
            self.canvas.itemconfig(self.toggle_btn, text="▼")
            h = self.height_full
        else:
            self.canvas.itemconfig("integrity_card", state="hidden")
            self.canvas.itemconfig(self.toggle_btn, text="▶")
            h = self.height_compact

        # Re-dibujar fondo redondeado
        self.canvas.delete("bg")
        self.draw_rounded_rect(self.canvas, 0, 0, self.width, h, 25, self.colors["bg"], tags="bg")
        self.canvas.tag_lower("bg")
        self.root.geometry(f"{self.width}x{h}")

    def verify_loop(self):
        """Monitorea la integridad de datos consultando al backend."""
        def task():
            if self.is_syncing or not self.integrity_visible:
                self.root.after(15000, self.verify_loop)
                return
            try:
                # Usar requests para mayor robustez
                r = requests.get("http://localhost:5000/api/v1/sync/status", timeout=5)
                if r.status_code == 200:
                    data = r.json()
                    entities = data.get("entities", {})
                    for key, info in entities.items():
                        if key in self.integrity_labels:
                            local, cloud, ok = info.get("local", 0), info.get("cloud", -1), info.get("ok", False)
                            if cloud < 0: txt, color = "Error Nube", self.colors["red"]
                            elif ok: txt, color = f"{local:,} ✓", self.colors["green"]
                            else: txt, color = f"L:{local:,} | N:{cloud:,}", self.colors["yellow"]
                            
                            lbl = self.integrity_labels[key]
                            self.root.after(0, lambda l=lbl, t=txt, c=color: self.canvas.itemconfig(l, text=t, fill=c))
            except Exception as e:
                print(f"[WIDGET] Error en verify_loop: {e}")
            
            self.root.after(15000, self.verify_loop)
        
        threading.Thread(target=task, daemon=True).start()

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
            
            # 3. Heartbeat y Verificación de Trigger Remoto (Cada 1 min para el dashboard)
            now_ts = time.time()
            if now_ts - self.last_heartbeat_time > 60: # Cada minuto
                self.send_heartbeat()
                self.last_heartbeat_time = now_ts

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

    def trigger_sync(self, auto=False):
        if self.is_syncing: return
        self.is_syncing = True
        self.canvas.itemconfig(self.btn_text, text="Sincronizando...")
        self.update_ui()
        
        def run():
            try:
                # Paso 1: Inventario
                self.root.after(0, lambda: self.canvas.itemconfig(self.sync_label, text="Sync Inventario..."))
                urllib.request.urlopen("http://localhost:5000/api/v1/sync/inventory", timeout=120)
                
                # Paso 2: Ventas
                self.root.after(0, lambda: self.canvas.itemconfig(self.sync_label, text="Sync Ventas..."))
                urllib.request.urlopen("http://localhost:5000/api/v1/sync/sales", timeout=120)
                
                print("[WIDGET] Sincronización completa.")
            except Exception as e:
                print(f"[WIDGET] Error en trigger_sync: {e}")
            
            self.is_syncing = False
            self.root.after(0, lambda: (self.canvas.itemconfig(self.btn_text, text="Sincronizar Ahora"), self.update_ui()))
            self.root.after(500, self.check_loop) 
        
        threading.Thread(target=run, daemon=True).start()

    def send_heartbeat(self):
        """Envía el estado de salud y versión a la tabla de licencias global."""
        def task():
            try:
                # 1. Verificar si el servicio local de Sync está arriba
                local_service_ok = False
                try:
                    # Probamos el puerto 5000 (Backend Python)
                    with socket.create_connection(("localhost", 5000), timeout=2):
                        local_service_ok = True
                except: pass

                status_msg = "Online" if local_service_ok else "Local Service Error"
                
                # 2. Reportar a la tabla de licencias global
                url = f"{config.LICENSE_SUPABASE_URL}/rest/v1/licenses?hwid=eq.{self.hwid}"
                headers = {
                    "apikey": config.LICENSE_SUPABASE_ANON_KEY,
                    "Authorization": f"Bearer {config.LICENSE_SUPABASE_ANON_KEY}",
                    "Content-Type": "application/json",
                    "Prefer": "return=representation"
                }
                
                payload = {
                    "last_seen": datetime.now(timezone.utc).isoformat(),
                    "software_version": config.VERSION,
                    "connection_status": status_msg
                }
                
                # Actualizar y obtener la fila actual (para leer el trigger remoto)
                resp = requests.patch(url, json=payload, headers=headers, timeout=10)
                
                if resp.status_code == 200:
                    data = resp.json()
                    if data and data[0].get("remote_trigger_sync"):
                        print("[WIDGET] Trigger remoto detectado! Sincronizando...")
                        # Limpiar el trigger en la nube
                        requests.patch(url, json={"remote_trigger_sync": False}, headers=headers, timeout=5)
                        self.root.after(0, self.trigger_sync)
                
                # 3. Actualizar UI si hay error de servicio local
                if not local_service_ok:
                    self.root.after(0, lambda: self.canvas.itemconfig(self.status_label, text="Error Servidor Sync", fill=self.colors["red"]))

            except Exception as e:
                print(f"[WIDGET] Heartbeat error: {e}")

        threading.Thread(target=task, daemon=True).start()

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
    app = HybridCloudWidget(root)
    root.mainloop()
