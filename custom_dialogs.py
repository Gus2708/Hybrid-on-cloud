import tkinter as tk
from tkinter import font as tkfont
import math

class ThemedDialog(tk.Toplevel):
    def __init__(self, parent, title, message, dialog_type="info", show_input=False, show_yesno=False):
        super().__init__(parent)
        self.title(title)
        self.width, self.height = 350, 220
        if show_input: self.height = 250
        
        # Center on screen
        screen_width = self.winfo_screenwidth()
        screen_height = self.winfo_screenheight()
        x = (screen_width // 2) - (self.width // 2)
        y = (screen_height // 2) - (self.height // 2)
        self.geometry(f"{self.width}x{self.height}+{x}+{y}")
        
        # Premium iOS look
        self.overrideredirect(True)
        self.attributes("-topmost", True)
        self.attributes("-transparentcolor", "#010101")
        self.config(bg="#010101")
        
        self.colors = {
            "bg": "#1C1C1E",
            "green": "#34C759",
            "red": "#FF3B30",
            "yellow": "#FFCC00",
            "text": "#FFFFFF",
            "subtext": "#8E8E93",
            "btn": "#2C2C2E",
            "input_bg": "#2C2C2E"
        }
        
        self.canvas = tk.Canvas(self, width=self.width, height=self.height, bg="#010101", highlightthickness=0, bd=0)
        self.canvas.pack()
        self.draw_rounded_rect(0, 0, self.width, self.height, 25, self.colors["bg"])
        
        # Icon/Indicator color
        indicator_color = self.colors["green"]
        if dialog_type == "warning": indicator_color = self.colors["yellow"]
        if dialog_type == "error": indicator_color = self.colors["red"]
        
        # Title
        self.canvas.create_text(self.width//2, 35, text=title, fill=self.colors["text"], font=("Inter", 12, "bold"))
        
        # Message (Wrapped)
        self.canvas.create_text(self.width//2, 85, text=message, fill=self.colors["subtext"], 
                                font=("Inter", 10), width=300, justify="center")
        
        self.result = None
        self.input_var = tk.StringVar()
        
        if show_input:
            self.entry = tk.Entry(self, textvariable=self.input_var, bg=self.colors["input_bg"], 
                                  fg=self.colors["text"], insertbackground=self.colors["text"],
                                  relief="flat", font=("Inter", 11), justify="center")
            # Place entry inside the dialog
            self.entry_window = self.canvas.create_window(self.width//2, 140, window=self.entry, width=280, height=35)
            self.entry.focus_set()
            self.entry.bind("<Return>", lambda e: self.on_ok())
        
        # Buttons
        if show_yesno:
            self.draw_button(self.width//2 - 80, self.height - 50, 70, 35, "No", self.on_cancel, color=self.colors["btn"])
            self.draw_button(self.width//2 + 10, self.height - 50, 70, 35, "Sí", self.on_ok, color=self.colors["green"])
        else:
            self.draw_button(self.width//2 - 50, self.height - 50, 100, 35, "OK", self.on_ok, color=self.colors["green"])

    def draw_rounded_rect(self, x1, y1, x2, y2, r, color):
        p = [x1+r, y1, x1+r, y1, x2-r, y1, x2-r, y1, x2, y1, x2, y1+r, x2, y1+r, x2, y2-r, x2, y2-r, x2, y2, x2-r, y2, x2-r, y2, x1+r, y2, x1+r, y2, x1, y2, x1, y2-r, x1, y2-r, x1, y1+r, x1, y1+r, x1, y1]
        return self.canvas.create_polygon(p, smooth=True, fill=color)

    def draw_button(self, x, y, w, h, text, command, color):
        btn_bg = self.draw_rounded_rect(x, y, x+w, y+h, 12, color)
        btn_text = self.canvas.create_text(x+w/2, y+h/2, text=text, fill="#FFFFFF", font=("Inter", 10, "bold"))
        
        self.canvas.tag_bind(btn_bg, "<Button-1>", lambda e: command())
        self.canvas.tag_bind(btn_text, "<Button-1>", lambda e: command())
        
        # Hover effect
        self.canvas.tag_bind(btn_bg, "<Enter>", lambda e: self.canvas.itemconfig(btn_bg, fill=self.brighten(color)))
        self.canvas.tag_bind(btn_bg, "<Leave>", lambda e: self.canvas.itemconfig(btn_bg, fill=color))

    def brighten(self, hex_color):
        if hex_color.startswith('#'): hex_color = hex_color[1:]
        r, g, b = int(hex_color[:2], 16), int(hex_color[2:4], 16), int(hex_color[4:], 16)
        r, g, b = min(255, int(r*1.2)), min(255, int(g*1.2)), min(255, int(b*1.2))
        return f'#{r:02x}{g:02x}{b:02x}'

    def on_ok(self):
        self.result = self.input_var.get() if hasattr(self, 'entry') else True
        self.destroy()

    def on_cancel(self):
        self.result = False
        self.destroy()

def show_info(title, message):
    root = tk.Tk()
    root.withdraw()
    d = ThemedDialog(root, title, message, dialog_type="info")
    root.wait_window(d)
    root.destroy()

def show_warning(title, message):
    root = tk.Tk()
    root.withdraw()
    d = ThemedDialog(root, title, message, dialog_type="warning")
    root.wait_window(d)
    root.destroy()

def show_error(title, message):
    root = tk.Tk()
    root.withdraw()
    d = ThemedDialog(root, title, message, dialog_type="error")
    root.wait_window(d)
    root.destroy()

def ask_string(title, prompt):
    root = tk.Tk()
    root.withdraw()
    d = ThemedDialog(root, title, prompt, show_input=True)
    root.wait_window(d)
    res = d.result
    root.destroy()
    return res

def ask_yes_no(title, message):
    root = tk.Tk()
    root.withdraw()
    d = ThemedDialog(root, title, message, show_yesno=True)
    root.wait_window(d)
    res = d.result
    root.destroy()
    return res

if __name__ == "__main__":
    # Test
    # show_info("Sincronización", "El inventario se ha actualizado correctamente.")
    key = ask_string("Activación", "Ingrese su clave de licencia:")
    print(f"Key entered: {key}")
