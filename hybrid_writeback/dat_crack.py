"""dat_crack.py — Prueba hipótesis de algoritmo del checksum de fila DBISAM
sobre el snapshot capturado (snap_antes.bin)."""
import hashlib
import zlib

HEADER_LEN = 0x200
with open("snap_antes.bin", "rb") as f:
    blob = f.read()
header = blob[:HEADER_LEN]
row = blob[HEADER_LEN:]

stored = row[0x09:0x19]   # checksum de fila almacenado (16 bytes)
print(f"Checksum almacenado (fila): {stored.hex()}")
print(f"row_size={len(row)}")

# zona de datos de campos empieza ~0x1A; probamos muchos rangos y variantes
def variantes():
    for a in [0x00, 0x09, 0x19, 0x1A, 0x1B, 0x1C]:
        for b in [len(row), len(row)-1, len(row)-2]:
            yield (f"row[0x{a:X}:{b}]", row[a:b])
    # con el propio checksum puesto a cero
    rz = bytearray(row); rz[0x09:0x19] = b"\x00" * 16
    for a in [0x00, 0x19, 0x1A]:
        yield (f"rowZEROcks[0x{a:X}:]", bytes(rz[a:]))
    # header + datos (por si el hash incluye algo del header)
    yield ("desc_first16", row[0x1A:0x1A+16])

print("\n--- MD5 ---")
for nombre, datos in variantes():
    h = hashlib.md5(datos).digest()
    mark = "  <<< MATCH!!!" if h == stored else ""
    if mark or True:
        if h == stored:
            print(f"MD5 {nombre}: {h.hex()}{mark}")
# Mostrar solo coincidencias para no saturar:
print("\n(Buscando coincidencias exactas en MD5/SHA1/CRC...)")
found = False
for nombre, datos in variantes():
    for alg, fn in [("md5", lambda d: hashlib.md5(d).digest()),
                    ("sha1_16", lambda d: hashlib.sha1(d).digest()[:16]),
                    ("sha256_16", lambda d: hashlib.sha256(d).digest()[:16])]:
        if fn(datos) == stored:
            print(f"  >>> COINCIDE: {alg} de {nombre}")
            found = True
if not found:
    print("  Ninguna coincidencia directa. Se necesita diff con escritura conocida.")
