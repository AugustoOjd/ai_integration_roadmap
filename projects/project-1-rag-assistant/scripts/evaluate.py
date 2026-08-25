"""Corre el set de evaluacion y reporta dos metricas separadas.

    uv run python -m scripts.evaluate

Mide RECUPERACION y RESPUESTA por separado, que es lo unico que permite saber
DONDE falla el pipeline:

    recuperacion mala  -> ajustar CHUNK_SIZE, TOP_K o el modelo de embeddings
    recuperacion buena
    respuesta mala     -> ajustar el prompt o el modelo generador

Llama a los servicios directamente, sin pasar por HTTP: no necesita el servidor
levantado ni choca con el rate limit.
"""

import asyncio
import json
import logging
from dataclasses import dataclass
from pathlib import Path

from app.config import settings
from app.database import async_session, engine
from app.services.embeddings import embedding_service
from app.services.rag import SIN_CONTEXTO, answer
from app.services.search import search_chunks

logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(message)s")

PREGUNTAS = Path("evals/preguntas.json")


@dataclass
class Resultado:
    question: str
    recuperado: bool | None  # None cuando la pregunta espera rechazo
    respondido: bool
    answer: str


def _contiene(texto: str, esperados: list) -> bool:
    """Todos los terminos esperados aparecen, sin distinguir mayusculas.

    Cada entrada puede ser una cadena o una lista de variantes aceptables
    (["two", "dos", "2"]): basta con que aparezca una. Evita contar como fallo
    una respuesta correcta escrita en otro idioma o con otra palabra.
    """
    minusculas = texto.lower()
    for esperado in esperados:
        variantes = esperado if isinstance(esperado, list) else [esperado]
        if not any(variante.lower() in minusculas for variante in variantes):
            return False
    return True


def _es_rechazo(texto: str) -> bool:
    """Reconoce tanto el corte por umbral como la negativa del propio modelo."""
    if texto == SIN_CONTEXTO:
        return True
    señales = ("no encontre", "no contiene", "no aparece", "not contain",
               "no information", "does not", "no se menciona", "cannot find")
    minusculas = texto.lower()
    return any(s in minusculas for s in señales)


async def evaluar_una(session, caso: dict) -> Resultado:
    espera_rechazo = caso.get("expect_refusal", False)
    esperados = caso.get("expect", [])

    # 1) Recuperacion, sin LLM. Solo tiene sentido si esperamos una respuesta.
    recuperado = None
    if not espera_rechazo:
        hits = await search_chunks(session, caso["question"], settings.TOP_K)
        recuperado = any(_contiene(hit.text, esperados) for hit in hits)

    # 2) Pipeline completo.
    resultado = await answer(session, caso["question"])
    texto = resultado.text

    respondido = _es_rechazo(texto) if espera_rechazo else _contiene(texto, esperados)

    return Resultado(caso["question"], recuperado, respondido, texto)


async def main() -> None:
    casos = json.loads(PREGUNTAS.read_text(encoding="utf-8"))
    await asyncio.to_thread(embedding_service.load)

    resultados: list[Resultado] = []
    async with async_session() as session:
        for caso in casos:
            resultados.append(await evaluar_una(session, caso))

    await engine.dispose()
    _reportar(casos, resultados)


def _reportar(casos: list[dict], resultados: list[Resultado]) -> None:
    print(f"\n{'':2} {'REC':>4} {'RESP':>5}  pregunta")
    print("-" * 78)

    for i, (caso, r) in enumerate(zip(casos, resultados, strict=True), start=1):
        rec = "-" if r.recuperado is None else ("ok" if r.recuperado else "NO")
        resp = "ok" if r.respondido else "NO"
        print(f"{i:2} {rec:>4} {resp:>5}  {r.question[:58]}")
        if not r.respondido:
            print(f"{'':13}  -> {r.answer[:120]}")

    con_recuperacion = [r for r in resultados if r.recuperado is not None]
    aciertos_rec = sum(r.recuperado for r in con_recuperacion)
    aciertos_resp = sum(r.respondido for r in resultados)

    print("-" * 78)
    print(f"Recuperacion: {aciertos_rec}/{len(con_recuperacion)}")
    print(f"Respuesta:    {aciertos_resp}/{len(resultados)}")

    # La config se imprime para poder comparar corridas entre si.
    print(
        f"\nCHUNK_SIZE={settings.CHUNK_SIZE} OVERLAP={settings.CHUNK_OVERLAP} "
        f"TOP_K={settings.TOP_K} MIN_SIM={settings.MIN_SIMILARITY}\n"
        f"EMBEDDINGS={settings.MODEL_NAME} LLM={settings.LLM_MODEL}"
    )


if __name__ == "__main__":
    asyncio.run(main())
