# scanner.py
# ─────────────────────────────────────────────────────────────────────────────
# Background email scanner with Gemini integration.
#
# Flow per user:
#   1. Fetch Google tokens from Auth0 (token vault)
#   2. Search Gmail for potential interview emails
#   3. Read the full email body
#   4. Send to Gemini to verify it's an interview invite + extract details
#   5. If confirmed, generate behavioral interview questions
#   6. Store everything in Supabase
#
# RUN:
#   python scanner.py              (one-shot, good for cron)
#   python scanner.py --loop       (continuous, runs every SCAN_INTERVAL seconds)
#
# INSTALL:
#   pip install google-generativeai
#
# .env:
#   GEMINI_API_KEY=your_gemini_api_key
# ─────────────────────────────────────────────────────────────────────────────

import os
import sys
import json
import time
import uuid
import base64
import logging
import argparse
from datetime import datetime, timezone

import requests
from dotenv import load_dotenv
from google import genai

from twilio.rest import Client

def send_whatsapp_notification(company, role, date=None):
    """Sends a WhatsApp message via Twilio when a new interview is found."""
    account_sid = os.getenv("TWILIO_ACCOUNT_SID")
    auth_token = os.getenv("TWILIO_AUTH_TOKEN")
    from_whatsapp = os.getenv("TWILIO_WHATSAPP_NUMBER")
    to_whatsapp = os.getenv("MY_PERSONAL_PHONE")

    if not all([account_sid, auth_token, from_whatsapp, to_whatsapp]):
        logger.warning("Twilio credentials missing. Skipping WhatsApp notification.")
        return

    try:
        client = Client(account_sid, auth_token)
        
        # Format the message
        date_str = f" on {date}" if date else ""
        message_body = (
            f"🚀 *New Interview Detected!*\n\n"
            f"You have an interview for the *{role}* position at *{company}*{date_str}.\n\n"
            f"Your AI Prep Kit is ready on your dashboard!"
        )

        message = client.messages.create(
            from_=from_whatsapp,
            body=message_body,
            to=to_whatsapp
        )
        logger.info(f"WhatsApp notification sent! SID: {message.sid}")
    except Exception as e:
        logger.error(f"Failed to send WhatsApp message: {e}")

load_dotenv()
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)

# Import from Auth.py (capital A to match your filename)
from Auth import (
    SessionLocal,
    User,
    Interview,
    InterviewQuestion,
    InterviewContext,
    get_google_token_for_user,
)

SCAN_INTERVAL = int(os.getenv("SCAN_INTERVAL", 1800))  # default: 30 minutes
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

if not GEMINI_API_KEY:
    logger.error("GEMINI_API_KEY is not set. Exiting.")
    sys.exit(1)

client = genai.Client(api_key=GEMINI_API_KEY)
MODEL = "gemini-3.1-pro-preview"

GMAIL_BASE = "https://gmail.googleapis.com/gmail/v1/users/me"

# Broad query to catch potential interview emails.
# Gemini will do the real filtering.
INTERVIEW_QUERY = (
    "in:inbox -is:sent "  # Only look at the Inbox and ignore anything I sent
    "(interview OR scheduling OR recruiter OR offer OR assessment "
    "OR \"coding challenge\" OR \"phone screen\" OR onsite OR hiring OR application "
    "OR availability OR \"touch base\" OR \"connect\" OR \"chat\" OR \"speak\" "
    "OR calendly OR \"google meet\" OR zoom OR \"teams link\") "
    "newer_than:6h"
)

def fetch_candidate_emails(access_token: str) -> list[dict]:
    """Search Gmail for emails that might be interview invites."""
    headers = {"Authorization": f"Bearer {access_token}"}

    response = requests.get(
        f"{GMAIL_BASE}/messages",
        headers=headers,
        params={"q": INTERVIEW_QUERY, "maxResults": 5},
    )

    if not response.ok:
        logger.error(f"Gmail search failed: {response.status_code} {response.text}")
        return []

    messages = response.json().get("messages", [])
    if not messages:
        return []

    results = []
    for msg in messages:
        msg_data = fetch_message(access_token, msg["id"])
        if msg_data:
            results.append(msg_data)

    return results


