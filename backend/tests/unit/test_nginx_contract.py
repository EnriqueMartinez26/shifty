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

import ipaddress
import json
import random
import re
from collections.abc import Iterator
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


def test_los_tres_nginx_corren_la_misma_imagen_base() -> None:
    # 2026-09-26 (image-scan de Trivy en rojo): el edge de dev y el de prod
    # estaban en nginx:1.27.5-alpine y la SPA en el flotante 1.27-alpine, los
    # tres con OpenSSL 3.3.3 (CVE-2026-31789). Bumpear uno solo deja a los otros
    # con el hueco; el borde de produccion no pasa por el scan de CI (corre la
    # imagen oficial, no un build), asi que su unica garantia es este test.
    def from_nginx(ruta: Path) -> str:
        tags = re.findall(r"^FROM (nginx:\S+)", ruta.read_text(encoding="utf-8"), re.M)
        assert len(tags) == 1, f"{ruta}: {tags}"
        return str(tags[0])

    compose_prod = (RAIZ / "docker-compose.prod.yml").read_text(encoding="utf-8")
    borde_prod = re.findall(r"^\s+image: (nginx:\S+)\s*$", compose_prod, re.M)
    assert len(borde_prod) == 1, borde_prod
    imagenes = {
        "nginx/Dockerfile": from_nginx(EDGE_DOCKERFILE),
        "frontend/Dockerfile": from_nginx(RAIZ / "frontend" / "Dockerfile"),
        "docker-compose.prod.yml": borde_prod[0],
    }
    assert len(set(imagenes.values())) == 1, imagenes


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


def _locations_de_la_spa(
    http: list[Directiva],
) -> list[tuple[list[Directiva], Directiva]]:
    """(server, location) de cada location que proxea a la SPA."""
    return [
        (server, loc)
        for server in servidores(http)
        for loc in locations(server)
        if todas(loc.bloque, "proxy_pass")
        and una(loc.bloque, "proxy_pass").args[0] == "http://spa"
    ]


@EDGES
def test_un_request_a_una_replica_de_la_spa_que_se_apaga_va_a_otra(
    ruta: Path,
) -> None:
    """scripts/deploy.sh renueva el frontend con una replica nueva al lado de
    la vieja (2026-10-15: recrearlo daba 502 en la home en cada deploy). Si un
    request todavia va a la vieja cuando se apaga, falla al conectar y nginx
    lo pasa a la otra: `proxy_next_upstream` por defecto (error timeout) y sin
    tope de intentos. Apagar eso devuelve el 502 del deploy."""
    http = leer(ruta)
    spa = _locations_de_la_spa(http)
    assert spa
    for server, loc in spa:
        siguiente = efectivo("proxy_next_upstream", http, server, loc.bloque)
        assert siguiente is None or {"error", "timeout"} <= set(siguiente), (
            loc.args,
            siguiente,
        )
        intentos = efectivo("proxy_next_upstream_tries", http, server, loc.bloque)
        assert intentos is None or intentos[0] == "0" or int(intentos[0]) >= 2, (
            loc.args,
            intentos,
        )


def _segundos(valor: str) -> float:
    if valor.endswith("ms"):
        return float(valor[:-2]) / 1000
    return float(valor.removesuffix("s"))


@EDGES
def test_una_replica_de_la_spa_que_ya_no_existe_no_retiene_el_request(
    ruta: Path,
) -> None:
    """Revision del PR #188: despues de borrar la replica vieja, nginx puede
    tenerla como peer hasta re-resolver (valid=5s). Un SYN a esa IP espera
    "no route to host" o el `proxy_connect_timeout` por defecto (60 s) antes
    de pasar a la otra. Conectar a la SPA, en la red interna, tarda
    microsegundos: el tope es corto en todas sus locations."""
    http = leer(ruta)
    spa = _locations_de_la_spa(http)
    assert spa
    for server, loc in spa:
        tope = efectivo("proxy_connect_timeout", http, server, loc.bloque)
        assert tope is not None, f"{loc.args}: sin proxy_connect_timeout (60 s)"
        assert _segundos(tope[0]) <= 2, (loc.args, tope)


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

