# Mera Adhikaar Voice

**Tagline:** *Your Voice. Your Rights. Your Schemes.*

**Mera Adhikaar Voice** is a voice-first, bilingual (Hindi, Hinglish, and English) AI welfare scheme discovery and deterministic eligibility platform built for the **Gnani AI Internship Challenge**. It empowers Indian citizens—especially those with limited digital literacy—to discover government welfare schemes, verify exact eligibility rules, understand required documents, and prepare applications simply by speaking in their own language.

---

## 1. Problem Statement

Millions of eligible Indian citizens miss out on central and state welfare schemes (scholarships, maternity benefits, housing subsidies, healthcare assurance, disability support) because:
1. Official scheme portals and PDF guidelines are complex, text-heavy, and difficult to navigate for first-time internet users.
2. Citizens often speak in natural **Hindi** or **code-mixed Hinglish** (e.g., *"Meri family ki income 1.5 lakh hai, main Rajasthan se hoon, mujhe kaunsi government schemes mil sakti hain?"*), which rigid keyword forms fail to understand.
3. Generic AI chatbots hallucinate scheme benefits or invent eligibility rules, eroding citizen trust and leading to rejected applications due to missing documents (such as an Income Certificate or Jan Aadhaar).

---

## 2. Solution Explanation

**Mera Adhikaar Voice** combines **Gnani AI's sovereign Indic speech models (`api.vachana.ai`)** with a **100% deterministic scheme eligibility engine**:

```
Microphone (16kHz PCM WAV)
   ↓
Gnani AI Speech-to-Text (POST https://api.vachana.ai/stt/v3 · Model: prisma-v3.0)
   ↓
Multilingual NLU & Profile Extraction (Hindi / Hinglish / English → Income, State, Age, Course, Category)
   ↓
Deterministic Eligibility Engine (check() & evaluate() against published government rules)
   ↓
Grounded Citizen Explanation + Document Readiness & Application Steps
   ↓
Gnani AI Text-to-Speech (POST https://api.vachana.ai/api/v1/tts/inference · Model: timbre-v2.5)
```

### Key Architectural Guarantees
- **Zero Hallucinated Eligibility:** LLMs never decide whether a user is eligible. All eligibility statuses (`likely_match`, `possible_match`, `not_match`), matched criteria, unmatched criteria, and missing criteria are computed strictly by deterministic rule evaluation in `backend/app/main.py`.
- **Voice-First Accessibility:** Citizens can speak in Hindi, Hinglish, or Indian English, watch a real-time microphone waveform, hear responses spoken back via Gnani Timbre voices (`Nalini`, `Karan`, `Simran`, `Raju`), stop playback at any time, or fall back seamlessly to browser speech or text input.
- **Document & Readiness Guidance:** Handles practical citizen blockers such as *"Mere paas income certificate nahi hai"* by identifying schemes that do not require an income certificate and explaining how to obtain one via e-Mitra / CSC.

---

## 3. Technology Stack

- **Frontend:** React 19, TypeScript, Vite, Web Audio API (`AudioContext` + `AnalyserNode` live waveform + in-browser 16kHz 16-bit mono WAV encoder)
- **Backend:** FastAPI (Python), Pydantic v2, `httpx` (async Gnani AI client), `python-multipart`
- **Voice AI (Primary):** **Gnani AI Vachana Platform (`https://api.vachana.ai`)**
  - **Speech-to-Text (STT):** `POST /stt/v3` using **Gnani Prisma (`prisma-v3.0` / `prisma-v2.5`)**
  - **Text-to-Speech (TTS):** `POST /api/v1/tts/inference` using **Gnani Timbre (`timbre-v2.5` / `timbre-v3.0`)**
- **Conversational NLU:** Deterministic Hindi/Hinglish/English entity extractor + optional OpenAI (`gpt-4o-mini`) phrasing enhancement
- **Data & Rules Engine:** Local verified JSON dataset (`backend/data/schemes.json`) covering Central & State (Rajasthan) schemes with official `.gov.in` / `.org` URLs

---

## 4. Gnani AI API Integration Details

All Gnani AI calls are routed securely through the FastAPI backend so that `GNANI_API_KEY` is never exposed to the browser.

| Capability | Gnani AI Endpoint | Model | Auth Header | Format |
| --- | --- | --- | --- | --- |
| **Speech-to-Text (STT)** | `POST https://api.vachana.ai/stt/v3` | `prisma-v3.0` (multilingual auto-detect) / `prisma-v2.5` | `X-API-Key-ID: <GNANI_API_KEY>` | `multipart/form-data` (`audio_file`, `model`, `language_code`, `format=transcribe`) |
| **Text-to-Speech (TTS)** | `POST https://api.vachana.ai/api/v1/tts/inference` | `timbre-v2.5` / `timbre-v3.0` (Voices: `Nalini`, `Karan`, `Simran`, `Raju`) | `X-API-Key-ID: <GNANI_API_KEY>` | JSON request with `audio_config` (`linear_pcm`, `wav`, `48000` Hz) → returns `audio/wav` binary stream |

### Backend Voice Routes
- `GET /api/voice/status` — Reports whether `GNANI_API_KEY` is configured, active models (`prisma-v3.0`, `timbre-v2.5`), and supported voices/languages.
- `POST /api/voice/stt` — Validates uploaded WAV audio and proxies to `https://api.vachana.ai/stt/v3`.
- `POST /api/voice/tts` — Strips markdown formatting and proxies speech synthesis to `https://api.vachana.ai/api/v1/tts/inference`.
- `POST /api/ai/chat` — Extracts profile fields from Hindi/Hinglish/English input, runs the deterministic eligibility engine, and returns both rich display text and a clean `spoken_reply` for Gnani TTS.

