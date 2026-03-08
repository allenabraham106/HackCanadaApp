import asyncio
import json
import logging
import os
import tempfile
import time
from datetime import datetime
from typing import Optional

import requests as requests_sync
from dotenv import load_dotenv
from fastapi import FastAPI, File, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response
from google import genai
from google.genai import types

from interview_context import router as interview_context_router

logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("hackcanada")

# Load .env from this package dir first (same folder as main.py), then repo root
_backend_dir = os.path.dirname(os.path.abspath(__file__))
_load_env_local = os.path.join(_backend_dir, ".env")
_load_env_root = os.path.join(_backend_dir, "..", ".env")
if os.path.isfile(_load_env_local):
    load_dotenv(_load_env_local)
if os.path.isfile(_load_env_root):
    load_dotenv(_load_env_root)

# Fallback: read .env line by line and set GEMINI + OPENAI if missing (handles encoding/quirks/BOM)
def _load_env_keys():
    want = {"GEMINI_API_KEY", "OPENAI_API_KEY", "ELEVENLABS_API_KEY", "ELEVENLABS_VOICE_ID"}
    have = {k for k in want if (os.environ.get(k) or "").strip()}
    if have == want:
        return
    for _path in (_load_env_local, _load_env_root):
        if not os.path.isfile(_path):
            continue
        try:
            with open(_path, "r", encoding="utf-8", errors="replace") as f:
                for line in f:
                    line = line.strip().lstrip("\ufeff")
                    if not line or line.startswith("#") or "=" not in line:
                        continue
                    key, _, val = line.partition("=")
                    key = key.strip()
                    val = val.strip().strip("'\"").strip()
                    if not val:
                        continue
                    if key in want and key not in have:
                        os.environ[key] = val
                        have.add(key)
                    if have == want:
                        return
        except Exception:
            pass


_load_env_keys()

app = FastAPI()

app.include_router(interview_context_router)


@app.get("/check-keys")
async def check_keys():
    """Verify API keys are loaded (for debugging). Does not expose key values."""
    openai_raw = (os.environ.get("OPENAI_API_KEY") or "").strip()
    openai_line_found = False
    env_path_used = None
    if not openai_raw:
        for _path in (_load_env_local, _load_env_root, os.path.join(os.getcwd(), "hackcanada-backend", ".env")):
            if not os.path.isfile(_path):
                continue
            try:
                with open(_path, "r", encoding="utf-8", errors="replace") as f:
                    raw = f.read()
                for line in raw.splitlines():
                    line = line.strip().lstrip("\ufeff")
                    if "OPENAI_API_KEY" in line and "=" in line:
                        openai_line_found = True
                        key, _, val = line.partition("=")
                        if key.strip() == "OPENAI_API_KEY":
                            val = val.strip().strip("'\"").strip()
                            if val:
                                os.environ["OPENAI_API_KEY"] = val
                                openai_raw = val
                                env_path_used = _path
                                break
                if openai_raw:
                    break
            except Exception:
                continue
    gemini_raw = (os.environ.get("GEMINI_API_KEY") or "").strip()
    return {
        "gemini_configured": bool(gemini_raw),
        "presage_configured": bool(_env("PRESAGE_API_KEY")),
        "openai_configured": bool(openai_raw),
        "gemini_key_length": len(gemini_raw),
        "openai_key_length": len(openai_raw),
        "env_file_loaded": os.path.isfile(_load_env_local),
        "openai_line_found_in_file": openai_line_found,
        "env_path_used": env_path_used,
        "env_path_checked": _load_env_local,
        "cwd": os.getcwd(),
    }


@app.get("/health")
async def health():
    """Simple liveness check: backend is running."""
    return {"status": "ok", "service": "hackcanada-backend"}


@app.get("/health/ready")
async def health_ready():
    """Readiness: backend is up and can run video analysis (Gemini configured)."""
    gemini_ok = bool(_env("GEMINI_API_KEY"))
    return {
        "ready": gemini_ok,
        "gemini_configured": gemini_ok,
        "message": "Ready for analysis." if gemini_ok else "GEMINI_API_KEY not set.",
    }


#allows us to connect to apps
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Configure Gemini (lazy so server starts without GEMINI_API_KEY)
_gemini_client = None