# Clave de las zonas (#277): IPv4 por direccion, IPv6 por su /64. La arma el
# `map $remote_addr $rate_limit_key` (ver la seccion de IPv6, abajo).
CLAVE_DE_LIMITE = "$rate_limit_key"


def _tasa_por_segundo(http: list[Directiva], zona: str) -> int:
    for d in todas(http, "limit_req_zone"):
        if f"zone={zona}:10m" in d.args:
            assert d.args[0] == CLAVE_DE_LIMITE, d.args
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
    assert una(http, "limit_conn_zone").args == (CLAVE_DE_LIMITE, "zone=perip:10m")
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


# --- #277: IPv6 con la direccion real, agrupada por /64 -----------------------
# 2026-11-02 (produccion): nginx no escuchaba en IPv6 dentro del contenedor y la
# red de Docker no tenia IPv6, asi que docker-proxy le pasaba cada visitante
# IPv6 con la IP del gateway del bridge (172.16.1.1): todos compartian una
# cubeta en el edge y en la app. Ahora produccion escucha tambien en [::] (la
# red `edge` del override tiene IPv6, test_compose_contract.py) y las zonas
# cuentan una IPv6 por su /64, como la app (core/rate_limit.rate_limit_ip_key).

BINARIA = "<binary_remote_addr>"


def _mapa_de_la_clave(http: list[Directiva]) -> Directiva:
    (mapa,) = [
        d for d in todas(http, "map") if d.args == ("$remote_addr", CLAVE_DE_LIMITE)
    ]
    return mapa


def _sustituir(valor: str, calce: re.Match[str] | None) -> str:
    def variable(m: re.Match[str]) -> str:
        if m.group(1) == "binary_remote_addr":
            return BINARIA
        assert calce is not None, m.group(1)
        return str(calce.group(m.group(1)))

    return re.sub(r"\$(\w+)", variable, valor)


def _clave_de_nginx(mapa: Directiva, remote_addr: str) -> str:
    """Evalua el map como nginx: regex en orden, sin anclar salvo `^`; si
    ninguna calza, `default`. PCRE y `re` coinciden en estos patrones."""
    default = None
    for entrada in mapa.bloque:
        clave, valor = entrada.nombre, entrada.args[0]
        if clave == "default":
            default = valor
            continue
        assert clave.startswith("~") and not clave.startswith("~*"), clave
        calce = re.search(clave[1:].replace("(?<", "(?P<"), remote_addr)
        if calce:
            return _sustituir(valor, calce)
    assert default is not None, "el map no tiene default"
    return _sustituir(default, None)


def _como_lo_escribe_nginx(ip: str) -> str:
    """`$remote_addr` de una IPv6: port de ngx_inet6_ntop (src/core/ngx_inet.c).

    Minusculas, sin ceros a la izquierda, `::` solo para la corrida de ceros
    mas larga de DOS o mas grupos, y cola en decimal con puntos para las que
    empiezan con cinco o mas grupos en cero (la IPv4 mapeada, entre otras).
    """
    p = ipaddress.IPv6Address(ip).packed
    grupos = [p[i] * 256 + p[i + 1] for i in range(0, 16, 2)]
    zero, maximo, n, ultimo = -1, 1, 0, -1
    for i, grupo in enumerate(grupos):
        if grupo:
            if maximo < n:
                zero, maximo = ultimo, n
            n = 0
            continue
        if n == 0:
            ultimo = i
        n += 1
    if maximo < n:
        zero, maximo = ultimo, n
    texto, fin = "", 8
    if zero == 0:
        if (
            (maximo == 5 and grupos[5] == 0xFFFF)
            or maximo == 6
            or (maximo == 7 and p[14] != 0 and p[15] != 1)
        ):
            fin = 6
        texto = ":"
    i = 0
    while i < fin:
        if i == zero:
            texto += ":"
            i += maximo
            continue
        texto += f"{grupos[i]:x}"
        if i < 7:
            texto += ":"
        i += 1
    if fin == 6:
        texto += ".".join(str(b) for b in p[12:])
    return texto


