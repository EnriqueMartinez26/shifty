"""Toda decision atribuida al dueno en CLAUDE.md lleva su ID del registro.

"El dueno" de este repo es Enrique. El 2026-09-25 aparecieron en CLAUDE.md
reglas atribuidas a el que nunca habia visto (la opcion A de la sena, los
caminos que sueltan un turno): una frase en prosa no prueba quien decidio.
docs/DECISIONES.md es el registro (ID ``D-AAAAMMDD-NN``, fecha, decision,
propuesta por, adoptada por, referencia) y esta guarda recorre CLAUDE.md:

- cada bloque (un item de lista o un parrafo, con sus lineas partidas unidas)
  que dice "decision del dueno", "adoptada por el dueno" o "regla del dueno"
  cita al menos tantos IDs como frases de esas tiene;
- cada ID citado existe en el registro y su columna "Adoptada por" empieza
  con "dueno".

Sin ID, la frase se escribe "propuesta por X, pendiente de OK del dueno", que
esta guarda no toma como atribucion. Tampoco cuentan las frases entre
backticks (se mencionan, no se usan: es como la propia regla las nombra) ni
las genericas como "excepcion explicita del dueno", que piden una decision
futura en vez de afirmar una tomada.

Rutas resueltas desde la raiz del repo. Un contenedor corre la imagen, que no
trae CLAUDE.md ni docs/, asi que ahi la guarda se salta. En CI (variable CI
definida) no se salta nunca: si un archivo no se encuentra, falla. Mismo
esquema que test_api_contract_doc.py.
"""

import os
import re
from dataclasses import dataclass
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
CLAUDE_MD = REPO_ROOT / "CLAUDE.md"
DECISIONES_MD = REPO_ROOT / "docs" / "DECISIONES.md"

# \s+ entre palabras: dentro de un bloque la frase puede partirse de linea.
FRASE_DEL_DUENO = re.compile(
    r"\b(?:decisi[oó]n(?:es)?\s+del|adoptad[ao]s?\s+por\s+el|reglas?\s+del)"
    r"\s+due[nñ]o\b",
    re.IGNORECASE,
)
ID_DECISION = re.compile(r"\bD-(\d{4})(\d{2})(\d{2})-(\d{2})\b")
CODIGO_EN_LINEA = re.compile(r"`[^`]*`")
INICIO_DE_BLOQUE = re.compile(r"^\s*(?:#|[-*+]\s|\d+\.\s)")
FILA_DEL_REGISTRO = re.compile(r"^\|\s*D-\d{8}-\d{2}\s*\|")
ADOPTADA_POR_EL_DUENO = re.compile(r"due[nñ]o\b", re.IGNORECASE)
COLUMNAS = ("id", "fecha", "decision", "propuesta_por", "adoptada_por", "referencia")


@dataclass(frozen=True)
class Decision:
    id: str
    fecha: str
    decision: str
    propuesta_por: str
    adoptada_por: str
    referencia: str
    linea: int

    @property
    def del_dueno(self) -> bool:
        return ADOPTADA_POR_EL_DUENO.match(self.adoptada_por) is not None


def leer_registro(texto: str) -> tuple[dict[str, Decision], list[str]]:
    """Filas de la tabla de DECISIONES.md por ID, y los problemas de forma."""
    registro: dict[str, Decision] = {}
    problemas: list[str] = []
    for n, linea in enumerate(texto.splitlines(), start=1):
        if not FILA_DEL_REGISTRO.match(linea):
            continue
        celdas = [c.strip() for c in linea.strip().strip("|").split("|")]
        if len(celdas) != len(COLUMNAS):
            problemas.append(
                f"DECISIONES.md:{n}: {len(celdas)} columnas, se esperan "
                f"{len(COLUMNAS)} ({', '.join(COLUMNAS)})"
            )
            continue
        id_, fecha, texto_decision, propuesta_por, adoptada_por, referencia = celdas
        decision = Decision(
            id=id_,
            fecha=fecha,
            decision=texto_decision,
            propuesta_por=propuesta_por,
            adoptada_por=adoptada_por,
            referencia=referencia,
            linea=n,
        )
        if decision.id in registro:
            problemas.append(f"DECISIONES.md:{n}: {decision.id} repetido")
        registro[decision.id] = decision
    return registro, problemas


