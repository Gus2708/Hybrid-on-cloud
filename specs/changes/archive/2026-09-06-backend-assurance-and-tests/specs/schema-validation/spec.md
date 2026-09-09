# Delta Spec: schema-validation

## ADDED Requirements

### Requirement: schema-validation/writeback-item — Validación de items de orden de cambio
The system MUST validate the shape, types, and constraints of writeback item records before feeding them into GUI or database automation routines.

#### Scenario: Valid writeback item parsing
- GIVEN a Supabase record dictionary with `id=123`, `codigo_producto="PROD-01"`, `delta=5`, `costo=10.5` and valid order metadata
- WHEN parsed through `WritebackItemSchema.model_validate(record)`
- THEN an instance with typed numeric and string attributes is returned successfully.

#### Scenario: Rejection of invalid delta or missing required fields
- GIVEN a record dictionary where `delta` is null or `codigo_producto` is absent
- WHEN validation is attempted
- THEN a `ValidationError` is raised, detailing the missing or malformed fields, without triggering downstream processing.

#### Scenario: Tolerance for extra metadata columns
- GIVEN a record dictionary containing unexpected additional columns from Supabase
- WHEN validated
- THEN the extra columns are ignored without raising errors.

### Requirement: schema-validation/sync-records — Validación de transacciones de ventas y ajustes
The system MUST validate raw sales headers, sales details, and inventory adjustment payloads before submitting them to cloud sync or local caches.

#### Scenario: Valid sales header extraction
- GIVEN a row dictionary from `VENTAS_CABECERA.csv` with valid invoice number, date, and client identifier
- WHEN parsed through `VentaCabeceraSchema`
- THEN sanitized and normalized attributes are extracted.

#### Scenario: Decimal normalization for currency formats
- GIVEN currency or numeric fields formatted with Venezuelan commas (e.g. `"12,50"`) or standard dots (e.g. `"12.50"`)
- WHEN validated through the schema
- THEN they are normalized to standard Python `float` or `Decimal` values.