@pytest.mark.parametrize(
    ("ip", "texto"),
    [
        ("2001:db8::1", "2001:db8::1"),
        ("2001:db8:0:1:0:0:0:1", "2001:db8:0:1::1"),
        # Un solo grupo en cero no se comprime.
        ("2001:db8:0:1:1:1:1:1", "2001:db8:0:1:1:1:1:1"),
        ("::", "::"),
        ("::1", "::1"),
        ("::ffff:203.0.113.7", "::ffff:203.0.113.7"),
        ("::203.0.113.7", "::203.0.113.7"),
        ("fe80::", "fe80::"),
    ],
)
def test_el_port_de_ngx_inet6_ntop_escribe_como_nginx(ip: str, texto: str) -> None:
    assert _como_lo_escribe_nginx(ip) == texto


@EDGES
def test_las_zonas_del_edge_cuentan_por_la_clave_agrupada(ruta: Path) -> None:
    http = leer(ruta)
    zonas = todas(http, "limit_req_zone") + todas(http, "limit_conn_zone")
    assert zonas
    for zona in zonas:
        assert zona.args[0] == CLAVE_DE_LIMITE, zona.args
    _mapa_de_la_clave(http)


def test_dev_y_prod_agrupan_igual() -> None:
    dev, prod = (_mapa_de_la_clave(leer(r)).bloque for r in (EDGE_DEV, EDGE_PROD))
    assert [(d.nombre, d.args) for d in dev] == [(d.nombre, d.args) for d in prod]


@pytest.mark.parametrize(
    ("remote_addr", "clave"),
    [
        # IPv4: la direccion, en los 4 bytes de siempre.
        ("203.0.113.7", BINARIA),
        # Una IPv4 mapeada se queda con su direccion: no se junta con todas las
        # demas en ::ffff:0:0/64.
        ("::ffff:203.0.113.7", BINARIA),
        ("2001:db8:1:2:aaaa:bbbb:cccc:dddd", "2001:db8:1:2"),
        ("2001:db8:1:2::1", "2001:db8:1:2"),
        ("2001:db8::1", "2001:db8:0:0"),
        ("2001::1", "2001:0:0:0"),
        ("::1", "0:0:0:0"),
        # Formas con `::` de un solo grupo: nginx no las escribe, pero el map
        # igual les da su /64.
        ("2001:db8::5:6:7:8:9", "2001:db8:0:5"),
        ("2001::5:6:7:8:9:a", "2001:0:5:6"),
        ("::5:6:7:8:9:a:b", "0:5:6:7"),
    ],
)
def test_la_clave_del_edge_es_la_ipv4_o_el_64(remote_addr: str, clave: str) -> None:
    assert _clave_de_nginx(_mapa_de_la_clave(leer(EDGE_PROD)), remote_addr) == clave


def _ipv6_de_prueba() -> list[str]:
    """Direcciones con corridas de ceros en todas las posiciones."""
    azar = random.Random(277)
    direcciones = []
    for _ in range(3000):
        grupos = [
            0
            if azar.random() < 0.5
            else azar.choice((1, 0xFFFF, azar.randrange(1, 1 << 16)))
            for _ in range(8)
        ]
        direcciones.append(
            str(ipaddress.IPv6Address(b"".join(g.to_bytes(2, "big") for g in grupos)))
        )
    return direcciones


def test_el_edge_y_la_app_agrupan_en_el_mismo_64() -> None:
    from core.rate_limit import rate_limit_ip_key

    mapa = _mapa_de_la_clave(leer(EDGE_PROD))
    for ip in _ipv6_de_prueba():
        clave = _clave_de_nginx(mapa, _como_lo_escribe_nginx(ip))
        de_la_app = rate_limit_ip_key(ip)
        if ipaddress.IPv6Address(ip).ipv4_mapped is not None:
            assert clave == BINARIA, ip
            continue
        assert ipaddress.ip_network(f"{clave}::/64") == ipaddress.ip_network(
            de_la_app
        ), (ip, clave, de_la_app)