def _env(key: str) -> str:
    return (os.environ.get(key) or "").strip()

def _get_gemini_client():
    global _gemini_client
    key = _env("GEMINI_API_KEY")
    if _gemini_client is None and key:
        _gemini_client = genai.Client(api_key=key)
    return _gemini_client

# Default model for deeper analysis endpoints (report, answer analysis, etc.)
MODEL = "gemini-3.1-pro-preview"

# Fast model for question generation (low latency).
QUESTION_MODEL = "gemini-2.0-flash"

#how are we gonna score them
SCORING_RULES = {
    "filler_word": -2,
    "eye_contact_lost": -3,
    "high_stress": -2,
    "low_focus": -2,
    "good_posture": +2,
    "strong_answer": +5,
    "mediocre_answer": +2,
    "weak_answer": -3,
}

# In-memory session log
session_log = []


def _get_tip(triggered: list) -> Optional[str]:
    if "eye_contact_lost" in triggered:
        return "Look at the camera 👀"
    if "filler_word" in triggered:
        return "Take a breath before answering 🧘"
    if "high_stress" in triggered:
        return "Slow down, you've got this 💪"
    if "low_focus" in triggered:
        return "Stay present, almost there 🎯"
    if "weak_answer" in triggered:
        return "Use a concrete example next time 💡"
    return None



#generating a mock interview
@app.post("/mock-interview")
async def mock_interview(body: dict):
    role = body.get("role", "software engineer")
    company = body.get("company") or ""
    num_questions = body.get("num_questions", 3)

    company_phrase = f" at {company}" if company else ""
    prompt = f"Generate {num_questions} short interview questions for a {role} position{company_phrase}. One line each. Return ONLY a JSON array of strings, no markdown. Example: [\"Tell me about yourself.\", \"Describe a challenge you overcame.\"]"
    config = types.GenerateContentConfig(
        max_output_tokens=256,
        temperature=0.3,
    )
    client = _get_gemini_client()
    if not client:
        return JSONResponse({"error": "GEMINI_API_KEY not set"}, status_code=503)
    try:
        response = await asyncio.to_thread(
            client.models.generate_content,
            model=QUESTION_MODEL,
            contents=prompt,
            config=config,
        )
        text = response.text.strip().replace("```json", "").replace("```", "")
        questions = json.loads(text)
        return JSONResponse({"questions": questions})
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


# ─── Presage Physiology (near-real-time vitals from video) ───────────────────
PRESAGE_API_BASE = "https://api.physiology.presagetech.com"
CHUNK_SIZE = 5 * 1024 * 1024  # 5MB


def _presage_upload_video_sync(video_path: str, api_key: str) -> Optional[dict]:
    """Upload video to Presage, poll for result. Returns raw API response (hr, rr) or None."""
    headers = {"x-api-key": api_key}
    file_size = os.path.getsize(video_path)
    # 1) Get upload URLs
    r = requests_sync.post(
        f"{PRESAGE_API_BASE}/v1/upload-url",
        headers=headers,
        json={"file_size": file_size, "hr_br": {"to_process": True}},
        timeout=30,
    )
    if r.status_code != 200:
        return None
    data = r.json()
    vid_id = data["id"]
    urls = data["urls"]
    upload_id = data["upload_id"]
    # 2) PUT file in chunks
    parts = []
    with open(video_path, "rb") as f:
        for num, url in enumerate(urls):
            chunk = f.read(CHUNK_SIZE)
            if not chunk:
                break
            put_r = requests_sync.put(url, data=chunk, timeout=60)
            if put_r.status_code != 200:
                return None
            parts.append({"ETag": put_r.headers.get("ETag", ""), "PartNumber": num + 1})
    # 3) Complete upload
    r2 = requests_sync.post(
        f"{PRESAGE_API_BASE}/v1/complete",
        headers=headers,
        json={"id": vid_id, "upload_id": upload_id, "parts": parts},
        timeout=30,
    )
    if r2.status_code != 200:
        return None
    # 4) Poll retrieve-data (recommended: wait ~half video length before polling)
    stop_at = time.time() + 300  # 5 min max
    while time.time() < stop_at:
        r3 = requests_sync.post(
            f"{PRESAGE_API_BASE}/retrieve-data",
            headers=headers,
            json={"id": vid_id, "reshape": False},
            timeout=30,
        )
        if r3.status_code == 200:
            return r3.json()
        if r3.status_code == 401:
            return None
        time.sleep(2)
    return None


