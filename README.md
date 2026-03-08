# HackCanadaApp

HackCanadaApp is an AI-powered interview preparation platform with a React frontend and Python backends.
It combines interview discovery, personalized prep context, mock interviews, and multimodal feedback (speech, stress/body-language cues, and answer quality).

## What this repo contains

- **Frontend**: Vite + React app in `Behaviourly-frontend/Behviourly-frontend`.
- **FastAPI backend** (`hackcanada-backend/main.py`, default port `8001`): mock interview generation, video analysis, transcription, answer analysis, reporting, and session state.
- **Flask/Auth backend** (`hackcanada-backend/Auth.py`, default port `8000`): Auth0 login flow, interview records, interview context + question retrieval/generation.
- **Scanner worker** (`hackcanada-backend/Scanner.py`): optional Gmail scanner that detects interview emails, stores interviews, and can send WhatsApp notifications.

## Core user flow

1. User signs in via Auth0 (Google social connection).
2. Dashboard lists detected interviews (or user can create one manually).
3. User opens an interview prep kit (`/interview-context`) with company/role briefing.
4. User starts mock interview (`/interview`) with generated/fallback questions.
5. During each answer, frontend records video and submits it for AI feedback.
6. Backend returns transcript + analysis (Gemini, optional Presage physiology) and aggregates data for final report.

## Tech stack

### Frontend
- React 19
- React Router
- Vite
- CSS modules/files per page/component

### Backend
- FastAPI + Uvicorn
- Flask + SQLAlchemy
- Google Gemini (`google-genai`)
- OpenAI Whisper fallback path for transcription (if configured)
- Presage Physiology API integration (video upload + vitals retrieval)
- Auth0 OAuth + Management API

## Project structure

```text
.
├── README.md
├── docs/
│   └── PRESAGE_REALTIME_PLAN.md
├── hackcanada-backend/
│   ├── main.py                 # FastAPI interview + analysis API
│   ├── Auth.py                 # Flask Auth0 + interview CRUD API
│   ├── Scanner.py              # Optional background Gmail scanner
│   ├── interview_context.py    # FastAPI router for interview context generation
│   ├── requirements.txt
│   └── users.db                # Local SQLite DB (development)
├── Behaviourly-frontend/
│   └── Behviourly-frontend/
│       ├── src/
│       ├── package.json
│       └── vite.config.js
└── package.json                # Root scripts to run frontend + FastAPI together
```

## Prerequisites

- **Node.js** 18+
- **npm**
- **Python** 3.10+
- Auth0 tenant/apps (for login flow)
- API keys depending on features:
  - `GEMINI_API_KEY` (required for most AI endpoints)
  - `OPENAI_API_KEY` (optional transcription path)
  - `PRESAGE_API_KEY` (optional physiology analysis)

## Environment variables

Create `.env` at the repo root (or in `hackcanada-backend/` for backend-only local use).

### Commonly used variables

```bash
# AI
GEMINI_API_KEY=...
OPENAI_API_KEY=...
PRESAGE_API_KEY=...
ELEVENLABS_API_KEY=...
ELEVENLABS_VOICE_ID=...
ELEVENLABS_MODEL_ID=eleven_multilingual_v2

# Auth0 / Flask auth service
AUTH0_DOMAIN=...
AUTH0_CLIENT_ID=...
AUTH0_CLIENT_SECRET=...
AUTH0_M2M_CLIENT_ID=...
AUTH0_M2M_CLIENT_SECRET=...
FLASK_SECRET_KEY=...
REDIRECT_URI=http://localhost:8000/callback
FRONTEND_URL=http://localhost:5173
DATABASE_URL=sqlite:///users.db

# Optional scanner + Twilio
SCAN_INTERVAL=1800
TWILIO_ACCOUNT_SID=...
TWILIO_AUTH_TOKEN=...
TWILIO_WHATSAPP_NUMBER=whatsapp:+14155238886
MY_PERSONAL_PHONE=whatsapp:+1XXXXXXXXXX
```

### Frontend Vite variables (optional)

Create `Behaviourly-frontend/Behviourly-frontend/.env` if you need overrides:

```bash
VITE_API_BASE_URL=http://127.0.0.1:8001
VITE_AUTH_API_BASE_URL=http://localhost:8000
VITE_ELEVENLABS_VOICE_ID= # optional override; backend ELEVENLABS_VOICE_ID is default
VITE_ELEVENLABS_MODEL_ID= # optional override; backend ELEVENLABS_MODEL_ID is default
```

## Installation

### 1) Install root + frontend npm dependencies

```bash
npm install
npm install --prefix Behaviourly-frontend/Behviourly-frontend
```

### 2) Install Python dependencies

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r hackcanada-backend/requirements.txt
```

## Running the app

### Option A: Start FastAPI + frontend together (recommended)

From repo root:

```bash
npm start
```

This runs:
- FastAPI backend on `http://0.0.0.0:8001`
- Vite frontend on `http://localhost:5173`

### Option B: Run services manually

#### FastAPI backend
```bash
cd hackcanada-backend
uvicorn main:app --reload --host 0.0.0.0 --port 8001
```

#### Flask/Auth backend
```bash
cd hackcanada-backend
python Auth.py
```

#### Frontend
```bash
npm run dev --prefix Behaviourly-frontend/Behviourly-frontend
```

## API overview

### FastAPI (`:8001`)
- `GET /health` - liveness check
- `GET /health/ready` - readiness check for Gemini-dependent paths
- `POST /mock-interview` - generate interview questions
- `POST /gemini/analyze-video` - analyze uploaded answer video
- `POST /transcribe` - transcript extraction from uploaded media
- `POST /tts` - ElevenLabs text-to-speech proxy (returns audio)
- `POST /analyze-answer` - evaluate answer quality for a question
- `POST /presage/analyze` - optional physiology analysis from video
- `POST /report` - generate final interview report
- `POST /reset-session` - reset in-memory scoring/session
- `WebSocket /ws/live` - live signals/events stream

### Flask/Auth (`:8000`)
- `GET /login`, `GET /callback`, `GET /logout` - authentication flow
- `GET /me` - current user info from session
- `GET /interviews` - list interview records for user
- `GET /interviews/<id>/questions` - fetch saved questions
- `POST /interviews/<id>/generate-questions` - generate and persist interview questions
- `GET /interviews/<id>/context` - fetch/generate interview prep context

## Scanner (optional background job)

`hackcanada-backend/Scanner.py` can be run in one-shot or loop mode to detect interview emails in Gmail.

```bash
cd hackcanada-backend
python Scanner.py
# or
python Scanner.py --loop
```

It relies on Auth0-stored Google tokens and persists interview records/questions in the local database.

## Notes / known caveats

- The frontend folder is intentionally named `Behviourly-frontend` (typo preserved in existing scripts).
- `hackcanada-backend/users.db` is committed and used for local development.
- Presage Python SDK is currently commented out in requirements due dependency conflicts; REST API flow is used/planned in this repo.
- Some frontend endpoints are hardcoded to `http://localhost:8000` for auth-related routes.

## Additional docs

- Presage integration planning: `docs/PRESAGE_REALTIME_PLAN.md`

## Quick troubleshooting

- If `/interview` shows backend or AI not ready:
  - Ensure FastAPI is running on `:8001`.
  - Ensure `GEMINI_API_KEY` is set.
- If login loops or callback fails:
  - Verify Auth0 callback/logout URLs match local ports.
  - Ensure Flask/Auth service is running on `:8000`.
- If interview dashboard is empty:
  - Log in first (`/login`) and verify session cookies are enabled.
  - Ensure interview records exist in the local DB for your logged-in user.
