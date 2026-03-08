# auth.py
# ─────────────────────────────────────────────────────────────────────────────
# Auth0 authorization layer with Google OAuth for Gmail background scanning.
#
# Auth0 acts as:
#   - Identity provider (login/signup via Google)
#   - Token vault (stores Google refresh tokens securely)
#   - User management (tracks all registered users)
#
# AUTH0 DASHBOARD SETUP:
#   1. Create a "Regular Web Application"
#   2. Enable the "google-oauth2" social connection
#   3. In that connection's settings:
#        - Add to Scopes:
#            https://www.googleapis.com/auth/gmail.readonly
#        - Toggle ON "Allow Offline Access" (for refresh tokens)
#   4. Application settings:
#        Allowed Callback URLs:  http://localhost:5000/callback
#        Allowed Logout URLs:    http://localhost:3000
#        Allowed Web Origins:    http://localhost:5000
#   5. APIs → Auth0 Management API → Machine to Machine Applications:
#        - Authorize your app
#        - Grant scopes: read:users, read:user_idp_tokens
#
# .env file:
#   AUTH0_DOMAIN=dev-xxxx.us.auth0.com
#   AUTH0_CLIENT_ID=your_client_id
#   AUTH0_CLIENT_SECRET=your_client_secret
#   FLASK_SECRET_KEY=generate-a-real-secret
#   REDIRECT_URI=http://localhost:5000/callback
#   FRONTEND_URL=http://localhost:3000
#   DATABASE_URL=sqlite:///users.db
#
# INSTALL:
#   pip install flask requests python-dotenv sqlalchemy
# ─────────────────────────────────────────────────────────────────────────────

import json
import os
import time
import secrets
import logging
import requests
import uuid
from functools import wraps
from urllib.parse import urlencode
from datetime import datetime, timezone

from flask import Flask, request, redirect, session, jsonify
from dotenv import load_dotenv
from sqlalchemy import create_engine, Column, String, DateTime, Boolean
from sqlalchemy.orm import declarative_base, sessionmaker
from flask_cors import CORS

# Optional Gemini for generating interview questions (same logic as Scanner)
try:
    from google import genai as _genai
    _GEMINI_AVAILABLE = bool(os.getenv("GEMINI_API_KEY"))
except Exception:
    _genai = None
    _GEMINI_AVAILABLE = False

load_dotenv()
# Load .env from repo root when running from hackcanada-backend/
_root_env = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".env")
if os.path.isfile(_root_env):
    load_dotenv(_root_env)
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)
app.secret_key = os.getenv("FLASK_SECRET_KEY", "dev-secret-change-in-prod")
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
CORS(app, supports_credentials=True, origins=[
    "http://localhost:5173", "http://localhost:5174", "http://localhost:5175", "http://127.0.0.1:5173", "http://127.0.0.1:5174", "http://127.0.0.1:5175"
])

AUTH0_DOMAIN        = os.getenv("AUTH0_DOMAIN")         # e.g. dev-xxxx.us.auth0.com
AUTH0_CLIENT_ID     = os.getenv("AUTH0_CLIENT_ID")       # Regular Web App (login)
AUTH0_CLIENT_SECRET = os.getenv("AUTH0_CLIENT_SECRET")   # Regular Web App (login)
AUTH0_M2M_CLIENT_ID     = os.getenv("AUTH0_M2M_CLIENT_ID")       # Machine to Machine (scanner)
AUTH0_M2M_CLIENT_SECRET = os.getenv("AUTH0_M2M_CLIENT_SECRET")   # Machine to Machine (scanner)
REDIRECT_URI        = os.getenv("REDIRECT_URI", "http://localhost:8000/callback")
FRONTEND_URL        = os.getenv("FRONTEND_URL", "http://localhost:5173")
DATABASE_URL        = os.getenv("DATABASE_URL", "sqlite:///users.db")

SCOPES = "openid profile email"

# Google scopes requested via Auth0's social connection settings,
# NOT passed here — they're configured in the Auth0 dashboard under
# the google-oauth2 connection. This keeps secrets/scopes centralized.

# ─── Database ─────────────────────────────────────────────────────────────────
# Stores registered users so the background worker knows who to scan.
# Google tokens stay in Auth0 (token vault pattern).

