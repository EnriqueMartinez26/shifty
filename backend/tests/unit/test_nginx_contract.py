"""Contrato de los nginx: edge de desarrollo, edge de produccion y el de la SPA.

nginx no tiene suite propia: `nginx -t` solo dice que la sintaxis es valida,
no que el proxy reuse conexiones, que un 502 llegue al front como JSON o que
el log no guarde el telefono del cliente. Este test lee los .conf como texto
(un parser minimo de bloques y directivas) y fija esas propiedades, para que
dev y prod no se separen y ningun cambio las pierda en silencio.

Trampas de nginx que el contrato vigila:
- `proxy_set_header` y `add_header` se heredan SOLO si el nivel actual no
  define ninguno: uno solo en un location borra todos los del server.
- Un `return` a nivel server corre antes de elegir location.
- Los nombres de zona de memoria compartida son globales: `upstream` y
  `limit_req_zone` no pueden repetir nombre.
"""

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parents[3]
EDGE_DEV = RAIZ / "nginx" / "nginx.conf"
EDGE_PROD = RAIZ / "nginx" / "nginx.prod.conf"
EDGE_DOCKERFILE = RAIZ / "nginx" / "Dockerfile"
SPA = RAIZ / "frontend" / "nginx.conf"

EDGES = pytest.mark.parametrize("ruta", [EDGE_DEV, EDGE_PROD], ids=["dev", "prod"])


# --- parser minimo -----------------------------------------------------------


@dataclass(frozen=True)
class _Token:
    texto: str
    # Entre comillas: nunca es `{`, `}` ni `;` aunque lo parezca.
    literal: bool


@dataclass
class Directiva:
    nombre: str
    args: tuple[str, ...]
    hijos: list["Directiva"] | None = field(default=None)

    @property
    def bloque(self) -> list["Directiva"]:
        assert self.hijos is not None, f"{self.nombre} no es un bloque"
        return self.hijos


def _leer_citado(texto: str, inicio: int) -> tuple[str, int]:
    comilla = texto[inicio]
    partes: list[str] = []
    i = inicio + 1
    while i < len(texto) and texto[i] != comilla:
        if texto[i] == "\\" and i + 1 < len(texto):
            partes.append(texto[i + 1])
            i += 2
            continue
        partes.append(texto[i])
        i += 1
    assert i < len(texto), "comilla sin cerrar"
    return "".join(partes), i + 1


def _tokenizar(texto: str) -> list[_Token]:
    tokens: list[_Token] = []
    i = 0
    while i < len(texto):
        c = texto[i]
        if c.isspace():
            i += 1
        elif c == "#":
            fin = texto.find("\n", i)
            i = len(texto) if fin == -1 else fin
        elif c in "{};":
            tokens.append(_Token(c, literal=False))
            i += 1
        elif c in "\"'":
            valor, i = _leer_citado(texto, i)
            tokens.append(_Token(valor, literal=True))
        else:
            j = i
            while j < len(texto) and not texto[j].isspace() and texto[j] not in "{};":
                j += 1
            tokens.append(_Token(texto[i:j], literal=False))
            i = j
    return tokens


def parsear(texto: str) -> list[Directiva]:
    raiz: list[Directiva] = []
    pila = [raiz]
    actual: list[str] = []
    for token in _tokenizar(texto):
        if token.literal or token.texto not in "{};":
            actual.append(token.texto)
        elif token.texto == ";":
            assert actual, "`;` suelto"
            pila[-1].append(Directiva(actual[0], tuple(actual[1:])))
            actual = []
        elif token.texto == "{":
            assert actual, "bloque sin nombre"
            hijos: list[Directiva] = []
            pila[-1].append(Directiva(actual[0], tuple(actual[1:]), hijos))
            pila.append(hijos)
            actual = []
        else:
            assert not actual and len(pila) > 1, "`}` desbalanceada"
            pila.pop()
    assert len(pila) == 1 and not actual, "bloque sin cerrar"
    return raiz


def leer(ruta: Path) -> list[Directiva]:
    """Contexto `http`: los archivos de conf.d se incluyen dentro de `http {}`."""
    return parsear(ruta.read_text(encoding="utf-8"))


def todas(bloque: list[Directiva], nombre: str) -> list[Directiva]:
    return [d for d in bloque if d.nombre == nombre]


def una(bloque: list[Directiva], nombre: str) -> Directiva:
    encontradas = todas(bloque, nombre)
    assert len(encontradas) == 1, f"se esperaba un `{nombre}`: {encontradas}"
    return encontradas[0]