def _stress_from_hr_rr(hr_values: list, rr_values: list) -> str:
    """Simple stress level from heart rate."""
    if not hr_values:
        return "unknown"
    import statistics
    hr_avg = statistics.median(hr_values)
    if hr_avg >= 95:
        return "high"
    if hr_avg >= 78:
        return "elevated"
    return "calm"


@app.post("/presage/analyze")
async def presage_analyze(video: UploadFile = File(...)):
    """Upload a short video chunk; returns heart rate, breathing rate, and stress level (near-real-time)."""
    api_key = _env("PRESAGE_API_KEY")
    if not api_key:
        return JSONResponse({"error": "PRESAGE_API_KEY not set"}, status_code=503)
    if not video.content_type or not video.content_type.startswith("video/") and video.content_type != "application/octet-stream":
        pass  # allow anyway, Presage accepts video files
    try:
        suffix = ".webm"
        if video.filename and "." in video.filename:
            suffix = "." + video.filename.rsplit(".", 1)[-1]
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
            content = await video.read()
            tmp.write(content)
            tmp_path = tmp.name
        try:
            result = await asyncio.to_thread(_presage_upload_video_sync, tmp_path, api_key)
            if not result:
                return JSONResponse({"error": "Presage processing failed or timed out"}, status_code=502)
            hr = result.get("hr") or {}
            rr = result.get("rr") or {}
            if isinstance(hr, dict):
                hr_values = [v for v in hr.values() if isinstance(v, (int, float))]
            elif isinstance(hr, list):
                hr_values = [v for v in hr if isinstance(v, (int, float))]
            else:
                hr_values = []
            if isinstance(rr, dict):
                rr_values = [v for v in rr.values() if isinstance(v, (int, float))]
            elif isinstance(rr, list):
                rr_values = [v for v in rr if isinstance(v, (int, float))]
            else:
                rr_values = []
            heart_rate = round(sum(hr_values) / len(hr_values), 1) if hr_values else None
            breathing_rate = round(sum(rr_values) / len(rr_values), 1) if rr_values else None
            stress_level = _stress_from_hr_rr(hr_values, rr_values)
            return JSONResponse({
                "heartRate": heart_rate,
                "breathingRate": breathing_rate,
                "stressLevel": stress_level,
            })
        finally:
            try:
                os.unlink(tmp_path)
            except Exception:
                pass
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


# ─── Gemini video analysis (stress / body language from video) ─────────────────
# Try 2.5 Flash first; fallback to 3.1 Pro if 404 (model availability varies by account)
VIDEO_ANALYSIS_MODELS = ("gemini-2.5-flash", "gemini-2.5-pro", "gemini-3.1-pro-preview")
# Space out Gemini video calls to avoid rate limits (often only 1/3 requests succeed otherwise)
_gemini_video_last_call = 0.0
_gemini_video_min_interval = 4.0
_gemini_video_lock = asyncio.Lock()

VIDEO_ANALYSIS_PROMPT = """You are analyzing a short video of a person answering an interview question.
Watch AND listen to the video. The speaker may talk quickly—do your best to transcribe and still give full analysis.
Respond with ONLY a valid JSON object, no markdown or explanation.
Use these exact keys:
- "transcript": word-for-word what the person said (best effort even if fast; use "[inaudible]" only for truly inaudible parts)
- "stressLevel": one of "calm", "elevated", "high" (use visual cues if audio is unclear)
- "confidence": number 1-5 (1=very nervous, 5=very confident)
- "eyeContact": one of "good", "moderate", "poor"
- "bodyLanguageNotes": one short sentence (e.g. "Relaxed posture, minimal fidgeting")
Always fill every key. Be concise and objective."""


