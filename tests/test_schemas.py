import pytest
from pydantic import ValidationError

from schemas.writeback import WritebackItemSchema
from schemas.ventas import VentaCabeceraSchema, VentaDetalleSchema
from schemas.ajustes import AjusteInventarioSchema


class TestWritebackItemSchema:
    def test_valid_writeback_item(self):
        data = {
            "id": 101,
            "orden_id": 5,
            "codigo_producto": "00-001-002",
            "descripcion": "Martillo 16oz",
            "delta": 3.0,
            "existencia_actual": 10.0,
            "nueva_existencia": 13.0,
            "costo": 4.50,
            "precio_actual": 8.00,
            "nuevo_precio": 9.50,
            "extra_cloud_column": "ignored_value",
        }
        item = WritebackItemSchema.model_validate(data)
        assert item.id == 101
        assert item.orden_id == 5
        assert item.codigo_producto == "00-001-002"
        assert item.delta == 3.0
        assert item.costo == 4.50
        assert item.nuevo_precio == 9.50

    def test_missing_required_fields_raises_error(self):
        # Falta delta y codigo_producto
        data = {"id": 102, "orden_id": 5}
        with pytest.raises(ValidationError) as exc_info:
            WritebackItemSchema.model_validate(data)
        errors = str(exc_info.value)
        assert "delta" in errors or "codigo_producto" in errors

    def test_null_delta_raises_validation_error(self):
        data = {
            "id": 103,
            "orden_id": 5,
            "codigo_producto": "00-001-003",
            "delta": None,
        }
        with pytest.raises(ValidationError):
            WritebackItemSchema.model_validate(data)

    def test_comma_decimal_coercion(self):
        data = {
            "id": 104,
            "orden_id": 5,
            "codigo_producto": "00-001-004",
            "delta": "5,5",
            "costo": "12,75",
        }
        item = WritebackItemSchema.model_validate(data)
        assert item.delta == 5.5
        assert item.costo == 12.75


class TestVentasSchemas:
    def test_valid_venta_cabecera(self):
        row = {
            "THT_DOCUMENTO": "12345",
            "THT_FECHA": "2026-06-20",
            "THT_CLIENTE": "C-001",
            "THT_TOTALNETO": "100,50",
            "THT_TOTALIMPUESTO": "16,08",
            "THT_TOTALBRUTO": "116,58",
            "THT_IDUNICO": "999",
        }
        cab = VentaCabeceraSchema.from_csv_row(row)
        assert cab.documento == "00012345"
        assert cab.total_neto == 100.50
        assert cab.total_impuesto == 16.08
        assert cab.id_unico == 999

    def test_valid_venta_detalle(self):
        row = {
            "TDT_DOCUMENTO": "12345",
            "TDT_CODIGO": "01-001",
            "TDT_DESCRIPCION": "Tornillo 2x1",
            "TDT_CANTIDAD": "10,0",
            "TDT_PRECIO": "2,50",
            "TDT_TOTAL": "25,00",
        }
        det = VentaDetalleSchema.from_csv_row(row)
        assert det.documento == "00012345"
        assert det.codigo_producto == "01-001"
        assert det.cantidad == 10.0
        assert det.precio == 2.50


class TestAjusteInventarioSchema:
    def test_valid_ajuste(self):
        data = {
            "codigo": "05-001",
            "delta": -2.0,
            "motivo": "Merma",
            "hora": 3661000,
        }
        ajuste = AjusteInventarioSchema.model_validate(data)
        assert ajuste.codigo == "05-001"
        assert ajuste.delta == -2.0
        assert ajuste.hora_str == "01:01:01"