def bloque_con(bloque: list[Directiva], nombre: str, *args: str) -> list[Directiva]:
    for d in bloque:
        if d.nombre == nombre and d.args == args and d.hijos is not None:
            return d.hijos
    raise AssertionError(f"falta el bloque `{nombre} {' '.join(args)}`")


def servidores(http: list[Directiva]) -> list[list[Directiva]]:
    return [d.bloque for d in todas(http, "server")]


def server_de_la_app(http: list[Directiva]) -> list[Directiva]:
    """El server que sirve la app (en prod, el de 443; el de 80 solo redirige)."""
    candidatos = [
        s
        for s in servidores(http)
        if any(d.nombre == "location" and d.args == ("/api/",) for d in s)
    ]
    assert len(candidatos) == 1, "se esperaba un solo server con /api/"
    return candidatos[0]


def locations(server: list[Directiva]) -> list[Directiva]:
    return todas(server, "location")


def location(server: list[Directiva], *args: str) -> list[Directiva]:
    return bloque_con(server, "location", *args)


def locations_con_proxy(http: list[Directiva]) -> list[Directiva]:
    return [
        loc
        for server in servidores(http)
        for loc in locations(server)
        if todas(loc.bloque, "proxy_pass")
    ]


def es_de_api(loc: Directiva) -> bool:
    """Prefijo o exacta bajo /api/, o regex anclada en ^/api/."""
    patron = loc.args[-1]
    if loc.args[0] in {"~", "~*"}:
        return patron.startswith("^/api/")
    return patron.startswith("/api/")


def locations_de_api(server: list[Directiva]) -> list[Directiva]:
    return [loc for loc in locations(server) if es_de_api(loc)]


def cabeceras_proxy(bloque: list[Directiva]) -> dict[str, str]:
    return {d.args[0].lower(): d.args[1] for d in todas(bloque, "proxy_set_header")}


def efectivo(nombre: str, *niveles: list[Directiva]) -> tuple[str, ...] | None:
    """Valor heredado de una directiva simple: gana el nivel mas especifico."""
    for nivel in reversed(niveles):
        encontradas = todas(nivel, nombre)
        if encontradas:
            return encontradas[-1].args
    return None


# --- F0-01: upstreams con keepalive y DNS en runtime --------------------------


def test_el_parser_entiende_bloques_comillas_y_comentarios() -> None:
    conf = parsear(
        "# comentario { ;\n"
        "server { listen 80; location @x { return 503 '{\"a\":1}'; } }\n"
    )
    loc = location(conf[0].bloque, "@x")
    assert una(loc, "return").args == ("503", '{"a":1}')


def test_la_imagen_del_edge_fija_una_version_con_resolve_en_upstream() -> None:
    # `server ... resolve` dentro de `upstream` existe desde nginx 1.27.3. Un
    # tag flotante (`1.27-alpine`) cacheado viejo en el servidor rompe el
    # arranque; fijar el parche lo vuelve reproducible.
    texto = EDGE_DOCKERFILE.read_text(encoding="utf-8")
    match = re.search(r"^FROM nginx:(\d+)\.(\d+)\.(\d+)-alpine\s*$", texto, re.M)
    assert match, "el Dockerfile del edge debe fijar nginx:X.Y.Z-alpine"
    version = tuple(int(parte) for parte in match.groups())
    assert version >= (1, 27, 3)


@EDGES
def test_resuelve_con_el_dns_de_docker_y_ttl_corto(ruta: Path) -> None:
    resolver = una(leer(ruta), "resolver")
    assert resolver.args[0] == "127.0.0.11"
    assert "valid=5s" in resolver.args
    assert "ipv6=off" in resolver.args


@EDGES
@pytest.mark.parametrize(
    ("nombre", "destino", "keepalive_minimo"),
    [("api", "backend:8000", 32), ("spa", "frontend:3000", 8)],
)
def test_upstream_resuelve_en_runtime_y_reusa_conexiones(
    ruta: Path, nombre: str, destino: str, keepalive_minimo: int
) -> None:
    # `resolve` re-resuelve el nombre con el TTL del resolver y agrega TODOS
    # los registros A como servidores del grupo: con replicas del backend,
    # nginx reparte entre todas y sigue las IP nuevas tras un recreate, sin
    # reload. Exige `zone` (el grupo vive en memoria compartida).
    upstream = bloque_con(leer(ruta), "upstream", nombre)
    assert una(upstream, "zone").args
    assert [s.args for s in todas(upstream, "server")] == [(destino, "resolve")]
    assert int(una(upstream, "keepalive").args[0]) >= keepalive_minimo


