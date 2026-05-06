import os
import binascii

filepath = r"h:\HybridLite\HybridEmpresa\HybridDataBase\TTransaccionvta.dat"

try:
    with open(filepath, 'rb') as f:
        content = f.read(2048)
        
    print("--- HEX DUMP ---")
    for i in range(0, len(content), 16):
        chunk = content[i:i+16]
        hex_chunk = " ".join([f"{b:02x}" for b in chunk])
        ascii_chunk = "".join([chr(b) if 32 <= b <= 126 else "." for b in chunk])
        print(f"{i:04x}: {hex_chunk:<48}  {ascii_chunk}")
        
except Exception as e:
    print(f"Error: {e}")