def problemas_del_registro(registro: dict[str, Decision]) -> list[str]:
    """El ID lleva la fecha de su fila y numera de 01 en adelante por dia."""
    problemas: list[str] = []
    por_dia: dict[str, list[int]] = {}
    for decision in registro.values():
        partes = ID_DECISION.fullmatch(decision.id)
        assert partes is not None  # FILA_DEL_REGISTRO ya filtro la forma
        anio, mes, dia, numero = partes.groups()
        fecha_del_id = f"{anio}-{mes}-{dia}"
        if decision.fecha != fecha_del_id:
            problemas.append(
                f"DECISIONES.md:{decision.linea}: {decision.id} tiene fecha "
                f"{decision.fecha!r}; su ID dice {fecha_del_id}"
            )
        por_dia.setdefault(fecha_del_id, []).append(int(numero))
    for fecha, numeros in sorted(por_dia.items()):
        if sorted(numeros) != list(range(1, len(numeros) + 1)):
            problemas.append(
                f"DECISIONES.md: los IDs del {fecha} no numeran 01..NN "
                f"seguidos: {sorted(numeros)}"
            )
    return problemas


def bloques(texto: str) -> list[tuple[int, str]]:
    """Items de lista y parrafos, con su linea de inicio.

    Un bloque arranca en un titulo, un item (``-``, ``*``, ``+``, ``N.``) o
    despues de una linea en blanco; las lineas siguientes son su continuacion.
    """
    resultado: list[tuple[int, str]] = []
    actual: list[str] = []
    inicio = 0
    for n, linea in enumerate(texto.splitlines(), start=1):
        en_blanco = not linea.strip()
        if en_blanco or INICIO_DE_BLOQUE.match(linea):
            if actual:
                resultado.append((inicio, "\n".join(actual)))
            actual = []
            if en_blanco:
                continue
        if not actual:
            inicio = n
        actual.append(linea)
    if actual:
        resultado.append((inicio, "\n".join(actual)))
    return resultado


def problemas_de_atribucion(claude_md: str, registro: dict[str, Decision]) -> list[str]:
    """Frases de decision del dueno sin ID e IDs que el registro no respalda."""
    problemas: list[str] = []
    for inicio, bloque in bloques(claude_md):
        prosa = CODIGO_EN_LINEA.sub(" ", bloque)
        frases = [" ".join(m.group(0).split()) for m in FRASE_DEL_DUENO.finditer(prosa)]
        ids = [m.group(0) for m in ID_DECISION.finditer(bloque)]
        if len(ids) < len(frases):
            problemas.append(
                f"CLAUDE.md:{inicio}: {len(frases)} frase(s) de decision del "
                f"dueno ({'; '.join(frases)}) y {len(ids)} ID(s) de "
                "docs/DECISIONES.md. Sin ID se escribe 'propuesta por X, "
                "pendiente de OK del dueno'."
            )
        for id_citado in ids:
            decision = registro.get(id_citado)
            if decision is None:
                problemas.append(
                    f"CLAUDE.md:{inicio}: {id_citado} no existe en docs/DECISIONES.md"
                )
            elif not decision.del_dueno:
                problemas.append(
                    f"CLAUDE.md:{inicio}: {id_citado} no esta adoptada por el "
                    f"dueno en docs/DECISIONES.md (adoptada por: "
                    f"{decision.adoptada_por!r})"
                )
    return problemas


def _leer(ruta: Path) -> str:
    if not ruta.is_file():
        # Sin el archivo es un contenedor (corre la imagen). En CI el repo
        # entero esta en disco, asi que ahi no se tolera la ausencia.
        if not os.environ.get("CI"):
            pytest.skip(f"{ruta} no es alcanzable (contenedor con solo backend/).")
        pytest.fail(f"No existe {ruta}.")
    return ruta.read_text(encoding="utf-8")


def test_decisiones_del_dueno_en_claude_md_tienen_id_del_registro() -> None:
    claude_md = _leer(CLAUDE_MD)
    registro, problemas = leer_registro(_leer(DECISIONES_MD))
    problemas += problemas_de_atribucion(claude_md, registro)
    assert not problemas, "\n".join(problemas)


def test_el_registro_esta_bien_formado() -> None:
    registro, problemas = leer_registro(_leer(DECISIONES_MD))
    assert registro, "docs/DECISIONES.md no tiene filas D-AAAAMMDD-NN"
    problemas += problemas_del_registro(registro)
    assert not problemas, "\n".join(problemas)