@EDGES
def test_el_keepalive_al_backend_vence_antes_que_el_de_uvicorn(ruta: Path) -> None:
    # uvicorn cierra una conexion ociosa a los 5 s (--timeout-keep-alive por
    # defecto). Si nginx la reusa justo cuando uvicorn la cierra, el request
    # termina en 502; nginx tiene que soltarla antes.
    upstream = bloque_con(leer(ruta), "upstream", "api")
    assert una(upstream, "keepalive_timeout").args == ("4s",)


@EDGES
def test_todo_proxy_pass_va_por_un_upstream_con_keepalive(ruta: Path) -> None:
    proxies = locations_con_proxy(leer(ruta))
    assert proxies
    for loc in proxies:
        destino = una(loc.bloque, "proxy_pass").args[0]
        assert re.fullmatch(r"http://(api|spa)(/\S*)?", destino), loc.args
        # Sin HTTP/1.1 y sin vaciar Connection, nginx manda "close" y el
        # keepalive del upstream no se usa nunca.
        assert una(loc.bloque, "proxy_http_version").args == ("1.1",), loc.args
        cabeceras = cabeceras_proxy(loc.bloque)
        assert cabeceras.get("connection") == "", loc.args
        assert "upgrade" not in cabeceras, loc.args


@EDGES
def test_todo_proxy_reescribe_las_cabeceras_de_origen(ruta: Path) -> None:
    for loc in locations_con_proxy(leer(ruta)):
        cabeceras = cabeceras_proxy(loc.bloque)
        assert cabeceras.get("host") == "$host", loc.args
        assert cabeceras.get("x-real-ip") == "$remote_addr", loc.args
        # Reescribir, nunca agregar: con $proxy_add_x_forwarded_for el primer
        # elemento lo elige el cliente y evade el rate limit del backend.
        assert cabeceras.get("x-forwarded-for") == "$remote_addr", loc.args
        assert cabeceras.get("x-forwarded-proto") == "$scheme", loc.args


@EDGES
def test_las_zonas_de_memoria_compartida_no_repiten_nombre(ruta: Path) -> None:
    http = leer(ruta)
    nombres = [
        una(bloque_con(http, "upstream", u), "zone").args[0] for u in ("api", "spa")
    ]
    for d in http:
        if d.nombre in {"limit_req_zone", "limit_conn_zone"}:
            zona = next(a for a in d.args if a.startswith("zone="))
            nombres.append(zona.removeprefix("zone=").split(":")[0])
        if d.nombre == "proxy_cache_path":
            zona = next(a for a in d.args if a.startswith("keys_zone="))
            nombres.append(zona.removeprefix("keys_zone=").split(":")[0])
    assert len(nombres) == len(set(nombres)), nombres


# --- F0-07 / F0-08: compresion y buffers --------------------------------------

TIPOS_COMPRIMIDOS = {
    "text/css",
    "application/javascript",
    "text/javascript",
    "application/json",
    "image/svg+xml",
}


@EDGES
def test_comprime_texto_y_nunca_imagenes_binarias(ruta: Path) -> None:
    http = leer(ruta)
    assert una(http, "gzip").args == ("on",)
    assert una(http, "gzip_vary").args == ("on",)
    # `any`: tambien lo que viene del backend y de la SPA (el edge es proxy).
    assert una(http, "gzip_proxied").args == ("any",)
    assert una(http, "gzip_comp_level").args == ("5",)
    assert una(http, "gzip_min_length").args == ("1024",)
    tipos = set(una(http, "gzip_types").args)
    assert TIPOS_COMPRIMIDOS <= tipos
    # png/jpg/webp ya vienen comprimidos: recomprimir es CPU sin ahorro.
    assert {t for t in tipos if t.startswith("image/")} == {"image/svg+xml"}


@EDGES
def test_auth_no_se_comprime(ruta: Path) -> None:
    # BREACH: una respuesta comprimida que refleja entrada del atacante junto
    # a un secreto (tokens de /auth/) filtra el secreto por el tamanio.
    server = server_de_la_app(leer(ruta))
    auth = location(server, "/api/auth/")
    assert una(auth, "gzip").args == ("off",)
    assert una(auth, "proxy_pass").args == ("http://api",)
    api = location(server, "/api/")
    assert [r.args for r in todas(auth, "rewrite")] == [
        r.args for r in todas(api, "rewrite")
    ]


@EDGES
def test_los_buffers_del_proxy_no_vuelcan_a_disco_una_respuesta_mediana(
    ruta: Path,
) -> None:
    # Con el default (8 x 4k) toda respuesta > 32 KB, la disponibilidad
    # incluida, iba a un archivo temporal antes de salir.
    http = leer(ruta)
    for server in servidores(http):
        for loc in locations(server):
            if not todas(loc.bloque, "proxy_pass"):
                continue
            niveles = (http, server, loc.bloque)
            assert efectivo("proxy_buffer_size", *niveles) == ("16k",), loc.args
            assert efectivo("proxy_buffers", *niveles) == ("16", "16k"), loc.args
            assert efectivo("proxy_busy_buffers_size", *niveles) == ("32k",)


