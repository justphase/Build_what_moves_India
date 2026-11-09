import io
import os
import sys
import pytest
from fastapi.testclient import TestClient
from unittest.mock import patch, MagicMock, AsyncMock

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
        "institution_type": "AICTE approved",
    }
    res = client.post("/api/eligibility", json={"profile": profile})
    assert res.status_code == 200
    data = res.json()
    assert len(data) == len(SCHEMES)
    # Check that status ordering is likely_match first
    assert data[0]["result"]["status"] == "likely_match"


def test_understand_goal_fallback_when_no_api_key(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    res = client.post(
        "/api/ai/understand-goal",
        json={"message": "Mujhe college ki fees ke liye scholarship chahiye"},
    )
    assert res.status_code == 200
    data = res.json()
    assert data["intent"] == "education_financial_support"


def test_understand_goal_fallback_pregnancy(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    res = client.post(
        "/api/ai/understand-goal",
        json={"message": "Maternity and mother welfare support maa"},
    )
    assert res.status_code == 200
    data = res.json()
    assert data["intent"] == "pregnancy_support"


def test_explain_match_fallback_when_no_api_key(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    profile = {"age": 20, "gender": "Female"}
    res = client.post(
        "/api/ai/explain-match", json={"profile": profile, "scheme_id": "pragati"}
    )
    assert res.status_code == 200
    data = res.json()
    assert (
        "Your answers match" in data["summary"]
        or "This may fit" in data["summary"]
    )
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
        res = client.post(
            "/api/ai/understand-goal",
            json={"message": "Bhai scholarship milegi kya B.Tech ke liye?"},
        )
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
        res = client.post(
            "/api/ai/explain-match",
            json={"profile": profile, "scheme_id": "pragati"},
        )
        assert res.status_code == 200
        data = res.json()
        assert (
            data["summary"]
            == "OpenAI generated explanation: Based on your engineering degree and income, Pragati fits well."
        )
        # Ensure deterministic eligibility evaluation result is preserved verbatim
        target_scheme = next(s for s in SCHEMES if s["id"] == "pragati")
        expected_result = evaluate(target_scheme, profile)
        assert data["result"] == expected_result


def test_voice_status_endpoint(monkeypatch):
    monkeypatch.setenv("GNANI_API_KEY", "gnani-test-key-123")
    res = client.get("/api/voice/status")
    assert res.status_code == 200
    data = res.json()
    assert data["gnani_configured"] is True
    assert data["base_url"] == "https://api.vachana.ai"
    assert data["stt_model"] == "prisma-v3.0"
    assert data["tts_model"] == "timbre-v2.5"
    assert "Nalini" in data["supported_voices"]


def test_gnani_stt_missing_key_returns_503(monkeypatch):
    monkeypatch.delenv("GNANI_API_KEY", raising=False)
    fake_wav = b"RIFF" + b"\x00" * 128
    res = client.post(
        "/api/voice/stt",
        files={"audio_file": ("test.wav", io.BytesIO(fake_wav), "audio/wav")},
        data={"language_code": "hi-IN", "model": "prisma-v3.0"},
    )
    assert res.status_code == 503
    data = res.json()
    assert data["success"] is False
    assert data["code"] == "GNANI_API_KEY_MISSING"


def test_gnani_stt_live_vachana_integration(monkeypatch):
    monkeypatch.setenv("GNANI_API_KEY", "gnani-live-test-key")

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "success": True,
        "request_id": "5c1f0a52-6d62-4e0b-9a38-2f2b8a8f7a10",
        "transcript": "Meri family ki income 1.5 lakh hai. Main Rajasthan se hoon.",
        "model": "prisma-v3.0",
        "detected_language_code": "hi-IN",
        "processing_time": 0.42,
        "end_to_end_latency": 0.51,
    }

    mock_async_client = AsyncMock()
    mock_async_client.__aenter__.return_value.post.return_value = mock_resp

    with patch("httpx.AsyncClient", return_value=mock_async_client):
        fake_wav = b"RIFF" + b"\x00" * 200
        res = client.post(
            "/api/voice/stt",
            files={"audio_file": ("recording.wav", io.BytesIO(fake_wav), "audio/wav")},
            data={"language_code": "indic-auto", "model": "prisma-v3.0", "format": "transcribe"},
        )
        assert res.status_code == 200
        data = res.json()
        assert data["success"] is True
        assert data["provider"] == "gnani-prisma"
        assert "1.5 lakh" in data["transcript"]
        assert data["detected_language_code"] == "hi-IN"

        # Verify request sent to https://api.vachana.ai/stt/v3 with X-API-Key-ID header
        call_args = mock_async_client.__aenter__.return_value.post.call_args
        assert call_args[0][0] == "https://api.vachana.ai/stt/v3"
        assert call_args[1]["headers"]["X-API-Key-ID"] == "gnani-live-test-key"


def test_gnani_tts_live_vachana_integration(monkeypatch):
    monkeypatch.setenv("GNANI_API_KEY", "gnani-live-test-key")

    fake_wav_output = b"RIFF\x24\x00\x00\x00WAVEfmt " + b"\x00" * 64
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.headers = {"content-type": "audio/wav"}
    mock_resp.content = fake_wav_output

    mock_async_client = AsyncMock()
    mock_async_client.__aenter__.return_value.post.return_value = mock_resp

    with patch("httpx.AsyncClient", return_value=mock_async_client):
        res = client.post(
            "/api/voice/tts",
            json={
                "text": "नमस्ते, आप प्रधानमंत्री आवास योजना के लिए पात्र हो सकते हैं।",
                "language": "hi-IN",
                "voice": "Nalini",
                "model": "timbre-v2.5",
                "speed": 1.0,
            },
        )
        assert res.status_code == 200
        assert res.headers["content-type"] == "audio/wav"
        assert res.headers["x-voice-provider"] == "gnani-timbre"
        assert res.content == fake_wav_output

        call_args = mock_async_client.__aenter__.return_value.post.call_args
        assert call_args[0][0] == "https://api.vachana.ai/api/v1/tts/inference"
        assert call_args[1]["headers"]["X-API-Key-ID"] == "gnani-live-test-key"
        sent_json = call_args[1]["json"]
        assert sent_json["model"] == "timbre-v2.5"
        assert sent_json["voice"] == "Nalini"
        assert sent_json["audio_config"]["container"] == "wav"


def test_conversational_chat_rajasthan_income_extraction():
    res = client.post(
        "/api/ai/chat",
        json={
            "message": "Meri family ki income 1.5 lakh hai. Main Rajasthan se hoon. Mujhe kaunsi government schemes mil sakti hain?",
            "profile": {},
            "language": "HINGLISH",
        },
    )
    assert res.status_code == 200
    data = res.json()
    assert data["updated_profile"]["annual_income"] == 150000
    assert data["updated_profile"]["state"] == "Rajasthan"
    assert data["trust_metadata"]["deterministic_engine"] is True
    assert len(data["matches"]) == len(SCHEMES)
    assert len(data["highlighted_schemes"]) > 0
    assert len(data["spoken_reply"]) > 10


def test_conversational_chat_pm_awas_query():
    res = client.post(
        "/api/ai/chat",
        json={
            "message": "Kya main PM Awas Yojana ke liye eligible hoon?",
            "profile": {"annual_income": 200000, "age": 28},
            "language": "HINGLISH",
        },
    )
    assert res.status_code == 200
    data = res.json()
    assert data["highlighted_schemes"][0]["scheme"]["id"] == "pmay-u"
    assert "Pradhan Mantri Awas Yojana" in data["reply"]


def test_conversational_chat_missing_income_certificate():
    res = client.post(
        "/api/ai/chat",
        json={
            "message": "Mere paas income certificate nahi hai.",
            "profile": {"state": "Rajasthan"},
            "language": "HINGLISH",
        },
    )
    assert res.status_code == 200
    data = res.json()
    assert data["trust_metadata"]["missing_document_addressed"] == "Income certificate"
    assert "Sukanya Samriddhi Account" in data["reply"]


def test_conversational_chat_gnani_devanagari_itn_transcript():
    res = client.post(
        "/api/ai/chat",
        json={
            "message": "मेरी फैमिली की इनकम 1,50,000 है और मैं राजस्थान से हूँ।",
            "profile": {},
            "language": "HI",
        },
    )
    assert res.status_code == 200
    data = res.json()
    assert data["updated_profile"]["annual_income"] == 150000
    assert data["updated_profile"]["state"] == "Rajasthan"

