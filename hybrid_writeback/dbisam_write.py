"""
dbisam_write.py — Escritor PURO en Python para TCostoPrecioInv.Dat (DBISAM).

Reproduce lo que hace el motor al cambiar un precio:
  1. Escribe el double del campo en su offset.
  2. Recalcula el checksum de fila = MD5(fila[0x19:]) y lo escribe en [0x9:0x19].
  3. (Opcional) actualiza el flag de cambio (header 0x0) y la fecha (header 0x3F).
No toca .Idx (el precio no es campo indexado) ni el MD5 de tabla (no cambia).

Es legal: es nuestro propio formato y nuestros propios datos. No usa ni modifica
software de Elevate.

API:  set_precio_usd(codigo, valor) -> dict
"""
import struct
import hashlib
import datetime
import pydbisam

DAT = r"H:\HybridLite\HybridEmpresa\HybridDataBase\TCostoPrecioInv.Dat"
ROW_CKSUM_OFF = 0x09          # offset del checksum dentro de la fila (16 bytes)
ROW_DATA_OFF = 0x19           # los datos hasheados empiezan aquí
HDR_FLAG_OFF = 0x00           # byte contador/flag de cambios en el header
HDR_DATE_OFF = 0x3F           # fecha (double, días desde epoch DBISAM)
_DBISAM_EPOCH = datetime.datetime(3798, 12, 28)


def _locate(db, codigo, tipo, field_name):
    idx = {n: i for i, n in enumerate(db.fields())}
    cod_i, tipo_i = idx["TPC_CODIGOPRODUCTO"], idx["TPC_TIPO"]
    total = db._total_rows + db._deleted_rows
    col = next(c for c in db._columns if c.name == field_name)
    for i in range(total):
        vals = db.row(i, extract_deleted=True)
        if vals is None:
            continue
        if str(vals[cod_i]).strip() == codigo and vals[tipo_i] == tipo:
            return i, col.row_offset, col.size
    return None, None, None


def set_precio_usd(codigo, valor, tipo=1, field_name="TPC_PVPCONIMPUESTO1",
                   update_meta=True, verify=True):
    """Fija un campo double (por defecto el PVP con impuesto USD) en TCostoPrecioInv."""
    db = pydbisam.PyDBISAM(DAT)
    data_offset, row_size = db._data_offset, db._row_size
    row_index, foff, fsize = _locate(db, codigo, tipo, field_name)
    if row_index is None:
        return {"ok": False, "detalle": f"No encontré {codigo} TIPO={tipo}"}
    if fsize != 8:
        return {"ok": False, "detalle": f"Campo {field_name} no es double (size={fsize})"}

    row_start = data_offset + row_index * row_size

    with open(DAT, "r+b") as f:
        # leer la fila completa
        f.seek(row_start)
        row = bytearray(f.read(row_size))

        # 1) escribir el nuevo valor en el campo
        row[foff:foff + 8] = struct.pack("<d", float(valor))

        # 2) recalcular checksum de fila = MD5(fila[0x19:])
        nuevo_cksum = hashlib.md5(bytes(row[ROW_DATA_OFF:])).digest()
        row[ROW_CKSUM_OFF:ROW_CKSUM_OFF + 16] = nuevo_cksum

        # escribir la fila modificada
        f.seek(row_start)
        f.write(row)

        # 3) metadatos del header (flag de cambio + fecha)
        if update_meta:
            f.seek(HDR_FLAG_OFF)
            flag = f.read(1)[0]
            f.seek(HDR_FLAG_OFF)
            f.write(bytes([(flag + 2) & 0xFF]))   # el motor lo subió +2 (f5->f7)
            dias = (datetime.datetime.now() - _DBISAM_EPOCH).total_seconds() / 86400.0
            f.seek(HDR_DATE_OFF)
            f.write(struct.pack("<d", dias))

        f.flush()
        import os
        os.fsync(f.fileno())

    result = {"ok": True, "row_index": row_index, "detalle": f"{field_name}={valor} escrito"}

    # 4) verificación independiente
    if verify:
        db2 = pydbisam.PyDBISAM(DAT)
        idx = {n: i for i, n in enumerate(db2.fields())}
        leido, total = None, 0
        for r in db2.rows():
            total += 1
            if (str(r[idx["TPC_CODIGOPRODUCTO"]]).strip() == codigo
                    and r[idx["TPC_TIPO"]] == tipo):
                leido = r[idx[field_name]]
        result["verificado"] = abs(float(leido) - float(valor)) < 1e-6
        result["leido"] = leido
        result["filas_integras"] = total
    return result


if __name__ == "__main__":
    import sys
    codigo = sys.argv[1] if len(sys.argv) > 1 else "00-002-024"
    valor = float(sys.argv[2]) if len(sys.argv) > 2 else 12.00
    res = set_precio_usd(codigo, valor)
    print("RESULTADO:")
    for k, v in res.items():
        print(f"  {k}: {v}")
