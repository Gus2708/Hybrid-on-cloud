# Tasks: writeback-guardrails

## Review Workload Forecast
Estimated changed lines: 100-180
Estimated product files: 3-5
Target budget: 800 lines and 15 files
Hard limit: 1000 lines and 25 files
Budget risk: Low
Independent slices possible: No
Shared production files across slices: No
Forecast basis: proposal/spec/design focused exploration

## Delivery Plan
Strategy: single-pr
Model: whole
PR mode: draft
PR creation point: final verify only
Current delivery unit: whole

### Whole Delivery
Planned branch/base: sdd/writeback-guardrails -> main
Scope: Guardrails y verificadores de ventanas modales y bloqueantes en HybridLiteOS para hybrid_health, abrir_hybrid y listener_writeback.

## Slice: whole — Guardrails y Verificadores de Ventanas de HybridLiteOS

### Phase 1: Win32 Window Inspection and Modal Detection
- [x] 1.1 Inspección y detección de ventanas bloqueantes y modales
  - [x] 1.1.a Safety Net evidence: verificar ausencia de ventanas_bloqueantes y verificar_hybrid_listo en hybrid_health.py.
  - [x] 1.1.b RED failing test: test unitario en tests/test_hybrid_health.py para ventanas deshabilitadas (IsWindowEnabled=False), popups activos (GetLastActivePopup) y clases Delphi modales (TMessageForm, #32770, TForm_BusquedaConfDb).
  - [x] 1.1.c GREEN implementation: implementar ventanas_bloqueantes() y verificar_hybrid_listo() en hybrid_health.py.
  - [x] 1.1.d TRIANGULATE second case: test para instancia limpia (sin popups, habilitada) que confirme listo=True.
  - [x] 1.1.e REFACTOR evidence: optimizar manejo de excepciones Win32 y timeouts.

### Phase 2: Safe Instance Adoption Guard
- [x] 2.1 Validación de estado listo antes de adoptar ventana MAIN existente
  - [x] 2.1.a Safety Net evidence: inspeccionar paso 1.5 en abrir_hybrid.py.
  - [x] 2.1.b RED failing test: test que simula MAIN existente con ventanas modales bloqueantes y verifica que asegurar_hybrid() rechaza adoptarla.
  - [x] 2.1.c GREEN implementation: integrar verificar_hybrid_listo() en el paso 1.5 de abrir_hybrid.py.
  - [x] 2.1.d TRIANGULATE second case: verificar que si la instancia existente está libre de modales y habilitada, se adopta con éxito.
  - [x] 2.1.e REFACTOR evidence: mensajes de log claros y preservación del target PID.

### Phase 3: Pre-flight Guardrail in Writeback Listener
- [x] 3.1 Postergación no destructiva previa a control_seguro
  - [x] 3.1.a Safety Net evidence: verificar comportamiento actual de procesar_pendientes() en listener_writeback.py.
  - [x] 3.1.b RED failing test: test en tests/test_listener_writeback.py donde Hybrid reporta modales abiertos; verificar que control_seguro no se activa y backend_intentos no se incrementa.
  - [x] 3.1.c GREEN implementation: añadir chequeo pre-vuelo en procesar_pendientes() antes de control_seguro.
  - [x] 3.1.d TRIANGULATE second case: verificar que cuando Hybrid está libre, la ejecución procede normalmente.
  - [x] 3.1.e REFACTOR evidence: ejecución de ruff check . y suite completa de tests de pytest.
