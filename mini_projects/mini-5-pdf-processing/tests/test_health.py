async def test_health(client):
    """Humo: si esto pasa, la app arranca y los tests están bien cableados."""
    resp = await client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}