# --- F0-09: rate limit y conexiones por IP en el edge -------------------------


def _tasa_por_segundo(http: list[Directiva], zona: str) -> int:
    for d in todas(http, "limit_req_zone"):
        if f"zone={zona}:10m" in d.args:
            assert d.args[0] == "$binary_remote_addr", d.args
            rate = next(a for a in d.args if a.startswith("rate="))
            match = re.fullmatch(r"rate=(\d+)r/s", rate)
            assert match, rate
            return int(match.group(1))
    raise AssertionError(f"falta limit_req_zone zone={zona}:10m")


def _limit_req(loc: list[Directiva]) -> tuple[str, int]:
    args = una(loc, "limit_req").args
    assert "nodelay" in args, args
    zona = next(a for a in args if a.startswith("zone="))
    burst = next(a for a in args if a.startswith("burst="))
    return zona.removeprefix("zone="), int(burst.removeprefix("burst="))


# Mercado Pago reintenta en rafaga desde pocas IP: su webhook tiene zona propia
# para que el edge no le devuelva 429 antes de que la app verifique el HMAC.
WEBHOOK_MP = ("=", "/api/payments/webhooks/mercadopago")


def _zona_esperada(loc: Directiva) -> str:
    if loc.args == ("/api/auth/",):
        return "auth"
    if loc.args == WEBHOOK_MP:
        return "webhooks"
    return "api"


def _conexiones_por_ip(http: list[Directiva], server: list[Directiva]) -> int:
    limite = efectivo("limit_conn", http, server)
    assert limite is not None and limite[0] == "perip", limite
    return int(limite[1])


@EDGES
def test_el_edge_corta_inundaciones_por_ip(ruta: Path) -> None:
    http = leer(ruta)
    _tasa_por_segundo(http, "api")
    _tasa_por_segundo(http, "auth")
    _tasa_por_segundo(http, "webhooks")
    assert una(http, "limit_conn_zone").args == (
        "$binary_remote_addr",
        "zone=perip:10m",
    )
    # 429 y no el 503 por defecto: el front y el backoff lo leen como limite.
    assert una(http, "limit_req_status").args == ("429",)
    assert una(http, "limit_conn_status").args == ("429",)
    # Cada rechazo es una linea del error log (con la query): warn, no error.
    assert una(http, "limit_req_log_level").args == ("warn",)
    assert una(http, "limit_conn_log_level").args == ("warn",)
    server = server_de_la_app(http)
    assert _conexiones_por_ip(http, server) > 0
    apis = locations_de_api(server)
    assert apis
    for loc in apis:
        zona, _burst = _limit_req(loc.bloque)
        assert zona == _zona_esperada(loc), loc.args


def test_produccion_limita_muy_por_encima_de_la_app() -> None:
    # Solo corta inundaciones: el limite fino (por ruta, por sujeto) es el de
    # core/rate_limit.py. Si el edge cortara antes, el front veria un 429 sin
    # el Retry-After calculado por la app.
    http = leer(EDGE_PROD)
    assert _tasa_por_segundo(http, "api") == 20
    assert _tasa_por_segundo(http, "auth") == 3
    server = server_de_la_app(http)
    assert _limit_req(location(server, "/api/")) == ("api", 40)
    assert _limit_req(location(server, "/api/auth/")) == ("auth", 6)
    assert _tasa_por_segundo(http, "webhooks") == 10
    assert _limit_req(location(server, *WEBHOOK_MP)) == ("webhooks", 60)
    assert _conexiones_por_ip(http, server) == 40


def test_desarrollo_no_limita_mas_que_produccion() -> None:
    # Las simulaciones locales salen todas de una IP: dev puede ser mas laxo,
    # nunca mas estricto (un 429 del edge falsearia la medicion).
    dev, prod = leer(EDGE_DEV), leer(EDGE_PROD)
    for zona in ("api", "auth", "webhooks"):
        assert _tasa_por_segundo(dev, zona) >= _tasa_por_segundo(prod, zona)
    assert _conexiones_por_ip(dev, server_de_la_app(dev)) >= _conexiones_por_ip(
        prod, server_de_la_app(prod)
    )


# --- F0-10: errores del edge en JSON canonico ---------------------------------

