/**
 * Text-to-speech for interview questions.
 * Uses ElevenLabs API when VITE_ELEVENLABS_API_KEY and VITE_ELEVENLABS_VOICE_ID are set.
 * Falls back to browser Speech Synthesis otherwise.
 */
const API_KEY = import.meta.env.VITE_ELEVENLABS_API_KEY
const VOICE_ID = import.meta.env.VITE_ELEVENLABS_VOICE_ID

let currentAbortController = null
let currentAudio = null

export async function speakText(text) {
  if (!text || typeof text !== "string") return

  stopSpeaking()

  if (API_KEY && VOICE_ID) {
    currentAbortController = new AbortController()
    try {
      const res = await fetch(`https://api.elevenlabs.io/v1/text-to-speech/${VOICE_ID}`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "xi-api-key": API_KEY,
        },
        body: JSON.stringify({ text, model_id: "eleven_multilingual_v2" }),
        signal: currentAbortController.signal,
      })
      if (!res.ok) throw new Error("ElevenLabs request failed")
      const blob = await res.blob()
      const url = URL.createObjectURL(blob)
      currentAudio = new Audio(url)
      currentAudio.onended = () => URL.revokeObjectURL(url)
      await currentAudio.play()
    } catch (err) {
      if (err.name !== "AbortError") fallbackSpeak(text)
    } finally {
      currentAbortController = null
    }
  } else {
    fallbackSpeak(text)
  }
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
    currentAudio.pause()
    currentAudio.currentTime = 0
    currentAudio = null
  }
  if ("speechSynthesis" in window) window.speechSynthesis.cancel()
}
