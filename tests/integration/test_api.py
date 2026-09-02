"""Integration test: FastAPI health endpoint."""

import pytest
from httpx import ASGITransport, AsyncClient

from yaf_api.main import app


@pytest.mark.asyncio
async def test_health():
    """Verify the health endpoint returns 200 OK."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert data["version"] == "0.1.0"

@pytest.mark.asyncio
async def test_api_v1_health():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/api/v1/health")
        assert resp.status_code == 200


@pytest.mark.asyncio
async def test_discovery_vertical_slice():
    """A small synchronous run returns ranked, visualizable candidates."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/api/v1/discoveries?wait=true",
            json={
                "name": "wifi_discovery",
                "center_frequency_ghz": 2.4,
                "bandwidth_mhz": 100,
                "target_gain_dbi": 4.0,
                "target_vswr": 2.0,
                "minimum_efficiency": 0.65,
                "max_width_mm": 100,
                "max_height_mm": 100,
                "max_depth_mm": 30,
                "candidate_budget": 6,
                "generations": 2,
                "verify_top_k": 0,
                "seed": 11,
            },
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["state"] == "completed"
    assert payload["progress"] == 1.0
    assert payload["explored_count"] == 6
    assert payload["best_candidate"] is not None
    assert payload["best_candidate"]["geometry"]["vertices"]
    assert payload["best_candidate"]["evaluation_mode"] == "analytical_screening"
