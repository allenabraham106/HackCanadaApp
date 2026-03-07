import { useState, useEffect } from "react"
import Camera from "./Camera"
import { speakText } from "./elevenLabs"

export default function Interview() {
  const [questions, setQuestions] = useState([])
  const [currentQ, setCurrentQ] = useState(0)
  const [score, setScore] = useState(100)
  const [tip, setTip] = useState(null)
  const [loading, setLoading] = useState(true)

  // Fetch questions from backend on load
  useEffect(() => {
    fetch("http://127.0.0.1:8000/mock-interview", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ role: "software engineer", num_questions: 5 })
    })
    .then(res => res.json())
    .then(data => {
      setQuestions(data.questions)
      setLoading(false)
    })
  }, [])

  // Speak question when it changes
  useEffect(() => {
    if (questions.length > 0 && currentQ < questions.length) {
      speakText(questions[currentQ])
    }
  }, [currentQ, questions])

  function nextQuestion() {
    setCurrentQ(prev => prev + 1)
  }

  if (loading) return <div style={styles.loading}>Generating your interview questions... 🤔</div>

  return (
    <div style={styles.container}>
      {/* Score bar */}
      <div style={styles.scoreBar}>
        <div style={styles.scoreLabel}>Score: {score}/100</div>
        <div style={styles.barBg}>
          <div style={{ ...styles.barFill, width: `${score}%` }} />
        </div>
        {tip && <div style={styles.tip}>{tip}</div>}
      </div>

      {/* Current question */}
      <div style={styles.question}>
        {currentQ < questions.length
          ? `Q${currentQ + 1}: ${questions[currentQ]}`
          : "Interview complete! 🎉"}
      </div>

      {/* Camera */}
      <Camera onRecordingComplete={(blob, url) => console.log("done", url)} />

      {/* Next button */}
      {currentQ < questions.length && (
        <button onClick={nextQuestion} style={styles.nextBtn}>
          Next Question →
        </button>
      )}
    </div>
  )
}

const styles = {
  container: { maxWidth: "800px", margin: "0 auto", padding: "20px", fontFamily: "sans-serif" },
  loading: { textAlign: "center", padding: "40px", fontSize: "20px" },
  scoreBar: { marginBottom: "20px" },
  scoreLabel: { fontSize: "18px", fontWeight: "bold", marginBottom: "8px" },
  barBg: { background: "#eee", borderRadius: "10px", height: "20px", overflow: "hidden" },
  barFill: { background: "#4CAF50", height: "100%", borderRadius: "10px", transition: "width 0.5s" },
  tip: { marginTop: "8px", color: "#ff9800", fontWeight: "bold" },
  question: { fontSize: "22px", fontWeight: "bold", margin: "20px 0", padding: "20px", background: "#f5f5f5", borderRadius: "12px" },
  nextBtn: { marginTop: "16px", background: "#2196F3", color: "white", border: "none", padding: "12px 32px", borderRadius: "8px", fontSize: "16px", cursor: "pointer" }
}