# --- La guarda misma, sobre un CLAUDE.md sintetico -------------------------

REGISTRO_SINTETICO = """\
| ID | Fecha | Decisión | Propuesta por | Adoptada por | Referencia |
|----|-------|----------|---------------|--------------|------------|
| D-20260925-01 | 2026-09-25 | Regla A | Mateo | dueño (Enrique) | abc1234 |
| D-20260925-02 | 2026-09-25 | Regla B | Mateo | pendiente | def5678 |
"""


def _registro() -> dict[str, Decision]:
    registro, problemas = leer_registro(REGISTRO_SINTETICO)
    assert not problemas
    return registro


def test_frase_partida_en_dos_lineas_sin_id_falla() -> None:
    snippet = (
        "- **Regla A** (propuesta por Mateo, adoptada por el\n"
        "  dueño el 2026-09-25). Sigue el texto.\n"
    )
    problemas = problemas_de_atribucion(snippet, _registro())
    assert len(problemas) == 1
    assert "CLAUDE.md:1" in problemas[0]
    assert "adoptada por el dueño" in problemas[0]


def test_frase_con_id_del_registro_pasa() -> None:
    snippet = (
        "- **Regla A** (propuesta por Mateo, adoptada por el\n"
        "  dueño el 2026-09-25, D-20260925-01). Sigue el texto.\n"
        "3. Otra cosa (decisión del dueño, D-20260925-01).\n"
    )
    assert problemas_de_atribucion(snippet, _registro()) == []


def test_id_que_no_existe_en_el_registro_falla() -> None:
    snippet = "- Regla C (decisión del dueño, D-20260925-09).\n"
    problemas = problemas_de_atribucion(snippet, _registro())
    assert problemas == ["CLAUDE.md:1: D-20260925-09 no existe en docs/DECISIONES.md"]


def test_id_no_adoptado_por_el_dueno_falla() -> None:
    snippet = "- Regla B (adoptada por el dueño el 2026-09-25, D-20260925-02).\n"
    problemas = problemas_de_atribucion(snippet, _registro())
    assert len(problemas) == 1
    assert "no esta adoptada por el dueno" in problemas[0]


def test_cada_frase_necesita_su_id() -> None:
    snippet = (
        "Uno (decisión del dueño, D-20260925-01) y otro (regla del dueño)\n"
        "en el mismo parrafo.\n"
    )
    assert len(problemas_de_atribucion(snippet, _registro())) == 1


def test_bloques_separados_no_se_prestan_el_id() -> None:
    snippet = (
        "- Regla A (decisión del dueño, D-20260925-01).\n"
        "- Regla C (decisión del dueño).\n"
    )
    problemas = problemas_de_atribucion(snippet, _registro())
    assert len(problemas) == 1
    assert problemas[0].startswith("CLAUDE.md:2:")


def test_menciones_y_frases_genericas_no_son_atribuciones() -> None:
    snippet = (
        "- Toda frase `decisión del dueño` o `adoptada por el dueño` lleva su\n"
        "  ID; sin él: propuesta por Mateo, pendiente de OK del dueño.\n"
        "- Un ítem sin marcar necesita excepción explícita del dueño.\n"
        "- La consolidación del panel del dueño espera su ok explícito.\n"
    )
    assert problemas_de_atribucion(snippet, _registro()) == []


def test_registro_con_fecha_o_numeracion_que_no_cuadra_falla() -> None:
    registro, problemas = leer_registro(
        "| D-20260925-01 | 2026-09-24 | X | Mateo | dueño (Enrique) | a |\n"
        "| D-20260925-03 | 2026-09-25 | Y | Mateo | dueño (Enrique) | b |\n"
        "| D-20260925-03 | 2026-09-25 | Z | Mateo | dueño (Enrique) | c |\n"
        "| D-20260926-01 | 2026-09-26 | faltan columnas |\n"
    )
    problemas += problemas_del_registro(registro)
    assert any("D-20260925-03 repetido" in p for p in problemas)
    assert any("3 columnas" in p for p in problemas)
    assert any("su ID dice 2026-09-25" in p for p in problemas)
    assert any("no numeran 01..NN" in p for p in problemas)