def fetch_message(access_token: str, message_id: str) -> dict | None:
    """Fetch a single email with metadata and body."""
    headers = {"Authorization": f"Bearer {access_token}"}

    response = requests.get(
        f"{GMAIL_BASE}/messages/{message_id}",
        headers=headers,
        params={"format": "full"},
    )

    if not response.ok:
        return None

    data = response.json()
    payload = data.get("payload", {})
    headers_list = payload.get("headers", [])

    # Extract metadata
    meta = {"id": message_id, "snippet": data.get("snippet", "")}
    for h in headers_list:
        if h["name"] in ("From", "Subject", "Date"):
            meta[h["name"].lower()] = h["value"]

    # Extract body
    meta["body"] = extract_body(payload)

    return meta


def extract_body(payload: dict) -> str:
    """Extract plain text or HTML body from a Gmail message payload."""
    # Simple message
    body_data = payload.get("body", {}).get("data", "")
    if body_data:
        return base64.urlsafe_b64decode(body_data).decode("utf-8", errors="replace")

    # Multipart — prefer text/plain, fall back to text/html
    parts = payload.get("parts", [])
    plain = ""
    html = ""

    for part in parts:
        mime = part.get("mimeType", "")
        data = part.get("body", {}).get("data", "")
        if not data:
            # Check nested parts (e.g. multipart/alternative inside multipart/mixed)
            for subpart in part.get("parts", []):
                sub_mime = subpart.get("mimeType", "")
                sub_data = subpart.get("body", {}).get("data", "")
                if sub_data and sub_mime == "text/plain":
                    plain = base64.urlsafe_b64decode(sub_data).decode("utf-8", errors="replace")
                elif sub_data and sub_mime == "text/html":
                    html = base64.urlsafe_b64decode(sub_data).decode("utf-8", errors="replace")
            continue
        if mime == "text/plain":
            plain = base64.urlsafe_b64decode(data).decode("utf-8", errors="replace")
        elif mime == "text/html":
            html = base64.urlsafe_b64decode(data).decode("utf-8", errors="replace")

    return plain or html or ""

def analyze_email(email: dict) -> dict | None:
    # ... metadata setup ...
    prompt = f"""Analyze this email and determine if it is an interview invitation, 
    a scheduling request, or a recruiter reaching out to discuss a specific job role.

    Include:
    - Formal interview invites (technical, behavioral, onsite).
    - Requests for "availability" or to "hop on a quick call/chat."
    - Coding challenges or assessments.
    - Casual recruiter reach-outs asking to "touch base" or "connect."

    Exclude:
    - Generic newsletters, job board alerts, automated rejections, or marketing.

    EMAIL METADATA:
    From: {email.get('from', 'unknown')}
    Subject: {email.get('subject', 'unknown')}
    Date: {email.get('date', 'unknown')}

    EMAIL BODY:
    {email.get('body', '')[:4000]}

    Respond ONLY with a JSON object...
    
If this IS an interview invitation or scheduling email:
{{
    "is_interview": true,
    "company": "company name",
    "role": "job title/role",
    "interview_date": "date and time if mentioned, otherwise null",
    "interview_type": "behavioral/technical/phone screen/onsite/panel/unknown",
    "summary": "A brief sentence in the format of You have been invited to a x type of interview for y position at z company or some similar variation, ending in exclamation mark"
}}

If this is NOT an interview invitation (e.g. marketing, newsletter, job board alert, rejection):
{{
    "is_interview": false
}}"""

    try:
        response = client.models.generate_content(
            model=MODEL,
            contents=prompt,
        )
        text = response.text.strip()

        # Clean up potential markdown formatting
        if text.startswith("```"):
            text = text.split("\n", 1)[1] if "\n" in text else text[3:]
        if text.endswith("```"):
            text = text[:-3]
        text = text.strip()

        result = json.loads(text)
        return result if result.get("is_interview") else None

    except (json.JSONDecodeError, Exception) as e:
        logger.error(f"Gemini analysis failed for '{email.get('subject', '?')}': {e}")
        return None