---

## 5. Environment Variables

Copy `.env.example` to `.env` and configure:

| Variable | Required | Default | Purpose |
| --- | --- | --- | --- |
| `GNANI_API_KEY` | Yes (for live Gnani cloud STT/TTS) | — | Gnani AI API key passed in `X-API-Key-ID` header to `https://api.vachana.ai`. |
| `GNANI_BASE_URL` | No | `https://api.vachana.ai` | Base URL for Gnani AI Vachana API. |
| `GNANI_STT_MODEL` | No | `prisma-v3.0` | Gnani STT model (`prisma-v3.0` or `prisma-v2.5`). |
| `GNANI_TTS_MODEL` | No | `timbre-v2.5` | Gnani TTS model (`timbre-v2.5` or `timbre-v3.0`). |
| `GNANI_TTS_VOICE` | No | `Nalini` | Default Gnani Timbre voice (`Nalini`, `Karan`, `Simran`, `Raju`). |
| `OPENAI_API_KEY` | No | — | Optional OpenAI key for NLU/explanation phrasing. Deterministic NLU + rule evaluation runs automatically if omitted. |
| `OPENAI_MODEL` | No | `gpt-4o-mini` | Optional OpenAI model name. |
| `PORT` | No | `8000` | Backend HTTP server port. |
| `CORS_ORIGINS` | No | `""` | Comma-separated origins if frontend is hosted separately. |

---

## 6. Setup & Run Instructions

### Local Production Run (Single Service)

```bash
npm ci
npm run build
python -m pip install -r requirements.txt
python -m uvicorn backend.app.main:app --host 0.0.0.0 --port 8000
```

Open `http://localhost:8000`.

### Local Development Mode (Hot Reload)

```bash
# Terminal 1: Start FastAPI backend on port 8000
python -m uvicorn backend.app.main:app --reload --port 8000

# Terminal 2: Start Vite dev server on port 5173 (proxies /api to 127.0.0.1:8000)
npm run dev
```

### Run Backend Tests

```bash
python -m pytest -v
```

---

## 7. Deployment Instructions

### Docker (Recommended Single-Container Deployment)

```bash
docker build -t mera-adhikaar-voice .
docker run --rm -p 8000:8000 --env-file .env mera-adhikaar-voice
```

- **Render / Railway / Fly.io / Cloud Run:** Deploy directly using the repository `Dockerfile`. Set `GNANI_API_KEY` (and optionally `OPENAI_API_KEY`) in the platform's environment variables. Use `GET /api/schemes` or `GET /api/voice/status` as the health check path.

---

## 8. 60–90 Second Demo Video Script

- **0:00 – 0:15 (Hook & Problem):**
  *"Meet Ramesh from Rajasthan. His family earns ₹1.5 lakh a year, and his daughter just passed Class 12. There are dozens of central and state welfare schemes they qualify for—but navigating English PDF notices and rigid forms is overwhelming. Welcome to **Mera Adhikaar Voice**—Your Voice, Your Rights, Your Schemes."*
- **0:15 – 0:40 (Live Gnani AI Voice Interaction):**
  *Click **Start Voice Discovery**. Tap the microphone and speak in Hinglish:*
  *"Meri family ki income 1.5 lakh hai. Main Rajasthan se hoon. Mujhe kaunsi government schemes mil sakti hain?"*
  *Show the live microphone waveform, Gnani AI Prisma v3.0 transcription badge, and watch the Detected Citizen Profile panel automatically populate `State: Rajasthan` and `Annual Income: ₹1,50,000`.*
- **0:40 – 1:05 (Deterministic Engine + Gnani Timbre Voice Response):**
  *The assistant responds in text and speaks aloud via Gnani Timbre v2.5 (`Nalini`), highlighting **Ayushman Bharat PM-JAY**, **Kalibai Bheel Medhavi Chhatra Yojana**, and **PM-USP Scholarship**, while asking follow-up questions to confirm remaining criteria. Next, ask: "Mere paas income certificate nahi hai" and show how it guides the user on alternative schemes and e-Mitra application steps.*
- **1:05 – 1:25 (Scheme Dashboard & Trust):**
  *Switch to the **Scheme Dashboard**, filter by **Likely Eligible** and **Potentially Eligible**, inspect matched vs. missing criteria, check off required documents, and highlight the architectural guarantee: Gnani AI powers natural Indic speech, while deterministic rules guarantee zero hallucinated eligibility.*

---

## 9. LinkedIn / X Submission Announcement

> Excited to share **Mera Adhikaar Voice** — *Your Voice. Your Rights. Your Schemes.* 🇮🇳🎙️
>
> Built for the **Gnani AI Internship Challenge**, Mera Adhikaar Voice transforms government welfare scheme discovery into an accessible Hindi, Hinglish & English voice conversation.
>
> 🔹 **Gnani AI Prisma v3.0 (`/stt/v3`)** for code-mixed Hinglish & Hindi speech-to-text with inverse text normalization
> 🔹 **Gnani AI Timbre v2.5 (`/api/v1/tts/inference`)** for natural Indic voice responses
> 🔹 **100% Deterministic Eligibility Engine** — AI extracts user profile intent, but published government criteria strictly decide eligibility (`Likely`, `Possible`, `Not Match`) with zero hallucinations
> 🔹 Built with FastAPI, React, TypeScript & Web Audio WAV encoding
>
> #GnaniAI #VoiceAI #IndicAI #DigitalPublicInfrastructure #FastAPI #React #GovTech
