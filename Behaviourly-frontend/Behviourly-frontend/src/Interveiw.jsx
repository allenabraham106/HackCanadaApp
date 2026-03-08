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

// Never show raw markdown/JSON from the API (e.g. ```json { "transcript"...)
function sanitizeDisplayText(s) {
  if (s == null || typeof s !== "string") return ""
  let t = s.trim()
  if (t.startsWith("```json")) t = t.slice(7).trim()
  else if (t.startsWith("```")) t = t.slice(3).trim()
  if (t.endsWith("```")) t = t.slice(0, -3).trim()
  if (t.startsWith("{") || t.startsWith("[")) return ""
  return t
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
  const [presageResult, setPresageResult] = useState(null)
  const [presageLoading, setPresageLoading] = useState(false)
  const [vitalsByQuestion, setVitalsByQuestion] = useState([])
  const [backendStatus, setBackendStatus] = useState(null)
  const [aiReady, setAiReady] = useState(null)
  const cameraRef = useRef(null)
  const lastRecordingBlobRef = useRef(null)

  useEffect(() => {
    return () => {
      stopSpeaking()
      cameraRef.current?.cleanup?.()
    }
  }, [])

  // Check if backend is up and AI (Gemini) is configured
  useEffect(() => {
    const base = (import.meta.env.VITE_API_BASE_URL || "http://127.0.0.1:8001").replace(/\/$/, "")
    let cancelled = false
    Promise.all([
      fetch(`${base}/health`).then((r) => (r.ok ? "ok" : "error")).catch(() => "error"),
      fetch(`${base}/health/ready`).then((r) => r.json().then((d) => d.ready === true)).catch(() => false),
    ]).then(([status, ready]) => {
      if (!cancelled) {
        setBackendStatus(status)
        setAiReady(ready)
      }
    })
    return () => { cancelled = true }
  }, [])

  // Show interview immediately with fallback questions; fetch AI questions in background and swap when ready
  useEffect(() => {
    fetch(`${API_BASE_URL}/reset-session`, { method: "POST" }).catch(() => {})

    setQuestions(FALLBACK_QUESTIONS)
    setLoading(false)

    const authOpts = { credentials: "include" }

    if (interviewId) {
      fetch(`${AUTH_API_BASE_URL}/interviews/${interviewId}/questions`, authOpts)
        .then((res) => res.json())
        .then((data) => {
          const list = questionTexts(data?.questions).slice(0, 3)
          if (list.length > 0) {
            setQuestions(list)
            setApiError(null)
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
                setApiError(gen?.error || "Using default questions.")
              }
            })
        })
        .catch(() => setApiError("Using default questions."))
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
          setApiError(data?.error || "Using default questions.")
        }
      })
      .catch(() => setApiError("Could not reach the server. Using default questions."))
  }, [company, role, interviewId])

  // Speak question when it changes (only after interview started, not when ended)
  useEffect(() => {
    if (started && !ended && questions.length > 0 && currentQ < questions.length) {
      speakText(questions[currentQ])
    }
  }, [started, ended, currentQ, questions])

  // Fetch AI recommendation (feedback + highlight) when we have a transcript and no feedback yet
  useEffect(() => {
    if (!presageResult?.transcript || presageResult.feedback != null || presageLoading) return
    const question = presageResult.question || questions[presageResult.questionIndex]
    if (!question) return
    const base = (import.meta.env.VITE_API_BASE_URL || "http://127.0.0.1:8001").replace(/\/$/, "")
    const qIndex = presageResult.questionIndex
    fetch(`${base}/analyze-answer`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ question, answer: presageResult.transcript }),
    })
      .then((r) => r.json())
      .then((data) => {
        if (data.error) return
        setPresageResult((prev) =>
          prev ? { ...prev, feedback: data.feedback, highlight: data.highlight, rating: data.rating, score: data.score } : null
        )
        setVitalsByQuestion((prev) =>
          prev.map((v, i) => (i === qIndex ? { ...v, feedback: data.feedback, highlight: data.highlight, rating: data.rating, score: data.score } : v))
        )
      })
      .catch(() => {})
  }, [presageResult?.transcript, presageResult?.question, presageResult?.questionIndex, presageResult?.feedback, presageLoading, questions])

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
    lastRecordingBlobRef.current = blob
    setLastRecordingUrl(url)
  }

  async function handleComplete() {
    stopSpeaking()
    const stopResult = await cameraRef.current?.stopRecording?.().catch(() => ({}))
    const blob = stopResult?.blob ?? lastRecordingBlobRef.current
    const url = stopResult?.url
    setAnswerSubmitted(true)
    if (url) {
      setLastRecordingUrl(url)
    }
    if (blob) {
      lastRecordingBlobRef.current = blob
    }
    if (blob && API_BASE_URL) {
      setPresageLoading(true)
      setPresageResult(null)
      // Slightly longer delay for Q2/Q3 so we don't burst Gemini (rate limits often make 1/3 succeed)
      await new Promise((r) => setTimeout(r, currentQ > 0 ? 2500 : 500))
      const base = API_BASE_URL.replace(/\/$/, "")
      const buildEntry = (data) => ({
        questionIndex: currentQ,
        question: questions[currentQ],
        heartRate: data.heartRate ?? null,
        breathingRate: data.breathingRate ?? null,
        stressLevel: data.stressLevel || "unknown",
        source: data.source || "presage",
        confidence: data.confidence,
        eyeContact: data.eyeContact,
        bodyLanguageNotes: data.bodyLanguageNotes,
        transcript: data.transcript ?? null,
        feedback: data.feedback ?? null,
        highlight: data.highlight ?? null,
        rating: data.rating ?? null,
        score: data.score ?? null,
      })
      let showedFeedback = false
      const form = new FormData()
      form.append("video", blob, "recording.webm")
      const formTranscribe = new FormData()
      formTranscribe.append("video", blob, "recording.webm")
      let transcriptFromApi = null
      const ANALYZE_TIMEOUT_MS = 50000
      const withTimeout = (promise, ms) => {
        const c = new AbortController()
        const t = setTimeout(() => c.abort(), ms)
        return Promise.race([
          promise,
          new Promise((_, rej) => c.signal.addEventListener("abort", () => rej(new Error("timeout")))),
        ]).finally(() => clearTimeout(t))
      }
      try {
        const [analyzeRes, transcribeRes] = await Promise.all([
          withTimeout(fetch(`${base}/gemini/analyze-video`, { method: "POST", body: form }), ANALYZE_TIMEOUT_MS).catch((e) => ({ ok: false, json: () => Promise.resolve({ error: e?.message || "timeout" }) })),
          withTimeout(fetch(`${base}/transcribe`, { method: "POST", body: formTranscribe }), ANALYZE_TIMEOUT_MS).catch(() => null),
        ])
        const transcribeData = transcribeRes?.ok ? await transcribeRes.json().catch(() => ({})) : null
        if (transcribeData?.transcript) transcriptFromApi = transcribeData.transcript
        let data = await analyzeRes.json().catch(() => ({}))
        if (analyzeRes.ok && (data.stressLevel || data.bodyLanguageNotes)) {
          const transcript = transcriptFromApi ?? data.transcript ?? null
          const entry = buildEntry({ ...data, stressLevel: data.stressLevel || "unknown", transcript })
          setPresageResult(entry)
          setVitalsByQuestion((prev) => [...prev, entry])
          showedFeedback = true
        } else if (analyzeRes.ok && data.error) {
          const fallback = buildEntry({
            stressLevel: "unknown",
            bodyLanguageNotes: data.error || "Video received — you're good to continue.",
            source: "gemini",
            transcript: transcriptFromApi,
          })
          setPresageResult(fallback)
          setVitalsByQuestion((prev) => [...prev, fallback])
          showedFeedback = true
        }
        if (!showedFeedback) {
          const formPresage = new FormData()
          formPresage.append("video", blob, "recording.webm")
          const controller = new AbortController()
          const timeoutId = setTimeout(() => controller.abort(), 70000)
          res = await fetch(`${base}/presage/analyze`, { method: "POST", body: formPresage, signal: controller.signal })
          clearTimeout(timeoutId)
          data = await res.json().catch(() => ({}))
          if (res.ok && data.heartRate != null) {
            const entry = buildEntry({ ...data, transcript: transcriptFromApi ?? data.transcript })
            setPresageResult(entry)
            setVitalsByQuestion((prev) => [...prev, entry])
            showedFeedback = true
          }
        }
      } catch (e) {
        try {
          const form2 = new FormData()
          form2.append("video", blob, "recording.webm")
          const formTranscribe2 = new FormData()
          formTranscribe2.append("video", blob, "recording.webm")
          const transcribeRes = await fetch(`${base}/transcribe`, { method: "POST", body: formTranscribe2 }).catch(() => null)
          const transcribeData = transcribeRes?.ok ? await transcribeRes.json().catch(() => ({})) : null
          const transcriptFallback = transcribeData?.transcript ?? null
          if (transcriptFallback) transcriptFromApi = transcriptFallback
          const controller = new AbortController()
          const timeoutId = setTimeout(() => controller.abort(), 70000)
          const res = await fetch(`${base}/presage/analyze`, { method: "POST", body: form2, signal: controller.signal })
          clearTimeout(timeoutId)
          const data = await res.json().catch(() => ({}))
          if (res.ok && data.heartRate != null) {
            const entry = buildEntry({ ...data, transcript: transcriptFallback ?? data.transcript })
            setPresageResult(entry)
            setVitalsByQuestion((prev) => [...prev, entry])
            showedFeedback = true
          }
        } catch (e2) {
          if (e.name !== "AbortError") console.warn("Video analysis failed:", e)
        }
      }
      if (!showedFeedback) {
        const fallback = buildEntry({
          stressLevel: "unknown",
          bodyLanguageNotes: "Video received. You're good to continue.",
          source: "gemini",
          transcript: transcriptFromApi ?? null,
        })
        setPresageResult(fallback)
        setVitalsByQuestion((prev) => [...prev, fallback])
      }
      setPresageLoading(false)
    }
    if (currentQ == questions.length - 1) {
      cameraRef.current?.cleanup?.()
    }
  }

  function handleNextQuestion() {
    if (currentQ >= questions.length) return
    setAnswerSubmitted(false)
    setLastRecordingUrl(null)
    setPresageResult(null)
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
          <p className="interview-speak-hint">Speak clearly at a moderate pace so we can transcribe your answer and give you AI recommendations.</p>
        </div>
      )}

      {/* Camera — keep mounted until summary so stream stays alive for Q2–Q4; hide when answer submitted */}
      <div className={`interview-section ${answerSubmitted ? "interview-section--camera-hidden" : ""}`}>
        {!complete && (
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
          /* Interview Summary — shown when all questions done; vitals data at the end */
          <div className="interview-summary">
            <h1 className="interview-summary-title">Interview Summary</h1>
            <p className="interview-summary-text">Your interview is complete. Review your performance and key takeaways below.</p>
            <div className="interview-summary-vitals">
              <h2 className="interview-summary-vitals-title">Vitals & stress by question</h2>
              {presageLoading && vitalsByQuestion.length === 0 && (
                <p className="interview-summary-vitals-wait">Analyzing your last answer… (this can take 30–90 seconds)</p>
              )}
              {!presageLoading && vitalsByQuestion.length === 0 && (
                <p className="interview-summary-vitals-empty">No feedback yet. Tap <strong>Complete</strong> on each answer and wait for &quot;Getting AI feedback…&quot; to finish — then you&apos;ll see stress, confidence, and notes here.</p>
              )}
              {vitalsByQuestion.length > 0 && (
                <>
                  <div className="interview-summary-vitals-grid">
                    {vitalsByQuestion.map((v, i) => (
                      <div 
                        key={i} 
                        className="interview-summary-vitals-card" 
                        style={vitalsByQuestion.length % 2 !== 0 && i === vitalsByQuestion.length - 1 ? { gridColumn: "1 / -1" } : {}}
                      >
                      <div className="interview-summary-vitals-card-header">
                        <span className="interview-summary-vitals-q">Q{v.questionIndex + 1}</span>
                        <span className={`interview-summary-vitals-pill interview-vibes--${v.stressLevel}`}>
                          {v.stressLevel === "calm" && "Calm"}
                          {v.stressLevel === "elevated" && "Elevated"}
                          {v.stressLevel === "high" && "High stress"}
                          {v.stressLevel === "unknown" && "—"}
                        </span>
                        {v.source === "gemini" && <span className="interview-summary-vitals-source">AI</span>}
                      </div>
                      <p className="interview-summary-vitals-question">{v.question}</p>
                      <div className="interview-summary-vitals-metrics">
                        {v.heartRate != null && <span>HR <strong>{v.heartRate}</strong> bpm</span>}
                        {v.breathingRate != null && <span>Breathing <strong>{v.breathingRate}</strong>/min</span>}
                        {v.source === "gemini" && v.confidence != null && <span>Confidence <strong>{v.confidence}</strong>/5</span>}
                        {v.source === "gemini" && v.eyeContact && <span>Eyes <strong>{v.eyeContact}</strong></span>}
                      </div>
                      <p className="interview-summary-vitals-notes">{sanitizeDisplayText(v.bodyLanguageNotes) || "Video reviewed."}</p>
                      {v.feedback && <p className="interview-summary-vitals-feedback"><strong>Recommendation:</strong> {v.feedback}</p>}
                      {v.highlight && <p className="interview-summary-vitals-highlight">✓ {v.highlight}</p>}
                      {sanitizeDisplayText(v.transcript) && <p className="interview-summary-vitals-transcript">{sanitizeDisplayText(v.transcript)}</p>}
                      </div>
                    ))}
                  </div>
                  <div className="interview-summary-vitals-avg">
                    {(() => {
                      const withHr = vitalsByQuestion.filter((v) => v.heartRate != null)
                      const withRr = vitalsByQuestion.filter((v) => v.breathingRate != null)
                      const avgHr = withHr.length ? (withHr.reduce((a, v) => a + v.heartRate, 0) / withHr.length).toFixed(1) : null
                      const avgRr = withRr.length ? (withRr.reduce((a, v) => a + v.breathingRate, 0) / withRr.length).toFixed(1) : null
                      const stressCounts = { calm: 0, elevated: 0, high: 0 }
                      vitalsByQuestion.forEach((v) => { if (v.stressLevel in stressCounts) stressCounts[v.stressLevel]++ })
                      return (
                        <>
                          {avgHr != null && <span>Avg heart rate <strong>{avgHr}</strong> bpm</span>}
                          {avgRr != null && <span>Avg breathing <strong>{avgRr}</strong>/min</span>}
                          <span>Stress: {stressCounts.calm} calm, {stressCounts.elevated} elevated, {stressCounts.high} high</span>
                        </>
                      )
                    })()}
                  </div>
                </>
              )}
            </div>
          </div>
        ) : answerSubmitted ? (
          /* After Complete: Below your recording + Presage vibes + Next Question */
          <div className="interview-post-answer">
            <div className="interview-recording-section">
              <h3 className="interview-recording-label">Below your recording</h3>
              {lastRecordingUrl && (
                <video src={lastRecordingUrl} controls className="interview-recording-playback" />
              )}
            </div>
            {presageLoading && (
              <div className="interview-analyzing-block">
                <p className="interview-presage-loading">Getting AI feedback… (usually a few seconds)</p>
                <p className="interview-analyzing-hint">Wait for the result below — then tap &quot;Next Question&quot;.</p>
              </div>
            )}
            {presageResult && !presageLoading && (
              <div className="interview-vibes-block">
                <div className="interview-vibes">
                  <span className={`interview-vibes-pill interview-vibes--${presageResult.stressLevel || "unknown"}`}>
                    {presageResult.stressLevel === "calm" && "😌 Calm"}
                    {presageResult.stressLevel === "elevated" && "🙂 Elevated"}
                    {presageResult.stressLevel === "high" && "😰 High stress"}
                    {(presageResult.stressLevel === "unknown" || !presageResult.stressLevel) && "—"}
                  </span>
                  {presageResult.heartRate != null && <span className="interview-vibes-hr">HR {presageResult.heartRate} bpm</span>}
                  {presageResult.breathingRate != null && <span className="interview-vibes-rr">Breathing {presageResult.breathingRate}/min</span>}
                  {presageResult.source === "gemini" && <span className="interview-vibes-ai">AI analysis</span>}
                  {(() => {
                    const notes = sanitizeDisplayText(presageResult.bodyLanguageNotes)
                    return <span className="interview-vibes-notes">{notes || "Video reviewed."}</span>
                  })()}
                </div>
                {(() => {
                  const transcript = sanitizeDisplayText(presageResult.transcript)
                  return transcript ? (
                    <div className="interview-transcript-block">
                      <strong>What you said:</strong>
                      <p className="interview-transcript-text">{transcript}</p>
                    </div>
                  ) : null
                })()}
                {presageResult.feedback && (
                  <div className="interview-recommendation-block">
                    <strong>AI recommendation:</strong>
                    <p className="interview-recommendation-feedback">{presageResult.feedback}</p>
                    {presageResult.highlight && <p className="interview-recommendation-highlight">✓ {presageResult.highlight}</p>}
                  </div>
                )}
                <p className="interview-ready-hint">✓ Done — tap &quot;Next Question&quot; when ready.</p>
              </div>
            )}
            {!presageLoading && !presageResult && (
              <p className="interview-no-vitals-hint">Analysis didn&apos;t return data. You can still tap &quot;Next Question&quot; to continue.</p>
            )}
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
                cameraRef.current?.cleanup?.()
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