def generate_questions(company: str, role: str, interview_type: str) -> list[dict]:
    """
    Ask Gemini to generate likely behavioral interview questions
    for a specific company and role.
    """
    prompt = f"""Generate 4-6 behavioral interview questions that a candidate would likely be asked
for a {role} position at {company}. The interview type is: {interview_type}.

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
            model=MODEL,
            contents=prompt,
        )
        text = response.text.strip()

        # Clean up potential markdown formatting
        if text.startswith("```"):
            text = text.split("\n", 1)[1] if "\n" in text else text[3:]
        if text.endswith("```"):
            text = text[:-3]
        text = text.strip()

        questions = json.loads(text)
        return questions if isinstance(questions, list) else []

    except (json.JSONDecodeError, Exception) as e:
        logger.error(f"Gemini question generation failed for {company} / {role}: {e}")
        return []


def generate_interview_context(company: str, role: str, interview_type: str) -> dict | None:
    """
    Ask Gemini to generate a full interview briefing: company overview,
    values, job description, skills, tailored tips, and a confidence note.
    """
    prompt = f"""You are preparing an interview briefing for a candidate applying to a
{role} position at {company}. The interview type is: {interview_type}.

Research what you know about {company} and generate a comprehensive briefing.

Respond ONLY with a JSON object, no markdown, no backticks, no extra text:
{{
    "company_name": "{company}",
    "company_summary": "2-3 sentence overview of what {company} does, its industry, size, and reputation",
    "company_values": ["value1", "value2", "value3", "value4", "value5"],
    "role_title": "{role}",
    "job_description": "A realistic 2-3 sentence description of what this role typically involves at {company} or similar companies",
    "skills_emphasized": ["skill1", "skill2", "skill3", "skill4", "skill5"],
    "tailored_tips": [
        "One short, punchy sentence with an actionable tip for {company} (max 15 words)",
        "A brief, single-sentence tip about {company}'s interview culture",
        "A concise, fast-read tip on demonstrating the right skills"
    ],
    "confidence_note": "A brief disclaimer noting this briefing is AI-generated based on publicly available information and may not reflect the exact current state of the company or role."
}}

