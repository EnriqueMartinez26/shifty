# Suite de autorizacion y aislamiento entre tiendas

Prueba permanente de quien puede llamar cada endpoint y de que una tienda
nunca alcanza ni ve los datos de otra. Corre en SQLite como la suite de
integracion, asi que prueba la **capa de aplicacion** (filtros `store_id` y
chequeos de rol), que CLAUDE.md §2 exige que se sostenga sin RLS.

```
uv run --frozen pytest -q -p no:cacheprovider tests/security
```

## Que hay

| Archivo | Prueba |
| --- | --- |
| `rutas.py` | La tabla: una fila por ruta (verbo + path exacto de FastAPI) con roles permitidos, alcance por tienda y una fabrica de request minimo. |
| `mundo.py` | Dos tiendas (alfa y beta) con la misma forma de datos, actores frescos por test y fabricas de recursos. |
| `test_inventario_de_rutas.py` | Toda ruta de la app tiene fila; la fila no contradice a las dependencias del router; guarda de suspension en el panel; `ge` y `le` en todo numerico. |
| `test_matriz_de_roles.py` | Cada ruta contra los seis roles; segunda pasada con la tienda suspendida (402, lecturas y escrituras permitidas); portal de una tienda suspendida. |
| `test_idor_entre_tiendas.py` | Actor de alfa con ids de beta en path, query y body: 404/403 y ni un dato de beta en la respuesta. Tambien con el superadmin sentado en alfa. |
| `test_caminos_de_abuso.py` | Topes de OTP, bloqueo de login, reuso de refresh, webhooks forjados, idempotencia entre clientes, reservas repetidas. |
| `test_entrada_hostil.py` | Cotas numericas fuera de rango y caracteres de control/NUL en cada campo de texto de cada body. |
| `test_errores_sin_fugas.py` | Todo error sale en el sobre canonico, sin traza, SQL ni datos ajenos. |

La rafaga concurrente y el NUL de punta a punta necesitan Postgres: viven en
`tests/postgres/test_pg_seguridad_rafaga_y_nul.py`.

## Agregaste un endpoint: agrega su fila

`test_inventario_de_rutas.py` falla con la ruta nueva en el mensaje. Para
cerrarlo:

1. **Verifica en el codigo quien pasa**, no en la doc: la dependencia del
   router (`get_current_staff`, `get_current_admin`, `get_current_user`,
   `get_current_global_admin`) y el chequeo del handler (`require_roles`,
   `_require_payment_admin`, comparaciones de `user.role`).
2. **Escribi la fabrica** en `rutas.py`: `async def _mi_ruta(m, a, t) ->
   Llamada`. `a` es quien llama (con su tienda de contexto) y `t` la tienda
   duena del recurso. Toma los ids de `t` y, si la ruta modifica o borra,
   crea un recurso fresco (`await m.servicio(t)`, `await m.turno(t)`...) para
   que el orden de los tests no importe. En rutas publicas la tienda del
   request es `a.tienda.id` y el recurso es de `t`.
3. **Agrega la fila** a `TABLA`:

   ```python
   R("POST", "/cosas/{public_id}/hacer", ADMINS, A.RECURSO, _mi_ruta, idor=IDOR_POR_ID),
   ```

   - `permitidos`: `TODOS`, `PERSONAL`, `ADMINS`, `OPERATIVOS`, `SOLO_SUPER`
     o `SOLO_OTP` (o un `frozenset` propio si ninguno describe la ruta).
   - `alcance`: `RECURSO` si nombra un recurso de la tienda por id (en el
     path, el query o el body), `PROPIA` si opera sobre "mi tienda",
     `PUBLICA_TIENDA` si es del portal con `store_public_id`, `SUPERADMIN`,
     `CUENTA` (la propia cuenta) o `PUBLICA` (publica por diseno).
   - `ok`: solo si el exito no es 200/201/204 (un redirect, por ejemplo).
   - `idor`: obligatorio en `RECURSO`. `IDOR_POR_ID` si el id va en el path,
     `IDOR_EN_BODY` si va en el body.
4. Corre la suite. Si un rol permitido no pasa, la fabrica esta mal o la
   tabla esta mal; si pasa uno que no deberia, encontraste un defecto.

## Cuando la suite encuentra un defecto

No se arregla la app desde esta suite. El caso se marca en el diccionario
de defectos del archivo (`DEFECTOS_MATRIZ`, `DEFECTOS_IDOR`,
`DEFECTOS_INVISIBLES`, `DEFECTOS_NUL`) con un id `SEG-NN`, la severidad, la
evidencia y la causa sospechada. Queda como `xfail(strict=True,
raises=Defecto)`: cuando alguien lo arregle, el test pasa, el xfail estricto
falla y la fila se borra. `raises=Defecto` hace que una fabrica rota no se
disfrace de defecto conocido.

## Lo que esta suite no prueba

- RLS de Postgres: `tests/postgres/test_pg_rls.py`.
- Concurrencia real: `tests/postgres/`.
- Que la tabla refleje la intencion de producto: refleja el codigo. Las
  diferencias declaradas estan en `docs/ROLE_MATRIX.md`.
