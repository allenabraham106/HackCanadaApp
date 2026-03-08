from google import genai
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
import os
import json
from typing import Optional
from datetime import datetime
from dotenv import load_dotenv
from interview_context import router as interview_context_router

load_dotenv()

app = FastAPI()

app.include_router(interview_context_router)

#allows us to connect to apps
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Configure Gemini
client = genai.Client(api_key=os.environ.get("GEMINI_API_KEY"))
app.state.gemini_model = client

# Default model for deeper analysis endpoints (report, answer analysis, etc.)
MODEL = "gemini-3.1-pro-preview"

# Faster, lighter model for quick question generation.
QUESTION_MODEL = "gemini-3.1-flash-lite-preview"

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
    num_questions = body.get("num_questions", 5)

    prompt = f"""
    Generate {num_questions} realistic interview questions for a {role} position.
    Mix behavioral, technical, and situational questions.
    Return ONLY a JSON array of strings, no extra text, no markdown.
    Example: ["Tell me about yourself.", "Describe a challenge you overcame."]
    """
    try:
        response = client.models.generate_content(
            model=QUESTION_MODEL,
            contents=prompt
        )
        text = response.text.strip().replace("```json", "").replace("```", "")
        questions = json.loads(text)
        return JSONResponse({"questions": questions})
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)

@app.post("/analyze-answer")
async def analyze_answer(body: dict):
    question = body.get("question", "")
    answer = body.get("answer", "")

    prompt = f"""
    Interview question: "{question}"
    Candidate's answer: "{answer}"

    Rate this answer. Return ONLY a JSON object, no markdown:
    {{
        "rating": "strong" or "mediocre" or "weak",
        "score": 1-10,
        "feedback": "one sentence of constructive feedback",
        "highlight": "one thing they did well"
    }}
    """
    try:
        response = client.models.generate_content(model=MODEL, contents=prompt)
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