Base = declarative_base()


class User(Base):
    __tablename__ = "users"

    auth0_id    = Column(String, primary_key=True)  # e.g. "google-oauth2|1234567890"
    email       = Column(String, nullable=False)
    name        = Column(String)
    picture     = Column(String)
    scanning    = Column(Boolean, default=True)      # user opted in to background scanning
    created_at  = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    last_scanned = Column(DateTime, nullable=True)


class Interview(Base):
    __tablename__ = "interviews"

    id            = Column(String, primary_key=True)       # gmail message id
    user_id       = Column(String, nullable=False)          # auth0_id
    company       = Column(String, nullable=False)
    role          = Column(String, nullable=False)
    interview_date = Column(String, nullable=True)          # extracted date as string
    interview_type = Column(String, nullable=True)          # e.g. "behavioral", "technical", "phone screen"
    email_subject = Column(String)
    email_from    = Column(String)
    email_date    = Column(String)
    email_snippet = Column(String)
    raw_summary   = Column(String)                          # Gemini's full analysis
    created_at    = Column(DateTime, default=lambda: datetime.now(timezone.utc))


class InterviewQuestion(Base):
    __tablename__ = "interview_questions"

    id            = Column(String, primary_key=True)       # generated uuid
    interview_id  = Column(String, nullable=False)          # references interviews.id
    question      = Column(String, nullable=False)
    category      = Column(String, nullable=True)           # e.g. "leadership", "teamwork", "conflict"
    tip           = Column(String, nullable=True)           # advice for answering
    created_at    = Column(DateTime, default=lambda: datetime.now(timezone.utc))


engine = create_engine(DATABASE_URL)
Base.metadata.create_all(engine)
SessionLocal = sessionmaker(bind=engine)


# ─── Auth0 Management API Client ─────────────────────────────────────────────
# Used to fetch Google tokens from Auth0's token vault.

class Auth0ManagementClient:
    """
    Handles Auth0 Management API authentication and token caching.
    The management token is a separate credential that lets our server
    talk to Auth0's admin APIs — specifically to read users' stored
    Google tokens.
    """

    def __init__(self):
        self._token = None
        self._expires_at = 0

    def _fetch_token(self):
        """Get a Management API token via client credentials grant."""
        response = requests.post(
            f"https://{AUTH0_DOMAIN}/oauth/token",
            json={
                "grant_type":    "client_credentials",
                "client_id":     AUTH0_M2M_CLIENT_ID,
                "client_secret": AUTH0_M2M_CLIENT_SECRET,
                "audience":      f"https://{AUTH0_DOMAIN}/api/v2/",
            },
        )
        response.raise_for_status()
        data = response.json()
        self._token = data["access_token"]
        # Cache with a small buffer so we refresh before actual expiry
        self._expires_at = time.time() + data.get("expires_in", 86400) - 300
        logger.info("Auth0 Management API token refreshed.")

    @property
    def token(self):
        """Return a valid management token, refreshing if expired."""
        if not self._token or time.time() >= self._expires_at:
            self._fetch_token()
        return self._token

    def get_user(self, auth0_id: str) -> dict:
        """Fetch a user's full profile from Auth0, including identity tokens."""
        response = requests.get(
            f"https://{AUTH0_DOMAIN}/api/v2/users/{auth0_id}",
            headers={"Authorization": f"Bearer {self.token}"},
        )
        response.raise_for_status()
        return response.json()

    def get_google_tokens(self, auth0_id: str) -> dict | None:
        """
        Extract the Google access_token and refresh_token from a user's
        Auth0 identity. Returns None if no Google identity is found.
        """
        user = self.get_user(auth0_id)
        for identity in user.get("identities", []):
            if identity.get("provider") == "google-oauth2":
                return {
                    "access_token":  identity.get("access_token"),
                    "refresh_token": identity.get("refresh_token"),
                }
        return None


mgmt_client = Auth0ManagementClient()


# ─── Google Token Refresh ─────────────────────────────────────────────────────
# Google access tokens expire after 1 hour. The background worker uses
# refresh tokens to get new access tokens without user interaction.

