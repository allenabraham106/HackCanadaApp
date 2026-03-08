import json
import asyncio
from typing import List, Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field, ValidationError


router = APIRouter(tags=["interview_context"])


class InterviewContextRequest(BaseModel):
    company_name: str = Field(..., min_length=1)
    role_title: str = Field(..., min_length=1)
    job_description: Optional[str] = None


class CompanyInfo(BaseModel):
    name: str
    summary: str
    values: List[str]


class RoleInfo(BaseModel):
    title: str


class InterviewContextResponse(BaseModel):
    company: CompanyInfo
    role: RoleInfo
    skills_emphasized: List[str]
    tailored_tips: List[str]
    confidence_note: str


def build_prompt(payload: InterviewContextRequest) -> str:
    job_desc_text = payload.job_description.strip() if payload.job_description else "Not provided."

    return f"""
You are generating a pre-interview briefing page for a mock interview app.

Input:
- Company name: {payload.company_name}
- Role title: {payload.role_title}
- Job description:
{job_desc_text}

Your task:
Return ONLY valid JSON.
Do not wrap the JSON in markdown.
Do not include any explanation outside the JSON.

Output schema:
{{
  "company": {{
    "name": "string",
    "summary": "1-2 sentence company summary tailored to interview prep",
    "values": ["string", "string", "string"]
  }},
  "role": {{
    "title": "string"
  }},
  "skills_emphasized": ["string", "string", "string", "string"],
  "tailored_tips": ["string", "string", "string"],
  "confidence_note": "State whether this is based mostly on the job description or inferred from company + role only."
}}

Rules:
- Keep lists concise and useful.
- Prefer interview-relevant information over generic company trivia.
- Company values should reflect what the company likely cares about in employees.
- skills_emphasized should be the main skills this role is likely looking for.
- tailored_tips should be specific to succeeding in an interview for this company and role.
- If the job description is missing, infer carefully from the company and role title and say so in confidence_note.
- Keep everything practical for a student preparing for an interview.
""".strip()


def extract_json_text(raw_text: str) -> str:
    text = raw_text.strip()

    if text.startswith("```"):
        lines = text.splitlines()

        if lines:
            lines = lines[1:]

        if lines and lines[-1].strip().startswith("```"):
            lines = lines[:-1]

        text = "\n".join(lines).strip()

    return text


@router.post("/interview_context", response_model=InterviewContextResponse)
async def generate_interview_context(
    payload: InterviewContextRequest,
    request: Request,
):
    model = getattr(request.app.state, "gemini_model", None)

    if model is None:
        raise HTTPException(status_code=500, detail="Gemini model not configured on app.state")

    prompt = build_prompt(payload)

    try:
        if hasattr(model, "generate_content"):
            response = await asyncio.to_thread(model.generate_content, prompt)
        elif hasattr(model, "models") and hasattr(model.models, "generate_content"):
            response = await asyncio.to_thread(
                model.models.generate_content,
                model="gemini-2.0-flash-lite",
                contents=prompt,
            )
        else:
            raise HTTPException(status_code=500, detail="Configured Gemini model is invalid")

        raw_text = getattr(response, "text", None)
        if not raw_text:
            raise HTTPException(status_code=502, detail="Model returned no text")

        json_text = extract_json_text(raw_text)
        data = json.loads(json_text)

        validated = InterviewContextResponse.model_validate(data)
        return validated

    except json.JSONDecodeError:
        raise HTTPException(
            status_code=502,
            detail="Model did not return valid JSON"
        )
    except ValidationError as e:
        raise HTTPException(
            status_code=502,
            detail=f"Model JSON did not match expected schema: {e.errors()}"
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to generate interview context: {str(e)}"
        )
