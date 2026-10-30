"""Behavior of detail-line filtering against the product master.

Sales-detail lines pointing at a product that no longer exists locally must not
be uploaded (they violate fk_ventas_detalle_producto) nor be counted in the
integrity check.
"""
from sync_utils import filter_valid_detail_rows, count_valid_detail_rows


def _row(code):
    return {"TBT_CODIGO": code, "TBT_DOCUMENTO": "1"}


def test_keeps_rows_whose_product_exists():
    rows = [_row("A1"), _row("B2")]
    assert filter_valid_detail_rows(rows, {"A1", "B2"}) == rows


def test_drops_rows_whose_product_is_gone():
    rows = [_row("A1"), _row("GONE")]
    assert filter_valid_detail_rows(rows, {"A1"}) == [_row("A1")]


def test_ignores_whitespace_around_codes():
    assert filter_valid_detail_rows([_row(" A1 ")], {"A1"}) == [_row(" A1 ")]


def test_empty_master_disables_filter_to_avoid_dropping_everything():
    rows = [_row("A1")]
    assert filter_valid_detail_rows(rows, set()) == rows


def test_count_valid_detail_rows_reads_both_csvs(tmp_path):
    maestro = tmp_path / "maestro.csv"
    detalle = tmp_path / "detalle.csv"
    maestro.write_text("CODIGO_INTERNO\nA1\nB2\n", encoding="utf-8")
    detalle.write_text("TBT_CODIGO\nA1\nB2\nGONE\nA1\n", encoding="utf-8")
    assert count_valid_detail_rows(str(detalle), str(maestro)) == 3


def test_count_falls_back_to_raw_lines_when_master_missing(tmp_path):
    detalle = tmp_path / "detalle.csv"
    detalle.write_text("TBT_CODIGO\nA1\nGONE\n", encoding="utf-8")
    assert count_valid_detail_rows(str(detalle), str(tmp_path / "nope.csv")) == 2
