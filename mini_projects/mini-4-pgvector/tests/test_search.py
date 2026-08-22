import pytest
from sqlalchemy import select

from app.config import EMBEDDING_DIM
from app.models.note import Note


async def test_create_guarda_el_embedding(client, db):
    """El POST no solo inserta la nota: genera y guarda su vector."""
    resp = await client.post("/notes/", json={"title": "Python", "content": "A language"})
    assert resp.status_code == 201

    nota = await db.scalar(select(Note).where(Note.id == resp.json()["id"]))
    assert nota.embedding is not None
    assert len(nota.embedding) == EMBEDDING_DIM


async def test_create_no_expone_el_embedding(client):
    """El response_model filtra la columna: 384 floats no son para el cliente."""
    resp = await client.post("/notes/", json={"title": "Python", "content": "A language"})
    assert "embedding" not in resp.json()


async def test_el_embedding_esta_normalizado(client, db):
    """Norma 1: si no, mezclar vectores normalizados y no normalizados en la
    misma tabla daría distancias sin sentido."""
    resp = await client.post("/notes/", json={"title": "Python", "content": "A language"})
    nota = await db.scalar(select(Note).where(Note.id == resp.json()["id"]))

    norma = sum(v * v for v in nota.embedding) ** 0.5
    assert norma == pytest.approx(1.0, abs=1e-5)


async def test_busqueda_es_semantica(client, notas):
    """El corazón del mini: la query no comparte NINGUNA palabra con las notas.

    Un LIKE o un full-text search devolvería cero. Aquí los dos lenguajes de
    programación tienen que quedar por delante de pan y maratón.
    """
    resp = await client.post("/notes/search", json={"query": "software development", "top_k": 4})
    assert resp.status_code == 200

    titulos = [r["title"] for r in resp.json()]
    assert set(titulos[:2]) == {"Python", "JavaScript"}


async def test_otro_tema_reordena(client, notas):
    """Control: con otra query el ranking cambia, no es un orden fijo."""
    resp = await client.post("/notes/search", json={"query": "baking recipes", "top_k": 4})
    assert resp.json()[0]["title"] == "Sourdough"


async def test_resultados_ordenados_por_similitud(client, notas):
    resp = await client.post("/notes/search", json={"query": "programming", "top_k": 4})
    similitudes = [r["similarity"] for r in resp.json()]
    assert similitudes == sorted(similitudes, reverse=True)


async def test_similitud_en_rango(client, notas):
    """1 - distancia_coseno cae en [-1, 1]. Fuera de ahí, el cálculo está mal."""
    resp = await client.post("/notes/search", json={"query": "programming", "top_k": 4})
    assert all(-1.0 <= r["similarity"] <= 1.0 for r in resp.json())


async def test_respeta_top_k(client, notas):
    resp = await client.post("/notes/search", json={"query": "programming", "top_k": 2})
    assert len(resp.json()) == 2


async def test_ignora_notas_sin_embedding(client, db, notas):
    """El WHERE embedding IS NOT NULL: una nota a medio procesar no debe salir."""
    db.add(Note(title="Huerfana", content="Sin vector", embedding=None))
    await db.commit()

    resp = await client.post("/notes/search", json={"query": "anything", "top_k": 10})
    assert "Huerfana" not in [r["title"] for r in resp.json()]


async def test_tabla_vacia_devuelve_lista_vacia(client):
    """Sin notas no hay error, hay cero resultados."""
    resp = await client.post("/notes/search", json={"query": "anything", "top_k": 5})
    assert resp.status_code == 200
    assert resp.json() == []


@pytest.mark.parametrize(
    "payload",
    [
        {"query": "", "top_k": 5},  # min_length=1: embeber "" no significa nada
        {"query": "ok", "top_k": 0},  # ge=1
        {"query": "ok", "top_k": 51},  # le=50: no pedir la tabla entera
        {"top_k": 5},  # query es obligatorio
    ],
)
async def test_validacion_rechaza_payloads_invalidos(client, payload):
    """Pydantic corta antes de tocar el modelo o la base."""
    resp = await client.post("/notes/search", json=payload)
    assert resp.status_code == 422


async def test_titulo_demasiado_largo_da_422(client):
    """max_length=200 espeja el String(200): 422 de Pydantic, no 500 de Postgres."""
    resp = await client.post("/notes/", json={"title": "x" * 201, "content": "ok"})
    assert resp.status_code == 422
