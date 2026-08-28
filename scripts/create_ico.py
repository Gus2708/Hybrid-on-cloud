from PIL import Image
import os

def create_ico():
    base_dir = os.path.dirname(os.path.abspath(__file__))
    logo_path = os.path.join(base_dir, "assets", "logo.png")
    ico_path = os.path.join(base_dir, "assets", "icon.ico")
    
    if os.path.exists(logo_path):
        img = Image.open(logo_path)
        # Crear icono con múltiples tamaños para Windows
        img.save(ico_path, format='ICO', sizes=[(16, 16), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
        print(f"Icono creado en: {ico_path}")
    else:
        print("No se encontró el logo.png")

if __name__ == "__main__":
    create_ico()