def test_produccion_escucha_tambien_en_ipv6() -> None:
    # Sin `listen [::]`, la red con IPv6 entrega el paquete al contenedor y nadie
    # lo atiende. ipv6only (el default) deja a IPv4 en su propio socket.
    escuchas = {
        frozenset(d.args for d in todas(server, "listen"))
        for server in servidores(leer(EDGE_PROD))
    }
    assert escuchas == {
        frozenset({("80",), ("[::]:80",)}),
        frozenset({("443", "ssl"), ("[::]:443", "ssl")}),
    }, escuchas


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

# --- F4-13: tunel de Sentry con el tope de cuerpo de la SPA --------------------

TUNEL_SENTRY = ("=", "/sentry-tunnel")
GENERADOR_DEL_TUNEL = RAIZ / "frontend" / "sentry-tunnel.sh"


@EDGES
def test_el_tunel_de_sentry_admite_el_tope_de_la_spa(ruta: Path) -> None:
    # 2026-09-30: un envelope de Sentry de mas de 32 KB daba 413 en el borde.
    # /sentry-tunnel caia en `location /` con el tope de 32k del server y
    # nunca llegaba al 256k que la SPA le da al tunel (sentry-tunnel.sh).
    server = server_de_la_app(leer(ruta))
    tunel = location(server, *TUNEL_SENTRY)
    assert una(tunel, "client_max_body_size").args == ("256k",)
    # Solo el tunel sube el tope: el resto del server sigue en 32k.
    assert efectivo("client_max_body_size", server) == ("32k",)
    # El borde no puede cortar antes que la SPA: mismo tope que el location
    # que genera sentry-tunnel.sh.
    generado = re.findall(
        r"client_max_body_size (\S+);", GENERADOR_DEL_TUNEL.read_text(encoding="utf-8")
    )
    assert generado == ["256k"], generado
    # Proxy identico al de `location /` (upstream de la SPA, cabeceras, sin
    # limit_req propio): solo cambia el tope de cuerpo.
    raiz = location(server, "/")
    assert una(tunel, "proxy_pass").args == ("http://spa",)
    for nombre in (
        "proxy_pass",
        "proxy_http_version",
        "proxy_set_header",
        "limit_req",
        "add_header",
        "error_page",
    ):
        assert [d.args for d in todas(tunel, nombre)] == [
            d.args for d in todas(raiz, nombre)
        ], nombre


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
    # Un solo salto: http://www.<dominio> va directo a https://<dominio>.
    assert una(location(server, "/"), "return").args == (
        "301",
        "https://$apex_host$request_uri",
    )


# --- www -> apex ----------------------------------------------------------------
# 2026-10-10. `server_name _` servia la app tambien en www.shifty-ar.tech: con
# cookies separadas de las del apex y mails que apuntan al apex. El certificado
# ya cubre www (certbot lo renueva por el desafio HTTP-01 de arriba, que sigue
# sirviendose en claro para los dos nombres: no depende del host).


def _apex_host() -> Directiva:
    (mapa,) = [
        d for d in todas(leer(EDGE_PROD), "map") if d.args == ("$host", "$apex_host")
    ]
    return mapa


def _resolver_apex(host: str) -> str:
    """Evalua el `map $host $apex_host` como nginx (regex en orden, default)."""
    default = "$host"
    for entrada in _apex_host().bloque:
        clave, valor = entrada.nombre, entrada.args[0]
        if clave == "default":
            default = valor
            continue
        assert clave.startswith("~"), clave
        patron = clave.lstrip("~*").replace("(?<", "(?P<")
        flags = re.IGNORECASE if clave.startswith("~*") else 0
        calce = re.match(patron, host, flags)
        if calce:
            return re.sub(r"\$(\w+)", lambda m: calce.group(m.group(1)), valor)
    return host if default == "$host" else default