# (codigos, named location, status, error_code, Retry-After)
ERRORES_DEL_EDGE = [
    (("502", "503", "504"), "@api_down", "503", "UPSTREAM_UNAVAILABLE", "5"),
    # Mismo error_code que el tope de cuerpo de la app (security_middleware):
    # el front lee un solo codigo para el mismo evento.
    (("413",), "@request_too_large", "413", "REQUEST_TOO_LARGE", None),
    (("429",), "@rate_limited", "429", "RATE_LIMITED", "1"),
]


def _cabeceras_agregadas(bloque: list[Directiva]) -> dict[str, str]:
    return {d.args[0].lower(): d.args[1] for d in todas(bloque, "add_header")}


@EDGES
def test_server_tokens_apagado_para_todo_el_edge(ruta: Path) -> None:
    http = leer(ruta)
    assert una(http, "server_tokens").args == ("off",)
    for server in servidores(http):
        assert efectivo("server_tokens", http, server) == ("off",)


@EDGES
def test_toda_location_con_add_header_repite_los_del_server(ruta: Path) -> None:
    # Un add_header en un location DESCARTA los del server: sin repetirlos, la
    # respuesta de error sale sin nosniff, sin DENY y (prod) sin HSTS.
    for server in servidores(leer(ruta)):
        del_server = set(_cabeceras_agregadas(server))
        for loc in locations(server):
            propias = set(_cabeceras_agregadas(loc.bloque))
            if propias:
                assert del_server <= propias, (loc.args, del_server - propias)


@EDGES
def test_los_errores_de_api_del_edge_salen_en_json_canonico(ruta: Path) -> None:
    # Regla 23: un 502/504 de nginx llegaba al front como HTML y rompia el
    # parseo igual que el redirect sin /api.
    server = server_de_la_app(leer(ruta))
    for loc in locations_de_api(server):
        paginas = {d.args[:-2]: d.args[-2:] for d in todas(loc.bloque, "error_page")}
        for codigos, destino, *_ in ERRORES_DEL_EDGE:
            assert paginas.get(codigos) == ("=", destino), (loc.args, codigos)
        # Los errores que genera la APP (503 de readiness, 413 propio) pasan
        # tal cual: solo se reemplazan los que genera nginx.
        assert efectivo("proxy_intercept_errors", server, loc.bloque) in {
            None,
            ("off",),
        }


@EDGES
@pytest.mark.parametrize(
    ("destino", "status", "error_code", "retry_after"),
    [fila[1:] for fila in ERRORES_DEL_EDGE],
)
def test_la_respuesta_de_error_del_edge_es_el_sobre_de_la_app(
    ruta: Path, destino: str, status: str, error_code: str, retry_after: str | None
) -> None:
    loc = location(server_de_la_app(leer(ruta)), destino)
    # `types {}` vacio: el Content-Type no sale de la extension de la URI
    # (un /api/x.csv caido no puede responder text/csv).
    assert bloque_con(loc, "types") == []
    assert una(loc, "default_type").args == ("application/json; charset=utf-8",)
    codigo, cuerpo = una(loc, "return").args
    assert codigo == status
    payload = json.loads(cuerpo)
    assert payload["success"] is False
    assert payload["error_code"] == error_code
    assert payload["message"]
    cabeceras = _cabeceras_agregadas(loc)
    assert cabeceras.get("retry-after") == retry_after
    assert cabeceras.get("cache-control") == "no-store"
    for d in todas(loc, "add_header"):
        assert d.args[-1] == "always", d.args


@EDGES
def test_el_webhook_de_mp_se_proxea_igual_que_el_resto_de_api(ruta: Path) -> None:
    server = server_de_la_app(leer(ruta))
    webhook, api = location(server, *WEBHOOK_MP), location(server, "/api/")
    for nombre in (
        "rewrite",
        "proxy_pass",
        "proxy_http_version",
        "proxy_set_header",
        "error_page",
        "client_max_body_size",
        "proxy_connect_timeout",
        "proxy_read_timeout",
    ):
        assert [d.args for d in todas(webhook, nombre)] == [
            d.args for d in todas(api, nombre)
        ], nombre


@EDGES
def test_las_paginas_de_error_json_son_solo_de_api(ruta: Path) -> None:
    # Un error_page JSON en `/` o `/assets/` (o a nivel server, que se hereda)
    # le devolveria JSON al navegador en vez de la SPA.
    for server in servidores(leer(ruta)):
        assert not todas(server, "error_page")
        for loc in locations(server):
            if todas(loc.bloque, "error_page"):
                assert es_de_api(loc), loc.args