def refresh_google_access_token(refresh_token: str) -> str | None:
    """
    Use a Google refresh token to get a fresh access token.
    The Google OAuth client ID and secret here come from the SAME Google
    credentials you configured in Auth0's Google social connection.
    You need to set these env vars:
        GOOGLE_CLIENT_ID=...
        GOOGLE_CLIENT_SECRET=...
    """
    google_client_id     = os.getenv("GOOGLE_CLIENT_ID")
    google_client_secret = os.getenv("GOOGLE_CLIENT_SECRET")

    if not google_client_id or not google_client_secret:
        logger.error("GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET must be set for token refresh.")
        return None

    response = requests.post(
        "https://oauth2.googleapis.com/token",
        data={
            "grant_type":    "refresh_token",
            "refresh_token": refresh_token,
            "client_id":     google_client_id,
            "client_secret": google_client_secret,
        },
    )

    if not response.ok:
        logger.error(f"Google token refresh failed: {response.text}")
        return None

    return response.json().get("access_token")


# Redirect user to Auth0 → Google login.

@app.route("/login")
def login():
    state = secrets.token_urlsafe(32)
    session["oauth_state"] = state

    params = {
        "response_type": "code",
        "client_id":     AUTH0_CLIENT_ID,
        "redirect_uri":  REDIRECT_URI,
        "scope":         SCOPES,
        "connection":    "google-oauth2",
        "state":         state,
        # Request offline access so Auth0 stores a Google refresh token
        "access_type":   "offline",
        "prompt":        "consent",
    }

    auth_url = f"https://{AUTH0_DOMAIN}/authorize?{urlencode(params)}"
    return redirect(auth_url)


# Auth0 redirects here after Google login. Exchange code for tokens,
# fetch user info, register user in our DB, store session.

@app.route("/callback")
def callback():
    # Handle Auth0 errors
    error = request.args.get("error")
    if error:
        logger.error(f"Auth0 error: {error} — {request.args.get('error_description')}")
        return redirect(f"{FRONTEND_URL}/login?error={error}")

    code  = request.args.get("code")
    state = request.args.get("state")

    # CSRF check
    if state != session.pop("oauth_state", None):
        return jsonify({"error": "State mismatch — possible CSRF."}), 403

    if not code:
        return jsonify({"error": "No authorization code returned."}), 400

    # ── Exchange code for tokens ──────────────────────────────────────────
    token_response = requests.post(
        f"https://{AUTH0_DOMAIN}/oauth/token",
        json={
            "grant_type":    "authorization_code",
            "client_id":     AUTH0_CLIENT_ID,
            "client_secret": AUTH0_CLIENT_SECRET,
            "code":          code,
            "redirect_uri":  REDIRECT_URI,
        },
    )

    if not token_response.ok:
        logger.error(f"Token exchange failed: {token_response.text}")
        return redirect(f"{FRONTEND_URL}/login?error=token_exchange_failed")

    tokens = token_response.json()
    auth0_access_token = tokens["access_token"]

    # ── Fetch user profile from Auth0 ─────────────────────────────────────
    userinfo_response = requests.get(
        f"https://{AUTH0_DOMAIN}/userinfo",
        headers={"Authorization": f"Bearer {auth0_access_token}"},
    )

    if not userinfo_response.ok:
        logger.error(f"Userinfo fetch failed: {userinfo_response.text}")
        return redirect(f"{FRONTEND_URL}/login?error=userinfo_failed")

    user_data = userinfo_response.json()

    # ── Register or update user in our database ───────────────────────────
    db = SessionLocal()
    try:
        user = db.query(User).filter_by(auth0_id=user_data["sub"]).first()
        if not user:
            user = User(
                auth0_id = user_data["sub"],
                email    = user_data.get("email", ""),
                name     = user_data.get("name", ""),
                picture  = user_data.get("picture", ""),
            )
            db.add(user)
            logger.info(f"New user registered: {user.email}")
        else:
            # Update profile in case it changed
            user.email   = user_data.get("email", user.email)
            user.name    = user_data.get("name", user.name)
            user.picture = user_data.get("picture", user.picture)
        db.commit()
    finally:
        db.close()

    # ── Store in session ──────────────────────────────────────────────────
    session["user"] = {
        "sub":     user_data.get("sub"),
        "name":    user_data.get("name"),
        "email":   user_data.get("email"),
        "picture": user_data.get("picture"),
    }

    return redirect(f"http://localhost:5173/home")


