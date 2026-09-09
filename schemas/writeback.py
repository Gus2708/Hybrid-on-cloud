from typing import Optional, Any
from pydantic import BaseModel, ConfigDict, field_validator


def parse_safe_float(v: Any) -> Optional[float]:
    if v is None or v == "":
        return None
    if isinstance(v, (int, float)):
        return float(v)
    if isinstance(v, str):
        cleaned = v.strip().replace("Bs.", "").replace("Bs", "").replace("$", "").strip()
        if not cleaned:
            return None
        # Si tiene coma decimal venezolana (ej. 12,50)
        if "," in cleaned and "." not in cleaned:
            cleaned = cleaned.replace(",", ".")
        elif "," in cleaned and "." in cleaned:
            # Si tiene miles y decimales
            cleaned = cleaned.replace(".", "").replace(",", ".")
        return float(cleaned)
    return float(v)


class WritebackItemSchema(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: int
    orden_id: int
    codigo_producto: str
    delta: float
    descripcion: Optional[str] = None
    existencia_actual: Optional[float] = None
    nueva_existencia: Optional[float] = None
    costo: Optional[float] = None
    precio_actual: Optional[float] = None
    nuevo_precio: Optional[float] = None
    nueva_descripcion: Optional[str] = None
    nueva_referencia: Optional[str] = None
    backend_intentos: Optional[int] = 0

    @field_validator("delta", mode="before")
    @classmethod
    def validate_delta(cls, v: Any) -> float:
        val = parse_safe_float(v)
        if val is None:
            raise ValueError("El campo 'delta' no puede ser nulo o vacío.")
        return val

    @field_validator("costo", "precio_actual", "nuevo_precio", "existencia_actual", "nueva_existencia", mode="before")
    @classmethod
    def validate_decimals(cls, v: Any) -> Optional[float]:
        return parse_safe_float(v)
