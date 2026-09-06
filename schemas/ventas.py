from typing import Optional, Any, Dict
from pydantic import BaseModel, ConfigDict, field_validator
from schemas.writeback import parse_safe_float


class VentaCabeceraSchema(BaseModel):
    model_config = ConfigDict(extra="ignore")

    documento: str
    fecha: Optional[str] = None
    cliente: Optional[str] = None
    total_neto: float
    total_impuesto: float = 0.0
    total_bruto: Optional[float] = None
    id_unico: Optional[int] = None
    tasa_referencial: Optional[float] = None

    @field_validator("documento", mode="before")
    @classmethod
    def sanitize_doc(cls, v: Any) -> str:
        s = str(v or "").strip()
        return s.zfill(8) if s.isdigit() else s

    @field_validator("total_neto", "total_impuesto", "total_bruto", "tasa_referencial", mode="before")
    @classmethod
    def validate_numbers(cls, v: Any) -> Optional[float]:
        return parse_safe_float(v)

    @classmethod
    def from_csv_row(cls, row: Dict[str, Any]) -> "VentaCabeceraSchema":
        return cls(
            documento=str(row.get("THT_DOCUMENTO", "")),
            fecha=row.get("THT_FECHA"),
            cliente=row.get("THT_CLIENTE"),
            total_neto=row.get("THT_TOTALNETO", 0),
            total_impuesto=row.get("THT_TOTALIMPUESTO", 0),
            total_bruto=row.get("THT_TOTALBRUTO"),
            id_unico=int(row["THT_IDUNICO"]) if row.get("THT_IDUNICO") else None,
            tasa_referencial=row.get("THT_FACTORREFERENCIAL"),
        )


class VentaDetalleSchema(BaseModel):
    model_config = ConfigDict(extra="ignore")

    documento: str
    codigo_producto: str
    descripcion: Optional[str] = None
    cantidad: float
    precio: float
    total: Optional[float] = None

    @field_validator("documento", mode="before")
    @classmethod
    def sanitize_doc(cls, v: Any) -> str:
        s = str(v or "").strip()
        return s.zfill(8) if s.isdigit() else s

    @field_validator("cantidad", "precio", "total", mode="before")
    @classmethod
    def validate_numbers(cls, v: Any) -> Optional[float]:
        return parse_safe_float(v)

    @classmethod
    def from_csv_row(cls, row: Dict[str, Any]) -> "VentaDetalleSchema":
        return cls(
            documento=str(row.get("TDT_DOCUMENTO", "")),
            codigo_producto=str(row.get("TDT_CODIGO", "")).strip(),
            descripcion=row.get("TDT_DESCRIPCION"),
            cantidad=row.get("TDT_CANTIDAD", 0),
            precio=row.get("TDT_PRECIO", 0),
            total=row.get("TDT_TOTAL"),
        )
