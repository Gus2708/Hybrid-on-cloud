import pytest

import actualizar_inventario


class TestDescripcionUtil:
    @pytest.mark.parametrize("desc", [".", "..", "", "-", "SIN DESCRIPCION", "12", "a."])
    def test_rejects_placeholder_descriptions(self, desc):
        assert actualizar_inventario.descripcion_util(desc) is False

    @pytest.mark.parametrize("desc", [
        "CAJETIN 2X4 PLAST CREOLE",
        "TEE PVC 4 AGUAS NEGRAS UNITECA ZETA",
        "Lija 3M N°80",
        "Cal",
    ])
    def test_accepts_real_descriptions(self, desc):
        assert actualizar_inventario.descripcion_util(desc) is True