def _extract_json_from_text(text: str):
    """Try to parse JSON from model output (handles markdown, extra text, trailing commas)."""
    if not text or not text.strip():
        return None
    text = text.strip()
    for prefix in ("```json", "```"):
        if text.startswith(prefix):
            text = text[len(prefix) :].strip()
        if text.endswith("```"):
            text = text[:-3].strip()
    start = text.find("{")
    if start == -1:
        return None
    depth = 0
    end = -1
    for i in range(start, len(text)):
        if text[i] == "{":
            depth += 1
        elif text[i] == "}":
            depth -= 1
            if depth == 0:
                end = i + 1
                break
    if end == -1:
        return None
    chunk = text[start:end]
    chunk = chunk.replace(",]", "]").replace(",}", "}")
    try:
        return json.loads(chunk)
    except json.JSONDecodeError:
        return None


def _sanitize_display_text(s: str) -> str:
    """Remove markdown code fences and JSON so we never show raw model output to the user."""
    if not s or not isinstance(s, str):
        return ""
    s = s.strip()
    for prefix in ("```json", "```"):
        if s.startswith(prefix):
            s = s[len(prefix) :].strip()
    if s.endswith("```"):
        s = s[:-3].strip()
    if s.startswith("{") or s.startswith("["):
        return ""
    return s.strip()


def _fallback_parse_video_response(text: str) -> dict:
    """When JSON fails, extract stress level and use first sentence as notes. Never return error-like text."""
    if not (text or "").strip():
        return {"stressLevel": "unknown", "bodyLanguageNotes": "Video reviewed.", "transcript": None, "confidence": None, "eyeContact": None}
    t = text.strip()
    for prefix in ("```json", "```"):
        if t.startswith(prefix):
            t = t[len(prefix) :].strip()
    if t.endswith("```"):
        t = t[:-3].strip()
    if t.startswith("{") or t.startswith("["):
        return {"stressLevel": "unknown", "bodyLanguageNotes": "Video reviewed.", "transcript": None, "confidence": None, "eyeContact": None}
    t_lower = t.lower()
    stress = "unknown"
    for level in ("high", "elevated", "calm"):
        if level in t_lower:
            stress = level
            break
    first_sentence = (t.split(".")[0] + ".").strip() if "." in t else t[:120]
    if len(first_sentence) > 200:
        first_sentence = first_sentence[:197] + "..."
    notes = _sanitize_display_text(first_sentence)
    if not notes:
        notes = "Video reviewed."
    return {
        "stressLevel": stress,
        "bodyLanguageNotes": notes,
        "transcript": None,
        "confidence": None,
        "eyeContact": None,
    }


def _call_gemini_video(client, content: bytes, mime: str, model: str):
    contents = types.Content(
        parts=[
            types.Part(inline_data=types.Blob(data=content, mime_type=mime)),
            types.Part(text=VIDEO_ANALYSIS_PROMPT),
        ]
    )
    config = types.GenerateContentConfig(max_output_tokens=256, temperature=0.2)
    return client.models.generate_content(
        model=model,
        contents=contents,
        config=config,
    )


