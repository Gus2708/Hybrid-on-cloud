import os
import re

def inspect_file(filepath, bytes_to_read=4096):
    print(f"--- Inspecting {filepath} ---")
    try:
        with open(filepath, 'rb') as f:
            content = f.read(bytes_to_read)
            
            # Print visible ASCII characters
            tokens = re.findall(b'[\x20-\x7E]{4,}', content)
            print("Visible strings:")
            for t in tokens[:30]:  # Limit output
                try:
                    print(t.decode('ascii'))
                except:
                    pass
            print("-" * 40)
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    base = r"h:\HybridLite\HybridEmpresa\HybridDataBase"
    inspect_file(os.path.join(base, "TTransaccionvta.dat"), 8192)
    inspect_file(os.path.join(base, "TDetalleVta.dat"), 8192)
    inspect_file(os.path.join(base, "TClientes.dat"), 8192)
