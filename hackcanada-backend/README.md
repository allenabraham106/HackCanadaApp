# HackCanada Backend

## Mock interview API (FastAPI)

The **mock-interview** and related endpoints (question generation, answer analysis, etc.) are in **main.py**. You need this server running for the Behaviourly frontend interview flow to work.

**Run it:**

```bash
cd hackcanada-backend
uvicorn main:app --reload --port 8001
```

Keep this terminal open. The frontend is configured to call `http://localhost:8001` for the API (see `VITE_API_BASE_URL` in the frontend `.env`).

**Requirements:** Python 3.10+, and a `.env` in this folder or the repo root with `GEMINI_API_KEY` set.

## Auth (Flask, Gmail + Gemini questions)

The Auth server (port **8000**) serves `/login` and `/callback` for Google sign-in, plus:
- **`/interviews`** – list detected interviews (from Scanner).
- **`/interviews/<id>/questions`** – get stored Gemini questions for an interview.
- **`POST /interviews/<id>/generate-questions`** – generate and save Gemini behavioral questions for an interview (uses `GEMINI_API_KEY`; same format as Scanner). The app calls this when you open a detected interview that has no questions yet. **It must be running** for "Try it for free" or you’ll get "localhost sent an invalid response" when the app redirects to login.

1. **Create `.env`** from the example:
   ```bash
   cp .env.example .env
   ```
   Edit `.env` and set `AUTH0_DOMAIN`, `AUTH0_CLIENT_ID`, `AUTH0_CLIENT_SECRET`, and `FLASK_SECRET_KEY`.

2. **Install dependencies** (if needed):
   ```bash
   pip install flask requests python-dotenv sqlalchemy
   ```

3. **Run the Auth server** (default port 5000):
   ```bash
   python Auth.py
   ```

4. **Use a different port** (e.g. if 5000 is in use):
   ```bash
   PORT=5001 python Auth.py
   ```
   Then in `.env` set `REDIRECT_URI=http://localhost:5001/callback` and add that URL to Auth0 **Allowed Callback URLs**.