@app.post("/gemini/analyze-video")
async def gemini_analyze_video(video: UploadFile = File(...)):
    """Analyze interview answer video with Gemini; returns stressLevel, confidence, eyeContact, bodyLanguageNotes."""
    global _gemini_video_last_call
    client = _get_gemini_client()
    if not client:
        return JSONResponse({"error": "GEMINI_API_KEY not set"}, status_code=503)
    try:
        content = await video.read()
        if not content or len(content) > 20 * 1024 * 1024:  # 20MB cap
            return JSONResponse({
                "heartRate": None,
                "breathingRate": None,
                "stressLevel": "unknown",
                "source": "gemini",
                "confidence": None,
                "eyeContact": None,
                "bodyLanguageNotes": "Video too short or too large to analyze. You're good to continue.",
            })
        mime = "video/webm"
        if video.content_type and video.content_type.startswith("video/"):
            mime = video.content_type
        # Throttle so we don't hit Gemini rate limits (spread Q1, Q2, Q3 requests)
        async with _gemini_video_lock:
            now = time.monotonic()
            elapsed = now - _gemini_video_last_call
            if elapsed < _gemini_video_min_interval:
                await asyncio.sleep(_gemini_video_min_interval - elapsed)
            _gemini_video_last_call = time.monotonic()
        last_text = None
        for model in VIDEO_ANALYSIS_MODELS:
            for attempt in (1, 2):
                try:
                    response = await asyncio.to_thread(
                        _call_gemini_video,
                        client,
                        content,
                        mime,
                        model,
                    )
                    text = (response.text or "").strip()
                    last_text = text
                    data = None
                    try:
                        data = json.loads(text.replace("```json", "").replace("```", "").strip())
                    except json.JSONDecodeError:
                        data = _extract_json_from_text(text)
                    if not data or not isinstance(data, dict):
                        data = _fallback_parse_video_response(text)
                    stress = (data.get("stressLevel") or "unknown").lower()
                    if stress not in ("calm", "elevated", "high"):
                        stress = "unknown"
                    notes = _sanitize_display_text(data.get("bodyLanguageNotes") or "")
                    if not notes:
                        notes = "Video reviewed."
                    transcript_val = _sanitize_display_text(data.get("transcript") or "")
                    return JSONResponse({
                        "heartRate": None,
                        "breathingRate": None,
                        "stressLevel": stress,
                        "source": "gemini",
                        "confidence": data.get("confidence"),
                        "eyeContact": data.get("eyeContact"),
                        "bodyLanguageNotes": notes,
                        "transcript": transcript_val or None,
                    })
                except Exception as e:
                    err_str = str(e)
                    if "404" in err_str or "NOT_FOUND" in err_str:
                        break
                    if last_text:
                        data = _fallback_parse_video_response(last_text)
                        return JSONResponse({
                            "heartRate": None,
                            "breathingRate": None,
                            "stressLevel": data.get("stressLevel", "unknown"),
                            "source": "gemini",
                            "confidence": data.get("confidence"),
                            "eyeContact": data.get("eyeContact"),
                            "bodyLanguageNotes": data.get("bodyLanguageNotes", "Video reviewed."),
                            "transcript": data.get("transcript"),
                        })
                    if attempt == 2:
                        raise
                    await asyncio.sleep(3)
        logger.warning(
            "gemini/analyze-video fallback (no usable response): size=%s bytes, has_text=%s",
            len(content),
            bool(last_text),
            exc_info=False,
        )
        data = _fallback_parse_video_response(last_text or "Video of candidate.")
        return JSONResponse({
            "heartRate": None,
            "breathingRate": None,
            "stressLevel": data.get("stressLevel", "unknown"),
            "source": "gemini",
            "confidence": None,
            "eyeContact": None,
            "bodyLanguageNotes": data.get("bodyLanguageNotes", "Video reviewed."),
            "transcript": data.get("transcript"),
        })
    except Exception as e:
        try:
            size = len(content)
        except NameError:
            size = 0
        logger.warning("gemini/analyze-video error: %s (size=%s)", e, size)
        data = _fallback_parse_video_response("")
        return JSONResponse({
            "heartRate": None,
            "breathingRate": None,
            "stressLevel": data.get("stressLevel", "unknown"),
            "source": "gemini",
            "confidence": None,
            "eyeContact": None,
            "bodyLanguageNotes": data.get("bodyLanguageNotes", "Video reviewed."),
            "transcript": None,
        })


