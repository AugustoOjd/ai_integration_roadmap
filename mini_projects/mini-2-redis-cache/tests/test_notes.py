from httpx import AsyncClient

NIL_UUID = "00000000-0000-0000-0000-000000000000"


async def test_list_notes_empty(client: AsyncClient):
    response = await client.get("/notes/")
    assert response.status_code == 200
    assert response.json() == []


async def test_create_note(client: AsyncClient):
    response = await client.post("/notes/", json={"title": "Test", "content": "Hello"})
    assert response.status_code == 201

    data = response.json()
    assert data["title"] == "Test"
    assert data["content"] == "Hello"
    assert "id" in data
    assert "created_at" in data


async def test_get_note_not_found(client: AsyncClient):
    response = await client.get(f"/notes/{NIL_UUID}")
    assert response.status_code == 404


async def test_update_note_not_found(client: AsyncClient):
    response = await client.put(f"/notes/{NIL_UUID}", json={"title": "x", "content": "y"})
    assert response.status_code == 404


async def test_delete_note_not_found(client: AsyncClient):
    response = await client.delete(f"/notes/{NIL_UUID}")
    assert response.status_code == 404


async def test_full_crud_flow(client: AsyncClient):
    # Create
    create_resp = await client.post("/notes/", json={"title": "Original", "content": "v1"})
    assert create_resp.status_code == 201
    note_id = create_resp.json()["id"]

    # Read
    get_resp = await client.get(f"/notes/{note_id}")
    assert get_resp.status_code == 200
    assert get_resp.json()["title"] == "Original"

    # Appears in the list
    list_resp = await client.get("/notes/")
    assert any(note["id"] == note_id for note in list_resp.json())

    # Update
    update_resp = await client.put(f"/notes/{note_id}", json={"title": "Updated", "content": "v2"})
    assert update_resp.status_code == 200
    assert update_resp.json()["title"] == "Updated"

    # The updated value is what later reads return, not the stale cached one
    assert (await client.get(f"/notes/{note_id}")).json()["title"] == "Updated"

    # Delete
    delete_resp = await client.delete(f"/notes/{note_id}")
    assert delete_resp.status_code == 204

    # Gone for good
    assert (await client.get(f"/notes/{note_id}")).status_code == 404