# ─── Route: /me ───────────────────────────────────────────────────────────────
# Returns the logged-in user's profile.

@app.route("/me")
def me():
    user = session.get("user")
    if not user:
        return jsonify({"error": "Not authenticated."}), 401
    return jsonify(user)


# ─── Route: /scanning ────────────────────────────────────────────────────────
# Toggle background scanning on/off for the logged-in user.

@app.route("/scanning", methods=["POST"])
def toggle_scanning():
    user_session = session.get("user")
    if not user_session:
        return jsonify({"error": "Not authenticated."}), 401

    enabled = request.json.get("enabled", True)

    db = SessionLocal()
    try:
        user = db.query(User).filter_by(auth0_id=user_session["sub"]).first()
        if user:
            user.scanning = enabled
            db.commit()
            return jsonify({"scanning": user.scanning})
        return jsonify({"error": "User not found."}), 404
    finally:
        db.close()


# ─── Route: /logout ──────────────────────────────────────────────────────────

@app.route("/logout")
def logout():
    session.clear()
    params = urlencode({
        "client_id": AUTH0_CLIENT_ID,
        "returnTo":  FRONTEND_URL,
    })
    return redirect(f"https://{AUTH0_DOMAIN}/v2/logout?{params}")


# ─── Route: /interviews ──────────────────────────────────────────────────────
# Returns all detected interviews for the logged-in user.

@app.route("/interviews")
def get_interviews():
    user_session = session.get("user")
    if not user_session:
        return jsonify({"error": "Not authenticated."}), 401

    db = SessionLocal()
    try:
        interviews = (
            db.query(Interview)
            .filter_by(user_id=user_session["sub"])
            .order_by(Interview.created_at.desc())
            .all()
        )
        return jsonify([
            {
                "id":             i.id,
                "company":        i.company,
                "role":           i.role,
                "interview_date": i.interview_date,
                "interview_type": i.interview_type,
                "email_subject":  i.email_subject,
                "email_from":     i.email_from,
                "email_date":     i.email_date,
                "summary":        i.raw_summary,
                "created_at":     i.created_at.isoformat() if i.created_at else None,
            }
            for i in interviews
        ])
    finally:
        db.close()


# ─── Route: /interviews/<id>/questions ────────────────────────────────────────
# Returns behavioral questions for a specific interview.

@app.route("/interviews/<interview_id>/questions")
def get_interview_questions(interview_id):
    user_session = session.get("user")
    if not user_session:
        return jsonify({"error": "Not authenticated."}), 401

    db = SessionLocal()
    try:
        # Verify the interview belongs to this user
        interview = db.query(Interview).filter_by(
            id=interview_id, user_id=user_session["sub"]
        ).first()
        if not interview:
            return jsonify({"error": "Interview not found."}), 404

        questions = (
            db.query(InterviewQuestion)
            .filter_by(interview_id=interview_id)
            .all()
        )
        return jsonify({
            "interview": {
                "company": interview.company,
                "role":    interview.role,
            },
            "questions": [
                {
                    "id":       q.id,
                    "question": q.question,
                    "category": q.category,
                    "tip":      q.tip,
                }
                for q in questions
            ],
        })
    finally:
        db.close()


# ─── Route: POST /interviews/<id>/generate-questions ─────────────────────────
# Uses Gemini to generate behavioral questions for this interview and saves them.
# Idempotent: can be called again to replace/add; existing questions are cleared first.

