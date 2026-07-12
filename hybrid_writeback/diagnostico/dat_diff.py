"""dat_diff.py — Compara dos snapshots (antes/después) byte a byte.
Muestra qué cambió en el header (tabla) y en la fila."""
import hashlib

HEADER_LEN = 0x200
with open("snap_antes.bin", "rb") as f:
    a = f.read()
with open("snap_despues.bin", "rb") as f:
    b = f.read()

ha, hb = a[:HEADER_LEN], b[:HEADER_LEN]
ra, rb = a[HEADER_LEN:], b[HEADER_LEN:]


def diff(nombre, x, y):
    print(f"\n=== Cambios en {nombre} (len {len(x)} vs {len(y)}) ===")
    cambios = [(i, x[i], y[i]) for i in range(min(len(x), len(y))) if x[i] != y[i]]
    if not cambios:
        print("  (sin cambios)")
        return cambios
    # agrupar en rangos contiguos
    rangos = []
    ini = cambios[0][0]; prev = ini
    for (i, _, _) in cambios[1:]:
        if i != prev + 1:
            rangos.append((ini, prev)); ini = i
        prev = i
    rangos.append((ini, prev))
    for (s, e) in rangos:
        viejo = bytes(x[s:e+1]).hex(' ')
        nuevo = bytes(y[s:e+1]).hex(' ')
        print(f"  [0x{s:X}..0x{e:X}] {viejo}  ->  {nuevo}")
    return cambios


diff("HEADER (tabla)", ha, hb)
diff("FILA", ra, rb)

# Verificar hipótesis del checksum de fila DESPUÉS
print("\n=== Verificación checksum de fila (después) ===")
stored_after = rb[0x09:0x19]
calc_after = hashlib.md5(rb[0x19:]).digest()
print(f"  almacenado: {stored_after.hex()}")
print(f"  MD5(row[0x19:]): {calc_after.hex()}")
print(f"  {'COINCIDE ✓' if stored_after == calc_after else 'NO coincide'}")
