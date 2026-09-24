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


def locations_de_api(server: list[Directiva]) -> list[Directiva]:
    return [loc for loc in locations(server) if loc.args[-1].startswith("/api/")]


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
    nombres = [una(bloque_con(http, "upstream", u), "zone").args[0] for u in ("api", "spa")]
    for d in http:
        if d.nombre in {"limit_req_zone", "limit_conn_zone"}:
            zona = next(a for a in d.args if a.startswith("zone="))
            nombres.append(zona.removeprefix("zone=").split(":")[0])
    assert len(nombres) == len(set(nombres)), nombres
