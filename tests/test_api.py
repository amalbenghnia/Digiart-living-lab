"""API integration tests via FastAPI's TestClient.

Important design note: app.core.container.get_container is @lru_cache'd
for production (one composition root per process). For tests we override
it via FastAPI's dependency_overrides with a FRESH Container per test, so
one test's writes to the in-memory prototype repository never leak into
the next test. Never remove this override — without it the suite becomes
order-dependent and flaky.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.core.config import DataSourceMode, LLMProviderName, Settings
from app.core.container import Container, get_container
from app.main import app
from tests.conftest import FakeLLMProvider


@pytest.fixture
def client(monkeypatch):
    settings = Settings(
        data_source_mode=DataSourceMode.PROTOTYPE,
        llm_provider=LLMProviderName.OLLAMA,
        n8n_webhook_base_url=None,
    )
    container = Container(settings)
    # Swap in the deterministic fake LLM so API tests never hit the network.
    container.llm_provider = FakeLLMProvider()
    container.qualification_service._llm = container.llm_provider

    app.dependency_overrides[get_container] = lambda: container
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


class TestHealth:
    def test_health_ok(self, client):
        response = client.get("/health")
        assert response.status_code == 200
        assert response.json() == {"status": "ok"}


class TestLeadsEndpoints:
    def test_list_leads_returns_seed_data(self, client):
        response = client.get("/leads")
        assert response.status_code == 200
        body = response.json()
        assert body["count"] == 5

    def test_get_single_lead(self, client):
        response = client.get("/lead/lead-001")
        assert response.status_code == 200
        assert response.json()["id"] == "lead-001"

    def test_get_missing_lead_returns_404(self, client):
        response = client.get("/lead/does-not-exist")
        assert response.status_code == 404

    def test_create_lead_success(self, client):
        payload = {
            "fullname": "New Lead",
            "phone": "+21655555555",
            "email": "new.lead@example.com",
            "training": "Graphic Design",
            "source": "website",
        }
        response = client.post("/lead/new", json=payload)
        assert response.status_code == 201
        assert response.json()["fullname"] == "New Lead"

    def test_create_lead_missing_contact_returns_422(self, client):
        payload = {
            "fullname": "No Contact",
            "phone": None,
            "email": None,
            "training": "Graphic Design",
        }
        response = client.post("/lead/new", json=payload)
        assert response.status_code == 422

    def test_create_duplicate_lead_returns_409(self, client):
        payload = {
            "fullname": "Duplicate Of Lead 001",
            "phone": "+21620000001",  # matches seeded lead-001
            "training": "Python for AI",
        }
        response = client.post("/lead/new", json=payload)
        assert response.status_code == 409

    def test_analyse_lead_returns_priority(self, client):
        response = client.post("/lead/analyse", json={"lead_id": "lead-002"})
        assert response.status_code == 200
        body = response.json()
        assert body["priority"] in {"P0", "P1", "P2"}

    def test_analyse_unknown_lead_returns_404(self, client):
        response = client.post("/lead/analyse", json={"lead_id": "nope"})
        assert response.status_code == 404

    def test_update_lead_status_valid_transition(self, client):
        response = client.put("/lead/lead-002", json={"status": "qualified"})
        assert response.status_code == 200
        assert response.json()["status"] == "qualified"

    def test_update_lead_status_invalid_transition(self, client):
        response = client.put("/lead/lead-004", json={"status": "new"})
        assert response.status_code == 422

    def test_duplicate_check_endpoint(self, client):
        response = client.post("/lead/duplicate", json={"phone": "+21620000001"})
        assert response.status_code == 200
        assert response.json()["is_duplicate"] is True

    def test_priority_endpoint(self, client):
        response = client.post("/lead/priority", json={"lead_id": "lead-005"})
        assert response.status_code == 200
        assert response.json()["priority"] == "P1"
        assert response.json()["is_payment_overdue"] is False

    def test_priority_endpoint_exposes_overdue_payment_state(self, client):
        response = client.post("/lead/priority", json={"lead_id": "lead-004"})
        assert response.status_code == 200
        assert response.json()["is_payment_overdue"] is True
        assert response.json()["days_overdue"] >= 3

    def test_list_leads_sorted_by_priority_no_crash(self, client):
        response = client.get("/leads?sort_by=priority")
        assert response.status_code == 200
        leads = response.json()["leads"]
        assert len(leads) == 5
        # Verify P0 leads are first
        assert leads[0]["priority"] == "P0"

    def test_mark_lead_called_success(self, client):
        response = client.post("/lead/lead-001/mark-called", json={"called_by": "Ines Zouaoui"})
        assert response.status_code == 200
        body = response.json()
        assert body["called"] is True
        assert body["called_by"] == "Ines Zouaoui"
        assert body["status"] == "contacted"

    def test_get_uncalled_urgent_leads(self, client):
        response = client.get("/leads/uncalled-urgent")
        assert response.status_code == 200
        body = response.json()
        assert body["count"] >= 1
        assert body["leads"][0]["id"] == "lead-001"

    def test_export_leads_excel(self, client):
        response = client.get("/leads/export-excel")
        assert response.status_code == 200
        assert "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet" in response.headers["content-type"]


class TestDashboardEndpoint:
    def test_dashboard_counts_are_consistent(self, client):
        response = client.get("/dashboard")
        assert response.status_code == 200
        body = response.json()
        assert body["total_leads"] == 5
        assert body["payment_overdue"] >= 1  # lead-004 in the seed data
        assert "llm_hourly_quota" in body
