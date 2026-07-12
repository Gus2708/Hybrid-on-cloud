# `diagnostico/` — scripts desechables del desarrollo del write-back

## Qué es esto

Scripts **desechables** de diagnóstico, calibración y exploración creados
durante el desarrollo del write-back a HybridLite (`diag_*`, `dbg_*`, `shot_*`,
`odbc_*`, `dat_*`, `dump_*`, calibradores, inspectores de ventanas, y enfoques
abandonados como `hybrid_ui.py`, `dbisam_write.py` y los experimentos ODBC).

**No son producción.** Ningún módulo de producción los importa; los módulos de
producción viven en el directorio padre (`hybrid_writeback/`). Se conservan
solo como herramientas de referencia para depurar o recalibrar flujos.

## Cómo ejecutar uno

Estos scripts importan módulos del paquete padre (`flujo_precio`, `realinput`,
etc.) asumiendo que `hybrid_writeback/` está en el path de Python. Ejecutarlos
desde `hybrid_writeback/` con `PYTHONPATH` apuntando al directorio actual:

```powershell
cd "C:\Proyect\backend serrucho\hybrid_writeback"
$env:PYTHONPATH = (Get-Location)
python diagnostico\<script>.py
```

## Advertencia

Varios de estos scripts **toman el control del mouse/teclado real**
(`SendInput`) o **abren y automatizan HybridLite**. Mientras corren, el equipo
queda ocupado y un movimiento manual puede corromper la secuencia. Ejecutarlos
**solo con supervisión y fuera del horario de la tienda**. Algunos (los `odbc_*`
y `dbisam_write.py`) son enfoques de escritura abandonados: no usarlos nunca
contra los `.DAT` vivos.
