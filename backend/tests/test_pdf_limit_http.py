from unittest.mock import patch
import pytest
from fastapi.testclient import TestClient
from backend.main import app
from backend.file_parser import PdfParseLimit, PdfParseBusy


@pytest.mark.parametrize("error,status", [(PdfParseLimit("page limit"), 400), (PdfParseBusy("busy"), 429)])
def test_upload_reports_parser_limits(error, status, monkeypatch):
    from backend import config

    monkeypatch.setattr(config, "AUTH_ENABLED", False)
    with patch("backend.api.routes.conversations.parse_file", side_effect=error):
        response = TestClient(app).post("/api/upload", files={"file": ("a.pdf", b"%PDF-test", "application/pdf")})
    assert response.status_code == status
    assert response.json()["detail"] == str(error)
