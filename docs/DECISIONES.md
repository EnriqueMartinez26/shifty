# Decisiones del dueño

Registro de las decisiones que el dueño del repo (Enrique) tomó o adoptó.
Es la única fuente para atribuirle una decisión: una frase en prosa no prueba
quién decidió (2026-09-25: CLAUDE.md le atribuía reglas que nunca había
visto).

## Columnas

- **ID**: `D-AAAAMMDD-NN`, con la fecha en que se adoptó y `NN` correlativo
  dentro de ese día (`-01`, `-02`, …). No se reutiliza ni se renumera.
- **Fecha**: `AAAA-MM-DD`, la misma del ID.
- **Decisión**: una línea.
- **Propuesta por**: quién la planteó.
- **Adoptada por**: quién la hizo regla. Una fila atribuible al dueño dice
  `dueño (Enrique)`; cualquier otro valor (por ejemplo `pendiente`) no
  respalda la frase en CLAUDE.md.
- **Referencia**: los commits o el PR donde se implementa o donde se
  escribió por primera vez.

## La regla

En CLAUDE.md, toda frase "decisión del dueño", "adoptada por el dueño" o
"regla del dueño" lleva el ID de una fila de esta tabla adoptada por el dueño.
Sin ID se escribe "propuesta por X, pendiente de OK del dueño". Lo verifica
`backend/tests/architecture/test_decisiones_del_dueno.py` (en CI no se salta);
las frases genéricas que piden una decisión futura ("excepción explícita del
dueño") no son una atribución y no llevan ID.

Las cuatro filas del 2026-09-09 son las reglas del dueño con las que nació
CLAUDE.md (el commit `800101c` las describe como "las reglas de Enrique"); su
fecha y su referencia son las del commit en que aparecieron por primera vez
en CLAUDE.md.

| ID | Fecha | Decisión | Propuesta por | Adoptada por | Referencia |
|----|-------|----------|---------------|--------------|------------|
| D-20260909-01 | 2026-09-09 | El alta de tiendas es solo desde el superadmin; no existe ni vuelve el registro público. | dueño (Enrique) | dueño (Enrique) | `7445ac9` (primera aparición en CLAUDE.md); implementada en `33f4b25` |
| D-20260909-02 | 2026-09-09 | La zona horaria por tienda es un flujo aparte; hoy solo Argentina. | dueño (Enrique) | dueño (Enrique) | `7445ac9` (primera aparición en CLAUDE.md) |
| D-20260909-03 | 2026-09-09 | La consolidación del panel del dueño espera su OK explícito. | dueño (Enrique) | dueño (Enrique) | `800101c` (primera aparición en CLAUDE.md) |
| D-20260909-04 | 2026-09-09 | Sin atribución de IA en commits ni PRs (nada de `Co-Authored-By` de un modelo). | dueño (Enrique) | dueño (Enrique) | `7445ac9` (primera aparición en CLAUDE.md) |
| D-20260925-01 | 2026-09-25 | Un turno en el pasado lo agenda solo la tienda (panel y lista de espera); el cliente final nunca. | Mateo | dueño (Enrique) | `13f4820`, `ff381f1`; PR [#2](https://github.com/EnriqueMartinez26/shifty/pull/2) |
| D-20260925-02 | 2026-09-25 | Todo camino que suelta un turno vence su cobro vivo (cancelar, reprogramar y liberar desde el panel, bloqueo, webhook, job de retenciones); el cliente no suelta un turno con cobro vivo. | Mateo | dueño (Enrique) | `d317e3f`, `62d2312`, `6e47bb9` (merge `d9f19e4`); PR [#2](https://github.com/EnriqueMartinez26/shifty/pull/2) |
| D-20260925-03 | 2026-09-25 | Opción A de la seña pendiente: un `pending_payment` no se reprograma desde el panel (409 `DEPOSIT_PENDING_RESCHEDULE_DENIED`); se cobra y después se mueve, o se cancela. | Mateo | dueño (Enrique) | `38a7059` (merge `623a755`); PR [#2](https://github.com/EnriqueMartinez26/shifty/pull/2) |
| D-20260925-04 | 2026-09-25 | PV-01: el email de un cliente es único por tienda; el del personal sigue único global. | Mateo | dueño (Enrique) | `a542dda` (merge `9fc2903`); PR [#2](https://github.com/EnriqueMartinez26/shifty/pull/2) |