@pytest.mark.parametrize(
    ("host", "apex"),
    [
        ("www.shifty-ar.tech", "shifty-ar.tech"),
        ("WWW.shifty-ar.tech", "shifty-ar.tech"),
        ("shifty-ar.tech", "shifty-ar.tech"),
        ("wwwx.shifty-ar.tech", "wwwx.shifty-ar.tech"),
        ("api.shifty-ar.tech", "api.shifty-ar.tech"),
        ("www.", "www."),
    ],
)
def test_el_host_canonico_es_el_apex(host: str, apex: str) -> None:
    assert _resolver_apex(host) == apex


def test_https_en_www_redirige_al_apex_con_ruta_y_query() -> None:
    server = server_de_la_app(leer(EDGE_PROD))
    # A nivel server: corre antes de elegir location, asi que cubre la SPA,
    # /api y los assets por igual. `$request_uri` conserva ruta y query.
    (condicion,) = todas(server, "if")
    assert condicion.args == ("($host", "!=", "$apex_host)")
    assert una(condicion.bloque, "return").args == (
        "301",
        "https://$apex_host$request_uri",
    )
    # Fuera del if no hay return a nivel server: el apex se sirve normal.
    assert not todas(server, "return")


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
    # Vite pone hash en el nombre solo bajo /assets/. favicon-32.png o
    # apple-touch-icon.png (de public/) no cambian de nombre: con immutable, un
    # cambio no llegaba nunca a quien ya los tenia.
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


def test_el_manifest_de_la_spa_sale_con_su_tipo_y_sus_iconos_existen() -> None:
    # 2026-10-03: el mime.types de nginx 1.30.5 no mapea .webmanifest; sin el
    # tipo explicito salia application/octet-stream y, con nosniff, el
    # navegador descartaba el manifest.
    manifest = location(_server_spa(), "=", "/manifest.webmanifest")
    tipos = bloque_con(manifest, "types")
    assert [(d.nombre, d.args) for d in tipos] == [
        ("application/manifest+json", ("webmanifest",))
    ]
    assert una(manifest, "try_files").args == ("$uri", "=404")
    publico = RAIZ / "frontend" / "public"
    datos = json.loads((publico / "manifest.webmanifest").read_text(encoding="utf-8"))
    for icono in datos["icons"]:
        assert (publico / icono["src"].lstrip("/")).is_file(), icono["src"]
    assert 'rel="manifest" href="/manifest.webmanifest"' in (
        RAIZ / "frontend" / "index.html"
    ).read_text(encoding="utf-8")


def test_toda_location_de_la_spa_con_headers_propios_incluye_los_de_seguridad() -> None:
    for loc in locations(_server_spa()):
        if todas(loc.bloque, "add_header"):
            incluidos = [d.args for d in todas(loc.bloque, "include")]
            assert ("/etc/nginx/security-headers.conf",) in incluidos, loc.args


# --- metadata social por tienda ----------------------------------------------


def _directivas_recursivas(bloque: list[Directiva]) -> Iterator[Directiva]:
    for directiva in bloque:
        yield directiva
        if directiva.hijos is not None:
            yield from _directivas_recursivas(directiva.hijos)


def _texto_directivas(bloque: list[Directiva]) -> str:
    return " ".join(
        " ".join((directiva.nombre, *directiva.args))
        for directiva in _directivas_recursivas(bloque)
    )


def _locations_de_share(server: list[Directiva]) -> list[Directiva]:
    """Locations regex que reconocen las dos URLs públicas compartibles."""
    encontradas: list[Directiva] = []
    for loc in locations(server):
        if len(loc.args) < 2 or loc.args[0] not in {"~", "~*"}:
            continue
        patron = loc.args[-1]
        reconoce_b = re.search(r"(?:^|[(/|])b(?:[/)|]|$)", patron)
        reconoce_booking = re.search(r"(?:^|[(/|])booking(?:[/)|]|$)", patron)
        if reconoce_b or reconoce_booking:
            encontradas.append(loc)
    return encontradas