# ─── Transcription (OpenAI Whisper preferred; Gemini fallback) ─────────────────
@app.post("/transcribe")
async def transcribe(video: UploadFile = File(...)):
    """Transcribe speech from video/audio. Uses OpenAI Whisper if OPENAI_API_KEY set, else Gemini."""
    content = await video.read()
    if not content or len(content) > 25 * 1024 * 1024:
        return JSONResponse({"transcript": None, "error": "File empty or too large"}, status_code=400)

    openai_key = _env("OPENAI_API_KEY")
    if openai_key:
        try:
            from openai import OpenAI
            client = OpenAI(api_key=openai_key)
            import io
            file_like = io.BytesIO(content)
            file_like.name = video.filename or "recording.webm"
            transcript_obj = await asyncio.to_thread(
                client.audio.transcriptions.create,
                model="whisper-1",
                file=file_like,
            )
            text = (transcript_obj.text or "").strip()
            return JSONResponse({"transcript": text or None, "source": "whisper"})
        except Exception as e:
            return JSONResponse(
                {"transcript": None, "error": str(e)[:120], "source": "whisper"},
                status_code=502,
            )

    client = _get_gemini_client()
    if not client:
        return JSONResponse({"transcript": None, "error": "No OPENAI_API_KEY or GEMINI_API_KEY"}, status_code=503)
    mime = video.content_type if video.content_type and video.content_type.startswith(("video/", "audio/")) else "video/webm"
    contents = types.Content(
        parts=[
            types.Part(inline_data=types.Blob(data=content, mime_type=mime)),
            types.Part(text="Transcribe the speech in this video. Return only the raw transcript, nothing else. The speaker may talk quickly—capture every word to the best of your ability. Use [inaudible] only for truly inaudible parts."),
        ]
    )
    try:
        response = await asyncio.to_thread(
            client.models.generate_content,
            model=VIDEO_ANALYSIS_MODELS[0],
            contents=contents,
            config=types.GenerateContentConfig(max_output_tokens=1024, temperature=0),
        )
        text = (response.text or "").strip()
        return JSONResponse({"transcript": text or None, "source": "gemini"})
    except Exception as e:
        for model in VIDEO_ANALYSIS_MODELS[1:]:
            try:
                response = await asyncio.to_thread(
                    client.models.generate_content,
                    model=model,
                    contents=contents,
                    config=types.GenerateContentConfig(max_output_tokens=1024, temperature=0),
                )
                text = (response.text or "").strip()
                return JSONResponse({"transcript": text or None, "source": "gemini"})
            except Exception:
                continue
        return JSONResponse({"transcript": None, "error": str(e)[:120]}, status_code=502)


@app.post("/tts")
async def text_to_speech(body: dict):
    text = (body.get("text") or "").strip()
    if not text:
        return JSONResponse({"error": "text is required"}, status_code=400)

    elevenlabs_key = _env("ELEVENLABS_API_KEY")
    if not elevenlabs_key:
        return JSONResponse({"error": "ELEVENLABS_API_KEY not set"}, status_code=503)

    voice_id = (body.get("voice_id") or _env("ELEVENLABS_VOICE_ID")).strip()
    if not voice_id:
        return JSONResponse({"error": "voice_id is required (body.voice_id or ELEVENLABS_VOICE_ID)"}, status_code=400)

    model_id = (body.get("model_id") or _env("ELEVENLABS_MODEL_ID") or "eleven_multilingual_v2").strip()
    output_format = (body.get("output_format") or _env("ELEVENLABS_OUTPUT_FORMAT") or "mp3_44100_128").strip()
    voice_settings = body.get("voice_settings") if isinstance(body.get("voice_settings"), dict) else None

    payload = {
        "text": text,
        "model_id": model_id,
    }
    if voice_settings:
        payload["voice_settings"] = voice_settings

    url = f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}/stream"
    params = {"output_format": output_format}

    try:
        resp = await asyncio.to_thread(
            requests_sync.post,
            url,
            params=params,
            json=payload,
            headers={
                "xi-api-key": elevenlabs_key,
                "accept": "audio/mpeg",
                "content-type": "application/json",
            },
            timeout=30,
        )
    except Exception as e:
        return JSONResponse({"error": f"Failed to contact ElevenLabs: {str(e)[:160]}"}, status_code=502)

    if not resp.ok:
        detail = (resp.text or "")[:300]
        return JSONResponse(
            {
                "error": "ElevenLabs TTS request failed",
                "status_code": resp.status_code,
                "detail": detail,
            },
            status_code=502,
        )

    media_type = resp.headers.get("content-type", "audio/mpeg")
    return Response(content=resp.content, media_type=media_type)


