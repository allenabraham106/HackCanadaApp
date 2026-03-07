from google import genai
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
import os
import json
from typing import Optional
from datetime import datetime

app = FastAPI()

#allows us to connect to apps
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Configure Gemini
client = genai.Client(api_key="AIzaSyB1qnZ_QufzHk8QUuOP-R-oVbZo3fw3kuo")


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
            model="gemini-2.0-flash-lite", contents=prompt
        )
        text = response.text.strip().replace("```json", "").replace("```", "")
        questions = json.loads(text)
        return JSONResponse({"questions": questions})
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)

