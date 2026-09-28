import pytest

from app.core.config import Settings
from app.interfaces.rag import FileRAGProvider
from app.services.hub_integration_service import HubIntegrationService


def test_file_rag_returns_cited_relevant_content(tmp_path):
    (tmp_path / "payment_policy.md").write_text(
        "# Payment policy\n\nPayment reminders require human approval before sending.",
        encoding="utf-8",
    )
    provider = FileRAGProvider(str(tmp_path))

    results = provider.search("How should a payment reminder be approved?")

    assert len(results) == 1
    assert "Source: payment_policy.md#" in results[0]
    assert "human approval" in results[0]


def test_hub_callback_requires_configured_secret():
    service = HubIntegrationService(Settings(), lead_service=None, sdr_copilot_service=None)

    with pytest.raises(RuntimeError):
        service.verify_secret("anything")


def test_hub_callback_rejects_wrong_secret():
    service = HubIntegrationService(
        Settings(hub_integration_secret="expected-secret"),
        lead_service=None,
        sdr_copilot_service=None,
    )

    with pytest.raises(PermissionError):
        service.verify_secret("wrong-secret")

    service.verify_secret("expected-secret")
