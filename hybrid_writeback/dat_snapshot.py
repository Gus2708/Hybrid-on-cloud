"""
dat_snapshot.py — Captura los bytes crudos del header y de un registro concreto
de TCostoPrecioInv.Dat, para ingeniería inversa del formato de escritura DBISAM.

Uso:  python dat_snapshot.py <etiqueta> [codigo] [tipo]
Genera:  snap_<etiqueta>.bin  (bytes crudos: header + fila)  y muestra hex.
"""
import sys
import pydbisam

ETIQUETA = sys.argv[1] if len(sys.argv) > 1 else "snap"
CODIGO = sys.argv[2] if len(sys.argv) > 2 else "00-002-024"
TIPO = int(sys.argv[3]) if len(sys.argv) > 3 else 1

DAT = r"H:\HybridLite\HybridEmpresa\HybridDataBase\TCostoPrecioInv.Dat"
HEADER_LEN = 0x200  # zona de header antes de las definiciones de campos


def main():
    db = pydbisam.PyDBISAM(DAT)
    fields = db.fields()
    idx = {n: i for i, n in enumerate(fields)}
    cod_i, tipo_i = idx["TPC_CODIGOPRODUCTO"], idx["TPC_TIPO"]

    data = db._data_bytes
    data_offset = db._data_offset
    row_size = db._row_size
    total = db._total_rows + db._deleted_rows

    # localizar el índice de fila del registro buscado
    target_index = None
    for i in range(total):
        vals = db.row(i, extract_deleted=True)
        if vals is None:
            continue
        if str(vals[cod_i]).strip() == CODIGO and vals[tipo_i] == TIPO:
            target_index = i
            break
    if target_index is None:
        print(f"No encontré {CODIGO} TIPO={TIPO}")
        return

    row_start = data_offset + target_index * row_size
    row_bytes = bytes(data[row_start:row_start + row_size])
    header_bytes = bytes(data[0:HEADER_LEN])

    # info de estructura útil
    pvp_col = next(c for c in db._columns if c.name == "TPC_PVPCONIMPUESTO1")
    print(f"row_index={target_index} row_start=0x{row_start:X} row_size={row_size}")
    print(f"total_rows(header@0x29)={db._total_rows}  last_updated={db.last_updated}")
    print(f"TPC_PVPCONIMPUESTO1: row_offset={pvp_col.row_offset} size={pvp_col.size} "
          f"-> bytes de la fila [0x{pvp_col.row_offset:X}:0x{pvp_col.row_offset+pvp_col.size:X}]")
    print(f"\nFila (hex):")
    for off in range(0, len(row_bytes), 16):
        chunk = row_bytes[off:off+16]
        print(f"  +0x{off:03X}: {chunk.hex(' ')}")

    # guardar snapshot crudo: header(0x200) + fila
    out = f"snap_{ETIQUETA}.bin"
    with open(out, "wb") as f:
        f.write(header_bytes)
        f.write(row_bytes)
    # guardar metadatos
    with open(f"snap_{ETIQUETA}.meta", "w") as f:
        f.write(f"row_index={target_index}\nrow_start={row_start}\nrow_size={row_size}\n"
                f"header_len={HEADER_LEN}\npvp_offset={pvp_col.row_offset}\npvp_size={pvp_col.size}\n")
    print(f"\n[OK] Guardado {out} ({HEADER_LEN}+{row_size} bytes)")


if __name__ == "__main__":
    main()