Make the values, skills, and tips specific to {company} and the {role} role — avoid generic advice.
Each tip should be 1-2 sentences of concrete, actionable guidance."""

    try:
        response = client.models.generate_content(
            model=MODEL,
            contents=prompt,
        )
        text = response.text.strip()

        if text.startswith("```"):
            text = text.split("\n", 1)[1] if "\n" in text else text[3:]
        if text.endswith("```"):
            text = text[:-3]
        text = text.strip()

        result = json.loads(text)
        return result

    except (json.JSONDecodeError, Exception) as e:
        logger.error(f"Gemini context generation failed for {company} / {role}: {e}")
        return None


def scan_user(user: User, db) -> int:
    """
    Scan a single user's Gmail for interview emails.
    Returns the number of new interviews found.
    """
    logger.info(f"Scanning {user.email} ({user.auth0_id})...")

    # Get a valid Google access token from Auth0
    token = get_google_token_for_user(user.auth0_id)
    if not token:
        logger.warning(f"  Could not get token for {user.email} — skipping.")
        return 0

    # Get existing interview IDs to avoid reprocessing
    existing_ids = set(
        row[0] for row in
        db.query(Interview.id).filter_by(user_id=user.auth0_id).all()
    )

    # Search Gmail for candidate emails
    emails = fetch_candidate_emails(token)
    logger.info(f"  Found {len(emails)} candidate email(s) to analyze.")

    new_count = 0
    for email in emails:
        # Skip already-processed emails
        if email["id"] in existing_ids:
            logger.info(f"  Skipping already-processed: {email.get('subject', '?')}")
            continue

        # Send to Gemini for analysis
        logger.info(f"  Analyzing: {email.get('subject', '(no subject)')}")
        analysis = analyze_email(email)

        if not analysis:
            logger.info(f"    → Not an interview email.")
            continue

        logger.info(f"    → Interview detected: {analysis['company']} — {analysis['role']}")

        # Store the interview
        interview = Interview(
            id             = email["id"],
            user_id        = user.auth0_id,
            company        = analysis["company"],
            role           = analysis["role"],
            interview_date = analysis.get("interview_date"),
            interview_type = analysis.get("interview_type", "unknown"),
            email_subject  = email.get("subject"),
            email_from     = email.get("from"),
            email_date     = email.get("date"),
            email_snippet  = email.get("snippet"),
            raw_summary    = analysis.get("summary"),
        )
        db.add(interview)

        # Generate behavioral questions
        logger.info(f"    Generating behavioral questions...")
        questions = generate_questions(
            analysis["company"],
            analysis["role"],
            analysis.get("interview_type", "behavioral"),
        )

        for q in questions:
            db.add(InterviewQuestion(
                id           = str(uuid.uuid4()),
                interview_id = email["id"],
                question     = q.get("question", ""),
                category     = q.get("category"),
                tip          = q.get("tip"),
            ))

        # Generate interview context briefing
        logger.info(f"    Generating interview context briefing...")
        context = generate_interview_context(
            analysis["company"],
            analysis["role"],
            analysis.get("interview_type", "behavioral"),
        )

        if context:
            db.add(InterviewContext(
                id                = str(uuid.uuid4()),
                interview_id      = email["id"],
                company_name      = context.get("company_name", analysis["company"]),
                company_summary   = context.get("company_summary"),
                company_values    = json.dumps(context.get("company_values", [])),
                role_title        = context.get("role_title", analysis["role"]),
                job_description   = context.get("job_description"),
                skills_emphasized = json.dumps(context.get("skills_emphasized", [])),
                tailored_tips     = json.dumps(context.get("tailored_tips", [])),
                confidence_note   = context.get("confidence_note"),
            ))
            logger.info(f"    Saved interview context briefing.")
        else:
            logger.warning(f"    Could not generate context briefing — skipping.")

        db.commit()
        new_count += 1
        logger.info(f"    Saved interview + {len(questions)} questions.")

        send_whatsapp_notification(
            company=analysis["company"],
            role=analysis["role"],
            date=analysis.get("interview_date")
        )
    return new_count


def run_scan():
    """Run a scan for all opted-in users."""
    db = SessionLocal()
    try:
        users = db.query(User).filter_by(scanning=True).all()
        logger.info(f"Starting scan for {len(users)} user(s)...")

        total = 0
        for user in users:
            try:
                count = scan_user(user, db)
                total += count

                # Update last scanned timestamp
                user.last_scanned = datetime.now(timezone.utc)
                db.commit()

            except Exception as e:
                logger.error(f"  Error scanning {user.email}: {e}")
                db.rollback()
                continue

        logger.info(f"Scan complete. {total} new interview(s) found across {len(users)} user(s).")

    finally:
        db.close()

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Background email scanner")
    parser.add_argument("--loop", action="store_true", help="Run continuously")
    args = parser.parse_args()

    if args.loop:
        logger.info(f"Running in loop mode (every {SCAN_INTERVAL}s). Ctrl+C to stop.")
        while True:
            try:
                run_scan()
            except Exception as e:
                logger.error(f"Scan cycle failed: {e}")
            time.sleep(SCAN_INTERVAL)
    else:
        run_scan()