@EDGES
def test_la_subida_de_medios_admite_el_tope_de_la_app_mas_el_multipart(
    ruta: Path,
) -> None:
    # La app acepta 3 MiB de cuerpo (MAX_UPLOAD_BODY_BYTES); con 3m el edge
    # cortaba antes que ella lo que el multipart agrega, y el 413 no era el de
    # la app. El resto de /api sigue en 32k.
    server = server_de_la_app(leer(ruta))
    subidas = [
        location(server, "=", "/api/stores/me/media"),
        # Imagen de servicio (F1-28): mismo tope, por regex exacta.
        location(server, "~", SUBIDA_DE_SERVICIO),
    ]
    for subida in subidas:
        assert una(subida, "client_max_body_size").args == ("3200k",)
    for loc in locations_de_api(server):
        if not any(loc.bloque is subida for subida in subidas):
            assert efectivo("client_max_body_size", server, loc.bloque) == ("32k",)


SUBIDA_DE_SERVICIO = "^/api/services/[A-Za-z0-9_-]+/image$"


@pytest.mark.parametrize(
    ("uri", "calza"),
    [
        ("/api/services/01JABCDEFGHJKMNPQRSTVWXYZ0/image", True),
        ("/api/services/01JABC/image/", False),
        ("/api/services/a/b/image", False),
        ("/api/services/01JABC", False),
        ("/api/services//image", False),
    ],
)
def test_la_regex_de_subida_de_servicio_es_exacta(uri: str, calza: bool) -> None:
    # PCRE y `re` coinciden en esta clase de patron (anclas, clase y `+`).
    assert (re.fullmatch(SUBIDA_DE_SERVICIO[1:-1], uri) is not None) is calza


# --- F1-29: cache del edge para medios y catalogo publico --------------------

ZONA_DE_CACHE = "shifty_cache"
MEDIOS = "^/api/stores/media/[A-Za-z0-9_-]+$"
# Solo lo que el backend marca cacheable (decision 11): la imagen inmutable
# (F1-27) y servicios/profesionales (s-maxage=30). La vitrina, la
# disponibilidad, los previews y el OTP no pasan por la cache.
RUTAS_CACHEADAS = {
    ("~", MEDIOS),
    ("=", "/api/public/services"),
    ("=", "/api/public/staff"),
}


@EDGES
def test_el_edge_tiene_una_sola_zona_de_cache_acotada(ruta: Path) -> None:
    (cache,) = todas(leer(ruta), "proxy_cache_path")
    assert cache.args[0].startswith("/var/cache/nginx/")
    assert f"keys_zone={ZONA_DE_CACHE}:10m" in cache.args
    # Sin archivo temporal intermedio: escribe directo en el directorio.
    assert "use_temp_path=off" in cache.args
    assert any(a.startswith("max_size=") for a in cache.args)
    assert any(a.startswith("inactive=") for a in cache.args)


@EDGES
def test_solo_se_cachean_los_medios_y_el_catalogo(ruta: Path) -> None:
    http = leer(ruta)
    server = server_de_la_app(http)
    assert not todas(http, "proxy_cache")
    assert not todas(server, "proxy_cache")
    cacheadas = {
        loc.args for loc in locations(server) if todas(loc.bloque, "proxy_cache")
    }
    assert cacheadas == RUTAS_CACHEADAS


@EDGES
@pytest.mark.parametrize("args", sorted(RUTAS_CACHEADAS))
def test_la_cache_la_decide_el_backend_y_nunca_con_credenciales(
    ruta: Path, args: tuple[str, str]
) -> None:
    server = server_de_la_app(leer(ruta))
    loc = location(server, *args)
    assert una(loc, "proxy_cache").args == (ZONA_DE_CACHE,)
    # Con Authorization (panel) o con Origin (CORS, la respuesta varia por
    # origen) ni se lee ni se guarda.
    for directiva in ("proxy_cache_bypass", "proxy_no_cache"):
        assert set(una(loc, directiva).args) == {"$http_authorization", "$http_origin"}
    # Un solo request al backend por clave vencida; el resto espera o recibe
    # la copia vieja mientras se renueva (stale-while-revalidate).
    assert una(loc, "proxy_cache_lock").args == ("on",)
    assert una(loc, "proxy_cache_background_update").args == ("on",)
    # El TTL es el Cache-Control del backend: sin proxy_cache_valid nada sin
    # ese header se guarda, y proxy_ignore_headers lo pisaria.
    assert not todas(loc, "proxy_cache_valid")
    assert not todas(loc, "proxy_ignore_headers")
    # Un add_header aca descartaria los headers de seguridad del server.
    assert not todas(loc, "add_header")
    assert una(loc, "proxy_buffering").args == ("on",)
    # Todo lo demas, igual que /api/.
    api = location(server, "/api/")
    for nombre in (
        "limit_req",
        "rewrite",
        "proxy_pass",
        "proxy_http_version",
        "proxy_set_header",
        "error_page",
        "client_max_body_size",
        "proxy_connect_timeout",
        "proxy_read_timeout",
    ):
        assert [d.args for d in todas(loc, nombre)] == [
            d.args for d in todas(api, nombre)
        ], (args, nombre)


