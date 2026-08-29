import pytest
from fastapi.testclient import TestClient
from unittest.mock import patch, MagicMock
import os, sys

# Ensure backend folder is in path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.main import app, SCHEMES, evaluate

client = TestClient(app)

def test_schemes_endpoint():
    res = client.get("/api/schemes")
    assert res.status_code == 200
    assert len(res.json()) > 0

def test_eligibility_deterministic_source_of_truth():
    profile = {
        "age": 20,
        "gender": "Female",
        "education_level": "B.Tech",
        "annual_income": 200000,
        "class12_percentile": 85,
        "institution_type": "AICTE approved"
    }
    res = client.post("/api/eligibility", json={"profile": profile})
    assert res.status_code == 200
    data = res.json()
    assert len(data) == len(SCHEMES)
    # Check that status ordering is likely_match first
    assert data[0]["result"]["status"] == "likely_match"

def test_understand_goal_fallback_when_no_api_key(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    res = client.post("/api/ai/understand-goal", json={"message": "Mujhe college ki fees ke liye scholarship chahiye"})
    assert res.status_code == 200
    data = res.json()
    assert data["intent"] == "education_financial_support"

def test_understand_goal_fallback_pregnancy(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    res = client.post("/api/ai/understand-goal", json={"message": "Maternity and mother welfare support maa"})
    assert res.status_code == 200
    data = res.json()
    assert data["intent"] == "pregnancy_support"

def test_explain_match_fallback_when_no_api_key(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    profile = {"age": 20, "gender": "Female"}
    res = client.post("/api/ai/explain-match", json={"profile": profile, "scheme_id": "pragati"})
    assert res.status_code == 200
    data = res.json()
    assert "Your answers match" in data["summary"] or "This may fit" in data["summary"]
    # Check deterministic eligibility engine remains unchanged inside result
    assert "status" in data["result"]

def test_understand_goal_live_openai_path(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-fake-test-key")
    
    mock_openai = MagicMock()
    mock_chat = MagicMock()
    mock_response = MagicMock()
    mock_choice = MagicMock()
    mock_message = MagicMock()
    
    mock_message.content = '{"intent": "hinglish_custom_scholarship", "possible_profile_fields": ["annual_income", "education_level"]}'
    mock_choice.message = mock_message
    mock_response.choices = [mock_choice]
    mock_chat.completions.create.return_value = mock_response
    mock_openai.return_value.chat = mock_chat

    with patch("openai.OpenAI", mock_openai):
        res = client.post("/api/ai/understand-goal", json={"message": "Bhai scholarship milegi kya B.Tech ke liye?"})
        assert res.status_code == 200
        data = res.json()
        assert data["intent"] == "hinglish_custom_scholarship"
        assert "annual_income" in data["possible_profile_fields"]

def test_explain_match_live_openai_path(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-fake-test-key")
    
    mock_openai = MagicMock()
    mock_chat = MagicMock()
    mock_response = MagicMock()
    mock_choice = MagicMock()
    mock_message = MagicMock()
    
    mock_message.content = "OpenAI generated explanation: Based on your engineering degree and income, Pragati fits well."
    mock_choice.message = mock_message
    mock_response.choices = [mock_choice]
    mock_chat.completions.create.return_value = mock_response
    mock_openai.return_value.chat = mock_chat

    with patch("openai.OpenAI", mock_openai):
        profile = {"age": 20, "gender": "Female"}
        res = client.post("/api/ai/explain-match", json={"profile": profile, "scheme_id": "pragati"})
        assert res.status_code == 200
        data = res.json()
        assert data["summary"] == "OpenAI generated explanation: Based on your engineering degree and income, Pragati fits well."
        # Ensure deterministic eligibility evaluation result is preserved verbatim
        target_scheme = next(s for s in SCHEMES if s["id"] == "pragati")
        expected_result = evaluate(target_scheme, profile)
        assert data["result"] == expected_result