def test_el_home_conserva_el_shell_estatico_del_spa() -> None:
    """El metadata dinámico solo se aplica a rutas de tienda compartidas."""
    server = _server_spa()
    raiz = location(server, "/")
    assert una(raiz, "try_files").args == ("$uri", "$uri/", "/index.html")
    index = (RAIZ / "frontend" / "index.html").read_text(encoding="utf-8")
    assert '<meta property="og:title"' in index
    assert 'content="https://shifty-ar.tech/og-shifty.jpg"' in index


def test_las_dos_rutas_de_tienda_sirven_el_shell_con_metadata() -> None:
    server = _server_spa()
    matches = _locations_de_share(server)
    assert matches, "faltan locations para /b/{slug} y /booking/{slug}"
    # Nginx/PCRE nombra capturas como `(?<slug>...)`; normalizar esa forma
    # para que Python pueda verificar que los dos aliases alcanzan el shell.
    patrones = [
        re.compile(re.sub(r"\(\?<([A-Za-z_]\w*)>", r"(?P<\1>", loc.args[-1]))
        for loc in matches
    ]
    assert any(p.fullmatch("/b/demo-store") for p in patrones)
    assert any(p.fullmatch("/booking/demo-store") for p in patrones)
    assert any("store.html" in _texto_directivas(loc.bloque) for loc in matches), (
        "las rutas de tienda deben entregar el shell generado con metadata"
    )


def test_el_shell_usa_ssi_con_fallback_y_proxy_backend_interno() -> None:
    server = _server_spa()
    directives = list(_directivas_recursivas(server))
    assert any(d.nombre == "ssi" and d.args == ("on",) for d in directives)
    assert any(
        d.nombre == "ssi_silent_errors" and d.args == ("on",) for d in directives
    )

    shell = RAIZ / "frontend" / "store.html"
    assert shell.is_file(), "falta la plantilla store.html del shell de tienda"
    html = shell.read_text(encoding="utf-8")
    assert re.search(r"<!--\s*#\s*include\s+virtual=", html)
    assert re.search(r"\bstub=\"default_store_metadata\"", html), (
        "el include SSI debe enlazar el fallback Shifty"
    )
    assert re.search(
        r'<!--\s*#\s*block\s+name="default_store_metadata"\s*-->'
        r"[\s\S]*?<meta\s+property=\"og:title\""
        r"[\s\S]*?<meta\s+property=\"og:image\""
        r"[\s\S]*?<!--\s*#\s*endblock\s*-->",
        html,
    ), "el bloque SSI debe contener Open Graph genérico para fallos del lookup"
    assert "slug=$share_store_slug" in html

    proxy_interno = [
        loc.bloque
        for loc in locations(server)
        if todas(loc.bloque, "internal") and todas(loc.bloque, "proxy_pass")
    ]
    assert proxy_interno, "el endpoint metadata debe usar una location interna"
    assert any("backend" in _texto_directivas(loc) for loc in proxy_interno)
    [metadata_proxy] = proxy_interno
    assert una(metadata_proxy, "proxy_connect_timeout").args == ("2s",)
    assert una(metadata_proxy, "proxy_read_timeout").args == ("2s",)
    assert una(metadata_proxy, "proxy_intercept_errors").args == ("on",)
    assert una(metadata_proxy, "error_page").args == (
        "400",
        "404",
        "429",
        "500",
        "502",
        "503",
        "504",
        "=",
        "/_internal/share-metadata-fallback",
    )

    fallback = location(server, "=", "/_internal/share-metadata-fallback")
    assert una(fallback, "internal").args == ()
    assert una(fallback, "return").args == ("204",)


def test_el_shell_dinamico_no_se_cachea_y_docker_valida_nginx() -> None:
    server = _server_spa()
    shell = location(server, "=", "/store.html")
    assert any("no-store" in value.lower() for value in _cache_control(shell)), (
        "el HTML con metadata por tienda debe evitar cache compartido"
    )

    dockerfile = (RAIZ / "frontend" / "Dockerfile").read_text(encoding="utf-8")
    assert re.search(r"^RUN\s+nginx\s+-t(?:\s|$)", dockerfile, re.M), (
        "la imagen de frontend debe validar disponibilidad/sintaxis de SSI"
    )


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