@EDGES
@pytest.mark.parametrize(
    ("args", "clave"),
    [
        # La imagen es inmutable por id: un ?v=123 no es otra imagen. Con la
        # query en la clave, cada cache-buster seria una entrada nueva y un
        # viaje al backend (y ocuparia la cache con copias).
        (("~", MEDIOS), "$scheme$uri"),
        # El catalogo SI depende de la query (store_public_id, service_id).
        (("=", "/api/public/services"), "$scheme$request_uri"),
        (("=", "/api/public/staff"), "$scheme$request_uri"),
    ],
)
def test_la_clave_de_cache_de_cada_ruta(
    ruta: Path, args: tuple[str, str], clave: str
) -> None:
    loc = location(server_de_la_app(leer(ruta)), *args)
    assert una(loc, "proxy_cache_key").args == (clave,)


@pytest.mark.parametrize(
    ("uri", "calza"),
    [
        ("/api/stores/media/01JABCDEFGHJKMNPQRSTVWXYZ0", True),
        ("/api/stores/media/01JABC/", False),
        ("/api/stores/media/", False),
        ("/api/stores/media/a/b", False),
        ("/api/stores/me/media", False),
    ],
)
def test_la_regex_de_medios_es_exacta(uri: str, calza: bool) -> None:
    assert (re.fullmatch(MEDIOS[1:-1], uri) is not None) is calza


# --- F0-11: log estructurado sin datos del cliente ----------------------------

# Variables que meterian la query (client_phone viaja en la query de la
# reserva publica) o la URL de la pagina de origen en el access log.
VARIABLES_CON_QUERY = re.compile(
    r"\$(request|request_uri|args|query_string|arg_\w+|http_referer)\b"
)


def _log_format(http: list[Directiva]) -> Directiva:
    formatos = [d for d in todas(http, "log_format") if d.args[0] == "shifty_json"]
    assert len(formatos) == 1, "falta log_format shifty_json"
    return formatos[0]


@EDGES
def test_el_log_es_json_con_tiempos_y_sin_query(ruta: Path) -> None:
    formato = _log_format(leer(ruta))
    assert formato.args[1] == "escape=json"
    plantilla = "".join(formato.args[2:])
    assert "$uri" in plantilla
    assert not VARIABLES_CON_QUERY.search(plantilla), plantilla
    # Estas variables no siempre son numeros: $status vale 000 si el cliente
    # corta antes de la respuesta (JSON no admite ceros a la izquierda) y los
    # tiempos del upstream valen "-" sin upstream o "0.010, 0.020" si hubo
    # reintento. Van entre comillas o la linea deja de ser JSON.
    for variable in ("status", "upstream_response_time", "upstream_connect_time"):
        assert f'":"${variable}"' in plantilla, variable
    peores = {
        "status": "000",
        "upstream_response_time": "0.010, 0.020",
        "upstream_connect_time": "-",
    }
    linea = json.loads(
        re.sub(r"\$(\w+)", lambda m: peores.get(m.group(1), "0"), plantilla)
    )
    for clave in ("rid", "s", "rt", "urt", "uct", "u", "ip"):
        assert clave in linea, clave


@EDGES
def test_todo_server_del_edge_loguea_en_json(ruta: Path) -> None:
    # Un server sin access_log propio usa el `main` de la imagen, que loguea
    # $request con la query (en prod, el de 80 que redirige tambien).
    http = leer(ruta)
    assert not todas(http, "access_log"), "access_log a nivel http duplica lineas"
    for server in servidores(http):
        destino, formato = una(server, "access_log").args
        assert destino == "/var/log/nginx/access.log"
        assert formato == "shifty_json"


@EDGES
def test_el_backend_recibe_el_id_del_edge_sin_pisar_el_de_mercado_pago(
    ruta: Path,
) -> None:
    # Mercado Pago firma el webhook con SU x-request-id (el manifest HMAC de
    # payments/router.py lo incluye): pisarlo con el id de nginx rompe la
    # firma de todos los webhooks. El id del edge va en su propio header.
    for loc in locations_con_proxy(leer(ruta)):
        cabeceras = cabeceras_proxy(loc.bloque)
        assert "x-request-id" not in cabeceras, loc.args
        assert cabeceras.get("x-edge-request-id") == "$request_id", loc.args


