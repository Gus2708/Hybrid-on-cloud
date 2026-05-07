import tkinter as tk
from tkinter import messagebox
import urllib.request
import json
import socket
import threading
import time

class SerruchoWidget:
    def __init__(self, root):
        self.root = root
        self.root.title("El Serrucho Monitor")
        self.root.geometry("250x150+50+50") # Tamaño y posición inicial
        self.root.overrideredirect(True)    # Quitar bordes de ventana
        self.root.attributes("-topmost", True) # Siempre al frente
        self.root.configure(bg="#1e1e1e")   # Fondo oscuro
        
        # Permitir arrastrar la ventana
        self.root.bind("<ButtonPress-1>", self.start_move)
        self.root.bind("<ButtonRelease-1>", self.stop_move)
        self.root.bind("<B1-Motion>", self.do_move)

        # Estilos
        self.title_font = ("Segoe UI", 10, "bold")
        self.text_font = ("Segoe UI", 9)
        
        # Header
        self.header = tk.Label(root, text="EL SERRUCHO BACKEND", bg="#2d2d2d", fg="#ffffff", font=self.title_font, pady=5)
        self.header.pack(fill="x")
        
        # Status Label
        self.status_frame = tk.Frame(root, bg="#1e1e1e", pady=10)
        self.status_frame.pack()
        
        self.dot = tk.Label(self.status_frame, text="●", fg="#ff4444", bg="#1e1e1e", font=("Arial", 12))
        self.dot.pack(side="left")
        
        self.status_text = tk.Label(self.status_frame, text="Desconectado", fg="#cccccc", bg="#1e1e1e", font=self.text_font)
        self.status_text.pack(side="left", padx=5)
        
        # Sync Label
        self.sync_text = tk.Label(root, text="Última Sync: --:--", fg="#888888", bg="#1e1e1e", font=self.text_font)
        self.sync_text.pack()
        
        # IP Label
        self.ip_addr = self.get_local_ip()
        self.ip_text = tk.Label(root, text=f"IP: {self.ip_addr}", fg="#555555", bg="#1e1e1e", font=("Segoe UI", 8))
        self.ip_text.pack(side="bottom", pady=2)
        
        # Buttons Frame
        self.btn_frame = tk.Frame(root, bg="#1e1e1e", pady=10)
        self.btn_frame.pack()
        
        self.sync_btn = tk.Button(self.btn_frame, text="Sync Ahora", command=self.trigger_sync, bg="#007acc", fg="white", font=self.title_font, relief="flat", padx=10)
        self.sync_btn.pack(side="left", padx=5)
        
        self.close_btn = tk.Button(self.btn_frame, text="✕", command=root.quit, bg="#333333", fg="white", relief="flat", font=self.title_font)
        self.close_btn.pack(side="left")

    def get_local_ip(self):
        try:
            # Crea un socket temporal para detectar la interfaz de red activa
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect(("8.8.8.8", 80))
            ip = s.getsockname()[0]
            s.close()
            return ip
        except:
            return "127.0.0.1"

        # Iniciar actualización periódica
        self.update_status()

    def start_move(self, event): self.x, self.y = event.x, event.y
    def stop_move(self, event): self.x = self.y = None
    def do_move(self, event):
        deltax, deltay = event.x - self.x, event.y - self.y
        x = self.root.winfo_x() + deltax
        y = self.root.winfo_y() + deltay
        self.root.geometry(f"+{x}+{y}")

    def update_status(self):
        def check():
            try:
                with urllib.request.urlopen("http://localhost:5000/health", timeout=2) as resp:
                    data = json.loads(resp.read().decode())
                    self.dot.config(fg="#44ff44")
                    self.status_text.config(text="En Línea")
                    self.sync_text.config(text=f"Última Sync: {data.get('last_sync', 'Nunca')}")
            except:
                self.dot.config(fg="#ff4444")
                self.status_text.config(text="Desconectado")
            
            self.root.after(2000, self.update_status) # Re-check cada 2 segundos (Modo Instantáneo)

        threading.Thread(target=check, daemon=True).start()

    def trigger_sync(self):
        self.sync_btn.config(state="disabled", text="Sincronizando...")
        def run():
            try:
                with urllib.request.urlopen("http://localhost:5000/api/v1/sync/run", timeout=60) as resp:
                    messagebox.showinfo("Sincronización", "¡Sincronización completada!")
            except Exception as e:
                messagebox.showerror("Error", f"Fallo al sincronizar: {e}")
            self.sync_btn.config(state="normal", text="Sync Ahora")
            
        threading.Thread(target=run, daemon=True).start()

if __name__ == "__main__":
    root = tk.Tk()
    app = SerruchoWidget(root)
    root.mainloop()
