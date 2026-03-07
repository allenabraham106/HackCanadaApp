import { useRef, useState, useEffect } from "react";

export default function Camera({ onRecordingComplete }) {
  const videoRef = useRef(null);
  const mediaRecorderRef = useRef(null);
  const chunksRef = useRef([]);

  const [cameraReady, setCameraReady] = useState(false);
  const [recording, setRecording] = useState(false);
  const [error, setError] = useState(null);

  // ─────────────────────────────────────────────
  // Start camera on mount
  // ─────────────────────────────────────────────
  useEffect(() => {
    startCamera();
    return () => stopCamera();
  }, []);

  async function startCamera() {
    try {
      const stream = await navigator.mediaDevices.getUserMedia({
        video: true,
        audio: true,
      });
      videoRef.current.srcObject = stream;
      videoRef.current.play();
      setCameraReady(true);
    } catch (err) {
      setError("Camera access denied. Please allow camera permissions.");
      console.error("Camera error:", err);
    }
  }

  function stopCamera() {
    const stream = videoRef.current?.srcObject;
    if (stream) {
      stream.getTracks().forEach((track) => track.stop());
    }
  }

  // ─────────────────────────────────────────────
  // Start recording
  // ─────────────────────────────────────────────
  function startRecording() {
    const stream = videoRef.current.srcObject;
    chunksRef.current = [];

    const mediaRecorder = new MediaRecorder(stream, {
      mimeType: "video/webm",
    });

    mediaRecorder.ondataavailable = (e) => {
      if (e.data.size > 0) chunksRef.current.push(e.data);
    };

    mediaRecorder.onstop = () => {
      const blob = new Blob(chunksRef.current, { type: "video/webm" });
      const url = URL.createObjectURL(blob);
      if (onRecordingComplete) onRecordingComplete(blob, url);
    };

    mediaRecorderRef.current = mediaRecorder;
    mediaRecorder.start(1000);
    setRecording(true);
  }

  // ─────────────────────────────────────────────
  // Stop recording
  // ─────────────────────────────────────────────
  function stopRecording() {
    mediaRecorderRef.current?.stop();
    setRecording(false);
  }

  if (error) {
    return (
      <div style={styles.error}>
        <p>{error}</p>
      </div>
    );
  }

  return (
    <div style={styles.container}>
      {/* Live camera feed */}
      <video ref={videoRef} muted playsInline style={styles.video} />

      {/* Recording indicator */}
      {recording && (
        <div style={styles.recordingBadge}>🔴 Recording</div>
      )}

      {/* Controls */}
      <div style={styles.controls}>
        {!recording ? (
          <button
            onClick={startRecording}
            disabled={!cameraReady}
            style={styles.startBtn}
          >
            {cameraReady ? "Start Interview" : "Loading camera..."}
          </button>
        ) : (
          <button onClick={stopRecording} style={styles.stopBtn}>
            Stop Interview
          </button>
        )}
      </div>
    </div>
  );
}

const styles = {
  container: {
    position: "relative",
    width: "100%",
    maxWidth: "720px",
    margin: "0 auto",
    borderRadius: "12px",
    overflow: "hidden",
    background: "#000",
  },
  video: {
    width: "100%",
    display: "block",
    borderRadius: "12px",
  },
  recordingBadge: {
    position: "absolute",
    top: "12px",
    left: "12px",
    background: "rgba(0,0,0,0.6)",
    color: "white",
    padding: "4px 12px",
    borderRadius: "20px",
    fontSize: "14px",
    fontWeight: "bold",
  },
  controls: {
    position: "absolute",
    bottom: "16px",
    width: "100%",
    display: "flex",
    justifyContent: "center",
  },
  startBtn: {
    background: "#4CAF50",
    color: "white",
    border: "none",
    padding: "12px 32px",
    borderRadius: "8px",
    fontSize: "16px",
    cursor: "pointer",
    fontWeight: "bold",
  },
  stopBtn: {
    background: "#f44336",
    color: "white",
    border: "none",
    padding: "12px 32px",
    borderRadius: "8px",
    fontSize: "16px",
    cursor: "pointer",
    fontWeight: "bold",
  },
  error: {
    background: "#ffebee",
    color: "#c62828",
    padding: "20px",
    borderRadius: "12px",
    textAlign: "center",
  },
};