@EDGES
def test_los_assets_con_hash_no_se_loguean(ruta: Path) -> None:
    server = server_de_la_app(leer(ruta))
    assets = location(server, "^~", "/assets/")
    assert una(assets, "access_log").args == ("off",)
    assert una(assets, "proxy_pass").args == ("http://spa",)


# --- F0-12: renovacion de certificados por webroot ----------------------------


def test_el_desafio_acme_se_sirve_en_claro_y_el_resto_redirige() -> None:
    http = leer(EDGE_PROD)
    en_claro = [
        s for s in servidores(http) if ("80",) in [d.args for d in todas(s, "listen")]
    ]
    assert len(en_claro) == 1
    server = en_claro[0]
    # Un `return` a nivel server corre antes de elegir location: taparia el
    # desafio y certbot no podria renovar.
    assert not todas(server, "return")
    acme = location(server, "^~", "/.well-known/acme-challenge/")
    assert una(acme, "root").args == ("/var/www/acme",)
    assert una(location(server, "/"), "return").args == (
        "301",
        "https://$host$request_uri",
    )


def test_https_conserva_hsts() -> None:
    cabeceras = _cabeceras_agregadas(server_de_la_app(leer(EDGE_PROD)))
    assert (
        cabeceras["strict-transport-security"] == "max-age=31536000; includeSubDomains"
    )


# --- F0-13: cache de la SPA ----------------------------------------------------


def _server_spa() -> list[Directiva]:
    (server,) = servidores(leer(SPA))
    return server


def _cache_control(bloque: list[Directiva]) -> list[str]:
    return [
        d.args[1]
        for d in todas(bloque, "add_header")
        if d.args[0].lower() == "cache-control"
    ]


def test_la_spa_emite_un_solo_cache_control() -> None:
    # `expires` + `add_header Cache-Control` mandaba DOS Cache-Control.
    server = _server_spa()
    assert not todas(server, "expires")
    for loc in locations(server):
        assert not todas(loc.bloque, "expires"), loc.args
        assert len(_cache_control(loc.bloque)) <= 1, loc.args


def test_solo_los_assets_con_hash_son_inmutables() -> None:
    # Vite pone hash en el nombre solo bajo /assets/. favicon.svg o icons.svg
    # (de public/) no cambian de nombre: con immutable, un cambio no llegaba
    # nunca a quien ya los tenia.
    server = _server_spa()
    assets = location(server, "^~", "/assets/")
    assert _cache_control(assets) == ["public, max-age=31536000, immutable"]
    assert una(assets, "access_log").args == ("off",)
    for loc in locations(server):
        if loc.bloque is not assets:
            assert not any("immutable" in v for v in _cache_control(loc.bloque)), (
                loc.args
            )
    (estaticos,) = [loc.bloque for loc in locations(server) if loc.args[0] == "~*"]
    assert _cache_control(estaticos) == ["public, max-age=3600"]
    # El shell del SPA revalida siempre (manifiesto de chunks tras un deploy).
    assert _cache_control(location(server, "/")) == ["no-cache"]


def test_toda_ruta_desconocida_de_la_spa_cae_en_index_html() -> None:
    # Rutas del router del front (/panel, /reservar/...): sin el fallback un
    # refresh o un link directo devuelve 404.
    raiz = location(_server_spa(), "/")
    assert una(raiz, "try_files").args == ("$uri", "$uri/", "/index.html")


def test_toda_location_de_la_spa_con_headers_propios_incluye_los_de_seguridad() -> None:
    for loc in locations(_server_spa()):
        if todas(loc.bloque, "add_header"):
            incluidos = [d.args for d in todas(loc.bloque, "include")]
            assert ("/etc/nginx/security-headers.conf",) in incluidos, loc.args


# --- paridad dev/prod -----------------------------------------------------------

SOLO_DESARROLLO = {("/docs",), ("/openapi.json",)}


def test_dev_y_prod_enrutan_igual() -> None:
    # Lo que se prueba en local tiene que ser lo que corre en prod: mismas
    # locations en el server de la app (prod solo quita la documentacion) y
    # los mismos upstreams.
    dev, prod = leer(EDGE_DEV), leer(EDGE_PROD)
    rutas_dev = {loc.args for loc in locations(server_de_la_app(dev))}
    rutas_prod = {loc.args for loc in locations(server_de_la_app(prod))}
    assert rutas_dev - SOLO_DESARROLLO == rutas_prod
    assert {d.args for d in todas(dev, "upstream")} == {
        d.args for d in todas(prod, "upstream")
    }