@app.post("/analyze-answer")
async def analyze_answer(body: dict):
    question = body.get("question", "")
    answer = body.get("answer", "")

    prompt = f"""
    Interview question: "{question}"
    Candidate's transcribed audio: "{answer}"

    IMPORTANT: The candidate's transcribed audio might have captured the AI interviewer asking the question at the very beginning. You MUST ignore the interviewer's voice/question in the transcript and ONLY grade the candidate's actual response.

    Rate the candidate's answer. Return ONLY a JSON object, no markdown:
    {{
        "rating": "strong" or "mediocre" or "weak",
        "score": 1-10,
        "feedback": "one sentence of constructive feedback",
        "highlight": "one thing they did well"
    }}
    """
    client = _get_gemini_client()
    if not client:
        return JSONResponse({"error": "GEMINI_API_KEY not set"}, status_code=503)
    try:
        response = await asyncio.to_thread(client.models.generate_content, model=MODEL, contents=prompt)
        text = response.text.strip().replace("```json", "").replace("```", "")
        result = json.loads(text)
        rating = result.get("rating", "mediocre")
        result["delta"] = SCORING_RULES.get(f"{rating}_answer", 0)

        # Log weak answers as lowlights
        if rating == "weak":
            session_log.append(
                {
                    "timestamp": datetime.now().isoformat(),
                    "triggered": ["weak_answer"],
                    "delta": result["delta"],
                    "question": question,
                    "answer": answer,
                    "feedback": result.get("feedback", ""),
                    "tip": result.get("feedback", ""),
                }
            )

        return JSONResponse(result)
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


@app.post("/lowlight-reel")
async def lowlight_reel(body: dict):
    transcript = body.get("transcript", "")
    role = body.get("role", "software engineer")

    prompt = f"""
    You are an expert interview coach analyzing a {role} interview.

    Full transcript: "{transcript}"
    Flagged lowlight moments: {json.dumps(session_log)}

    For each lowlight moment, generate an optimal response.
    Return ONLY a JSON array, no markdown:
    [
        {{
            "timestamp": "the timestamp from the log",
            "what_happened": "one sentence describing what went wrong",
            "what_you_said": "the weak part from the transcript if available",
            "optimal_response": "the ideal response they should have given",
            "why_it_works": "one sentence explaining why the optimal response is better",
            "tip": "one actionable tip to improve"
        }}
    ]

    If there are no lowlight moments, return an empty array: []
    """
    client = _get_gemini_client()
    if not client:
        return JSONResponse({"error": "GEMINI_API_KEY not set"}, status_code=503)
    try:
        response = client.models.generate_content(model=MODEL, contents=prompt)
        text = response.text.strip().replace("```json", "").replace("```", "")
        reel = json.loads(text)
        return JSONResponse({"lowlights": reel, "total": len(reel)})
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)

@app.post("/report")
async def generate_report(body: dict):
    prompt = f"""
    Analyze this mock interview for a {body.get("role", "professional")} role.

    Final score: {body.get("final_score")}/100
    Transcript: {body.get("transcript", "N/A")}
    Behavioral signals: {json.dumps(body.get("signals_summary", {}))}

    Return ONLY a JSON object, no markdown:
    {{
        "overall_rating": "Excellent" or "Good" or "Needs Work" or "Poor",
        "summary": "2-3 sentence overall summary",
        "strengths": ["strength 1", "strength 2"],
        "improvements": ["improvement 1", "improvement 2"],
        "body_language_score": 0-100,
        "communication_score": 0-100,
        "content_score": 0-100,
        "confidence_score": 0-100,
        "top_tip": "single most important thing to work on"
    }}
    """
    client = _get_gemini_client()
    if not client:
        return JSONResponse({"error": "GEMINI_API_KEY not set"}, status_code=503)
    try:
        response = client.models.generate_content(model=MODEL, contents=prompt)
        text = response.text.strip().replace("```json", "").replace("```", "")
        report = json.loads(text)
        return JSONResponse(report)
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)
    
@app.post("/reset-session")
async def reset_session():
    session_log.clear()
    return JSONResponse({"status": "session cleared"})


#connection to our react app
@app.websocket("/ws/live")
async def websocket_live(websocket: WebSocket):
    await websocket.accept()
    try:
        while True:
            data = await websocket.receive_json()
            delta = 0
            triggered = []

            for signal, active in data.items():
                if active and signal in SCORING_RULES:
                    delta += SCORING_RULES[signal]
                    triggered.append(signal)

            await websocket.send_json(
                {
                    "delta": delta,
                    "triggered": triggered,
                    "tip": _get_tip(triggered),
                }
            )
    except WebSocketDisconnect:
        print("Client disconnected")
