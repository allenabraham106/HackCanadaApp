import { useState, useEffect, useRef } from "react"
import { useLocation } from "react-router-dom"
import Camera from "./Camera"
import { speakText, stopSpeaking } from "./elevenLabs"
import "./Interview.css"

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || "http://127.0.0.1:8001"
const AUTH_API_BASE_URL = import.meta.env.VITE_AUTH_API_BASE_URL || "http://localhost:8000"

const FALLBACK_QUESTIONS = [
  "Tell me about yourself.",
  "Describe a challenge you overcame at work.",
  "Where do you see yourself in five years?",
]

function questionTexts(questions) {
  return Array.isArray(questions)
    ? questions.map((q) => (typeof q === "string" ? q : q?.question)).filter(Boolean)
    : []
}

export default function Interview() {
  const { state } = useLocation()
  const company = state?.company
  const role = state?.role || "software engineer"
  const interviewId = state?.interviewId

  const [questions, setQuestions] = useState([])
  const [currentQ, setCurrentQ] = useState(0)
  const [loading, setLoading] = useState(true)
  const [apiError, setApiError] = useState(null)
  const [started, setStarted] = useState(false)
  const [ended, setEnded] = useState(false)
  const [answerSubmitted, setAnswerSubmitted] = useState(false)
  const [lastRecordingUrl, setLastRecordingUrl] = useState(null)
  const cameraRef = useRef(null)

  // Fetch questions: from Auth (Gemini/stored) when interviewId present, else FastAPI mock-interview
  useEffect(() => {
    fetch(`${API_BASE_URL}/reset-session`, { method: "POST" }).catch(() => {})

    const authOpts = { credentials: "include" }

    if (interviewId) {
      fetch(`${AUTH_API_BASE_URL}/interviews/${interviewId}/questions`, authOpts)
        .then((res) => res.json())
        .then((data) => {
          const list = questionTexts(data?.questions).slice(0, 3)
          if (list.length > 0) {
            setQuestions(list)
            setApiError(null)
            setLoading(false)
            return
          }
          return fetch(`${AUTH_API_BASE_URL}/interviews/${interviewId}/generate-questions`, {
            method: "POST",
            ...authOpts,
          })
            .then((r) => r.json())
            .then((gen) => {
              const generated = questionTexts(gen?.questions).slice(0, 3)
              if (generated.length > 0) {
                setQuestions(generated)
                setApiError(null)
              } else {
                setQuestions(FALLBACK_QUESTIONS)
                setApiError(gen?.error || "Generated no questions; using defaults.")
              }
            })
        })
        .catch(() => {
          setQuestions(FALLBACK_QUESTIONS)
          setApiError("Could not load interview questions. Using defaults.")
        })
        .finally(() => setLoading(false))
      return
    }

    fetch(`${API_BASE_URL}/mock-interview`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ role, company: company || undefined, num_questions: 3 }),
    })
      .then((res) => res.json().then((data) => ({ ok: res.ok, data })))
      .then(({ ok, data }) => {
        if (ok && Array.isArray(data?.questions) && data.questions.length > 0) {
          setQuestions(data.questions.slice(0, 3))
          setApiError(null)
        } else {
          setQuestions(FALLBACK_QUESTIONS)
          setApiError(data?.error || "Using default questions.")
        }
        setLoading(false)
      })
      .catch((err) => {
        console.error("Mock interview fetch failed:", err)
        setQuestions(FALLBACK_QUESTIONS)
        setApiError("Could not reach the server. Using default questions.")
        setLoading(false)
      })
  }, [company, role, interviewId])

  // Speak question when it changes (only after interview started, not when ended)
  useEffect(() => {
    if (started && !ended && questions.length > 0 && currentQ < questions.length) {
      speakText(questions[currentQ])
    }
  }, [started, ended, currentQ, questions])

  function tryStartRecording() {
    if (started && !ended && currentQ < questions.length && !answerSubmitted) {
      cameraRef.current?.startRecording?.()
    }
  }

  // Auto-start recording when on a question (useEffect for state changes)
  useEffect(() => {
    tryStartRecording()
  }, [started, ended, currentQ, questions.length, answerSubmitted])

  // Start recording when Camera becomes ready (handles remount after Next Question)
  function handleCameraReady() {
    tryStartRecording()
  }

  function handleRecordingComplete(blob, url) {
    setLastRecordingUrl(url)
  }

  function handleComplete() {
    stopSpeaking()
    cameraRef.current?.stopRecording?.()
    setAnswerSubmitted(true)
  }

  function handleNextQuestion() {
    if (currentQ >= questions.length) return
    setAnswerSubmitted(false)
    setLastRecordingUrl(null)
    setCurrentQ(prev => prev + 1)
  }

  const complete = ended || currentQ >= questions.length

  if (loading) return <div className="interview-loading">Generating your interview questions...</div>

  if (questions.length === 0) {
    return (
      <div className="interview-page">
        <div className="interview-error-box">
          <strong>No questions loaded</strong>
          {apiError && <p className="interview-error-text">{apiError}</p>}
          <p className="interview-error-hint">Make sure the backend is running and GEMINI_API_KEY is set in hackcanada-backend/.env</p>
        </div>
      </div>
    )
  }

  return (
    <div className="interview-page">
      {/* Practicing for — at top */}
      <div className="interview-header">
        <span className="interview-label">Practicing for</span>
        <span className="interview-context">{company && role ? `${company} · ${role}` : role}</span>
      </div>

      {/* Questions — only visible after Start interview, hidden when answer submitted */}
      {started && !complete && !answerSubmitted && (
        <div className="interview-questions-card">
          <span className="interview-questions-label">Question {currentQ + 1} of {questions.length}</span>
          <p className="interview-current-question">
            {questions[currentQ]}
          </p>
        </div>
      )}

      {/* Camera — hidden when answer submitted or on Interview Summary; unmount kills camera (green light off) */}
      <div className="interview-section">
        {!answerSubmitted && !complete && (
          <Camera
            ref={cameraRef}
            onRecordingComplete={handleRecordingComplete}
            onCameraReady={handleCameraReady}
            externalControls
          />
        )}
        {!started ? (
          <button
            type="button"
            onClick={() => setStarted(true)}
            className="interview-start-btn"
          >
            Start interview
          </button>
        ) : complete ? (
          /* Interview Summary — shown when all questions done */
          <div className="interview-summary">
            <h1 className="interview-summary-title">Interview Summary</h1>
            <p className="interview-summary-text">Your interview is complete. Review your performance and key takeaways below.</p>
          </div>
        ) : answerSubmitted ? (
          /* After Complete: Below your recording + Next Question (no camera, no next question preview) */
          <div className="interview-post-answer">
            <div className="interview-recording-section">
              <h3 className="interview-recording-label">Below your recording</h3>
              {lastRecordingUrl && (
                <video src={lastRecordingUrl} controls className="interview-recording-playback" />
              )}
            </div>
            <button
              type="button"
              onClick={handleNextQuestion}
              className="interview-next-btn"
            >
              Next Question →
            </button>
          </div>
        ) : (
          /* During recording: Complete + End interview */
          <div className="interview-actions">
            <button
              type="button"
              onClick={handleComplete}
              className="interview-complete-btn"
            >
              Complete
            </button>
            <button
              type="button"
              onClick={() => {
                stopSpeaking()
                setEnded(true)
                cameraRef.current?.stopRecording?.()
              }}
              className="interview-end-btn"
            >
              End interview
            </button>
          </div>
        )}
      </div>
    </div>
  )
}