def _gemini_generate_questions(company: str, role: str, interview_type: str) -> list[dict]:
    """Generate 8–10 behavioral questions via Gemini (same format as Scanner)."""
    if not _GEMINI_AVAILABLE or _genai is None:
        return []
    client = _genai.Client(api_key=os.environ.get("GEMINI_API_KEY"))
    prompt = f"""Generate 8-10 behavioral interview questions that a candidate would likely be asked
for a {role} position at {company}. The interview type is: {interview_type or "behavioral"}.

Focus on:
- Questions specific to {company}'s known culture and values
- Questions relevant to the {role} role
- Common behavioral patterns (STAR method questions)

Respond ONLY with a JSON array, no markdown, no backticks, no extra text.
Each item should have:
{{
    "question": "the interview question",
    "category": "one of: leadership, teamwork, conflict resolution, problem solving, communication, adaptability, initiative, time management",
    "tip": "brief advice on how to approach this question well"
}}"""
    try:
        response = client.models.generate_content(
            model=os.getenv("GEMINI_QUESTION_MODEL", "gemini-2.0-flash"),
            contents=prompt,
        )
        text = (response.text or "").strip()
        if text.startswith("```"):
            text = text.split("\n", 1)[1] if "\n" in text else text[3:]
        if text.endswith("```"):
            text = text[:-3]
        text = text.strip()
        out = json.loads(text)
        return out if isinstance(out, list) else []
    except (json.JSONDecodeError, Exception) as e:
        logger.error(f"Gemini question generation failed for {company} / {role}: {e}")
        return []


@app.route("/interviews/<interview_id>/generate-questions", methods=["POST"])
def generate_interview_questions(interview_id):
    user_session = session.get("user")
    if not user_session:
        return jsonify({"error": "Not authenticated."}), 401
    if not _GEMINI_AVAILABLE:
        return jsonify({"error": "Gemini is not configured (GEMINI_API_KEY)."}), 503

    db = SessionLocal()
    try:
        interview = db.query(Interview).filter_by(
            id=interview_id, user_id=user_session["sub"]
        ).first()
        if not interview:
            return jsonify({"error": "Interview not found."}), 404

        # Remove existing questions so we replace with fresh Gemini set
        db.query(InterviewQuestion).filter_by(interview_id=interview_id).delete()

        questions_data = _gemini_generate_questions(
            interview.company,
            interview.role,
            interview.interview_type or "behavioral",
        )
        if not questions_data:
            return jsonify({"error": "Failed to generate questions.", "questions": []}), 502

        for q in questions_data:
            db.add(InterviewQuestion(
                id=str(uuid.uuid4()),
                interview_id=interview_id,
                question=q.get("question", ""),
                category=q.get("category"),
                tip=q.get("tip"),
            ))
        db.commit()

        questions = (
            db.query(InterviewQuestion)
            .filter_by(interview_id=interview_id)
            .all()
        )
        return jsonify({
            "interview": {"company": interview.company, "role": interview.role},
            "questions": [
                {"id": q.id, "question": q.question, "category": q.category, "tip": q.tip}
                for q in questions
            ],
        })
    finally:
        db.close()


def require_auth(f):
    """Decorator: returns 401 if user is not logged in."""
    @wraps(f)
    def decorated(*args, **kwargs):
        if "user" not in session:
            return jsonify({"error": "Not authenticated."}), 401
        return f(*args, **kwargs)
    return decorated

def get_google_token_for_user(auth0_id: str) -> str | None:
    """
    Get a valid Google access token for a user.
    Tries the stored access token first, falls back to refresh.

    This is what your background email scanner will call.
    """
    tokens = mgmt_client.get_google_tokens(auth0_id)
    if not tokens:
        logger.warning(f"No Google tokens found for user {auth0_id}")
        return None

    # Try the stored access token first (might still be valid)
    access_token = tokens.get("access_token")
    if access_token and _is_token_valid(access_token):
        return access_token

    # Access token expired — refresh it
    refresh_token = tokens.get("refresh_token")
    if not refresh_token:
        logger.warning(f"No refresh token for user {auth0_id} — user needs to re-login.")
        return None

    new_token = refresh_google_access_token(refresh_token)
    if new_token:
        logger.info(f"Refreshed Google token for user {auth0_id}")
    return new_token


def _is_token_valid(access_token: str) -> bool:
    """Quick check if a Google access token is still valid."""
    response = requests.get(
        "https://www.googleapis.com/oauth2/v1/tokeninfo",
        params={"access_token": access_token},
    )
    return response.ok

if __name__ == "__main__":
    app.run(debug=True, host="localhost", port=8000)