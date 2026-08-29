# Mera Adhikaar

Independent public-service hackathon prototype. It helps citizens discover benefits, understand published criteria, prepare a mock application and follow a mock tracker. It is not an official government website and never submits to government systems.

## Architecture

- Frontend: React + TypeScript + Vite
- Backend: FastAPI
- Data: local JSON (`backend/data/schemes.json`)
- Eligibility: deterministic backend rules engine
- Storage: none; mock applications are not retained
- AI: OpenAI-powered Hinglish intent understanding and scheme explanations when `OPENAI_API_KEY` is provided, with deterministic local fallbacks when unavailable. Deterministic rule evaluation remains the sole source of truth for eligibility.

## Recommended deployment: one service

Build the Vite frontend, then FastAPI serves both `dist/` and `/api` from the same origin. This is already configured in `backend/app/main.py`; do not deploy `dist/` by itself.

### Local production run

```bash
npm ci
npm run build
python -m pip install -r requirements.txt
python -m uvicorn backend.app.main:app --host 0.0.0.0 --port 8000
```

Open `http://localhost:8000`.

### Docker

```bash
docker build -t mera-adhikaar .
docker run --rm -p 8000:8000 -e PORT=8000 mera-adhikaar
```

Deploy this Dockerfile to a container host. Use `GET /api/schemes` for the health check.

## Environment variables

| Variable | Required | Service | Purpose |
| --- | --- | --- | --- |
| `PORT` | Host-dependent | Backend | Uvicorn port; Docker defaults to `8000`. |
| `CORS_ORIGINS` | Only with split deployment | Backend | Comma-separated public frontend origins. Leave blank for the recommended one-service deployment. |
| `OPENAI_API_KEY` | No | Backend | OpenAI API key for Hinglish intent understanding & scheme explanations. Uses deterministic fallback if unset. |
| `OPENAI_MODEL` | No | Backend | OpenAI model name (defaults to `gpt-4o-mini`). |


The frontend has no environment variables. Its API URL is the same-origin relative path `/api`.

## If you must split deployments

Deploy `dist/` to the frontend host and the FastAPI service separately. Set `CORS_ORIGINS=https://your-frontend.example.com` on the backend and configure a same-origin `/api` proxy at the edge. The checked-in build is optimised for a single service.

## Safety and limitations

- All personas and applications are synthetic/mock.
- No Aadhaar, PAN, OTP, password, bank or payment data is requested.
- No government system is accessed.
- Every scheme record has an official source URL and verification date; unconfirmed cycles are labelled “Verification required”.
- No database, uploads, authentication, or persistent application storage is present.
