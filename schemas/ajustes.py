from typing import Optional, Any
from pydantic import BaseModel, ConfigDict, field_validator
from schemas.writeback import parse_safe_float


def decode_dbisam_time(ms_value: Any) -> str:
    if not isinstance(ms_value, int):
        try:
            ms_value = int(ms_value)
        except (ValueError, TypeError):
            return "00:00:00"
    h = ms_value // (1000 * 3600)
    m = (ms_value % (1000 * 3600)) // (1000 * 60)
    s = (ms_value % (1000 * 60)) // 1000
    return f"{h:02d}:{m:02d}:{s:02d}"


class AjusteInventarioSchema(BaseModel):
    model_config = ConfigDict(extra="ignore")

    codigo: str
    delta: float
    motivo: Optional[str] = None
    hora: Optional[int] = None
    hora_str: Optional[str] = None
    fecha: Optional[str] = None
    costo: Optional[float] = None

    @field_validator("delta", "costo", mode="before")
    @classmethod
    def validate_numbers(cls, v: Any) -> Optional[float]:
        return parse_safe_float(v)

    def model_post_init(self, __context: Any) -> None:
        if self.hora is not None and not self.hora_str:
            self.hora_str = decode_dbisam_time(self.hora)
