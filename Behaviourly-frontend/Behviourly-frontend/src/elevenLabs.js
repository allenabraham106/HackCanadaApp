/**
 * Text-to-speech for interview questions.
 * Uses backend ElevenLabs proxy when configured, with browser Speech Synthesis fallback.
 */
const API_BASE_URL = (import.meta.env.VITE_API_BASE_URL || "http://127.0.0.1:8001").replace(/\/$/, "")
const ELEVENLABS_VOICE_ID = (import.meta.env.VITE_ELEVENLABS_VOICE_ID || "").trim()
const ELEVENLABS_MODEL_ID = (import.meta.env.VITE_ELEVENLABS_MODEL_ID || "").trim()

let currentAbortController = null
let currentAudio = null

export async function speakText(text) {
  if (!text || typeof text !== "string") return

  stopSpeaking()

  try {
    await speakWithElevenLabs(text)
    return
  } catch (error) {
    console.warn("ElevenLabs TTS unavailable, using browser speech synthesis.", error)
  }

  fallbackSpeak(text)
}

async function speakWithElevenLabs(text) {
  currentAbortController = new AbortController()

  const payload = { text }
  if (ELEVENLABS_VOICE_ID) payload.voice_id = ELEVENLABS_VOICE_ID
  if (ELEVENLABS_MODEL_ID) payload.model_id = ELEVENLABS_MODEL_ID

  const response = await fetch(`${API_BASE_URL}/tts`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
    signal: currentAbortController.signal,
  })

  if (!response.ok) {
    const details = await response.text().catch(() => "")
    throw new Error(`TTS request failed (${response.status}): ${details.slice(0, 180)}`)
  }

  const blob = await response.blob()
  if (!blob || blob.size === 0) throw new Error("No audio returned from TTS endpoint")

  const audioUrl = URL.createObjectURL(blob)
  const audio = new Audio(audioUrl)
  currentAudio = audio

  audio.onended = () => {
    URL.revokeObjectURL(audioUrl)
    if (currentAudio === audio) currentAudio = null
  }
  audio.onerror = () => {
    URL.revokeObjectURL(audioUrl)
    if (currentAudio === audio) currentAudio = null
  }

  await audio.play()
}

function fallbackSpeak(text) {
  if (!("speechSynthesis" in window)) return
  window.speechSynthesis.cancel()
  const utterance = new SpeechSynthesisUtterance(text)
  utterance.rate = 0.9
  utterance.pitch = 1
  window.speechSynthesis.speak(utterance)
}

export function stopSpeaking() {
  if (currentAbortController) {
    currentAbortController.abort()
    currentAbortController = null
  }
  if (currentAudio) {
    if (currentAudio.src?.startsWith("blob:")) {
      URL.revokeObjectURL(currentAudio.src)
    }
    currentAudio.pause()
    currentAudio.currentTime = 0
    currentAudio = null
  }
  if ("speechSynthesis" in window) window.speechSynthesis.cancel()
}
