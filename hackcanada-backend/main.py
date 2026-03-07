import google.generativeai as genai
from fastapi import FastAPI, UploadFile, File, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
import tempfile
import os
import json
import asyncio
from typing import Optional

app = FastAPI()

#allow Swift to Connect
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

#setting up Gemini
genai.configure(api_key=os.environ.get("GEMINI_API_KEY"))
model = genai.GenerativeModel("gemini-1.5-pro")

SCORING_RULES = {
    "filler_word": -2,  # um, uh, like, you know
    "eye_contact_lost": -3,  # Presage detects gaze away
    "high_stress": -2,  # Presage stress spike
    "low_focus": -2,  # Presage focus drop
    "good_posture": +2,  # Presage posture signal
    "strong_answer": +5,  # Gemini rates answer highly
    "mediocre_answer": +2,  # Gemini rates answer okay
    "weak_answer": -3,  # Gemini rates answer poorly
}

