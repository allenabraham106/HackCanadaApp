import { useRef, useState, useEffect, forwardRef, useImperativeHandle } from "react";
import "./Camera.css";

const Camera = forwardRef(function Camera({ onRecordingComplete, onCameraReady, externalControls = false }, ref) {
  const videoRef = useRef(null);
  const mediaRecorderRef = useRef(null);
  const chunksRef = useRef([]);

  const [cameraReady, setCameraReady] = useState(false);
  const [recording, setRecording] = useState(false);
  const [error, setError] = useState(null);

  useEffect(() => {
    startCamera();
    return () => stopCamera();
  }, []);

  useEffect(() => {
    function handleVisibilityChange() {
      if (document.visibilityState === "hidden" && mediaRecorderRef.current?.state === "recording") {
        stopRecording();
      }
    }
    document.addEventListener("visibilitychange", handleVisibilityChange);
    return () => document.removeEventListener("visibilitychange", handleVisibilityChange);
  }, []);

  async function startCamera() {
    try {
      const stream = await navigator.mediaDevices.getUserMedia({
        video: { width: { ideal: 1280 }, height: { ideal: 720 } },
        audio: true,
      });
      const video = videoRef.current;
      if (video) {
        video.srcObject = stream;
        video.play().catch(() => {});
      }
      setCameraReady(true);
      onCameraReady?.();
    } catch (err) {
      setError("Camera access denied. Please allow camera permissions.");
      console.error("Camera error:", err);
    }
  }

  function stopCamera() {
    const stream = videoRef.current?.srcObject;
    if (stream) {
      stream.getTracks().forEach((track) => track.stop());
      if (videoRef.current) videoRef.current.srcObject = null;
    }
  }

  function startRecording() {
    const stream = videoRef.current?.srcObject;
    if (!stream) return;
    chunksRef.current = [];

    const mediaRecorder = new MediaRecorder(stream, {
      mimeType: "video/webm",
      videoBitsPerSecond: 2500000,
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

  function stopRecording() {
    const mr = mediaRecorderRef.current;
    if (mr?.state === "recording") {
      mr.stop();
      setRecording(false);
    }
  }

  useImperativeHandle(ref, () => ({
    startRecording,
    stopRecording,
    isRecording: () => mediaRecorderRef.current?.state === "recording",
    isReady: cameraReady,
  }), [cameraReady]);

  if (error) {
    return (
      <div className="camera-block__error">
        <p>{error}</p>
      </div>
    );
  }

  return (
    <div className="camera-block">
      <video
        ref={videoRef}
        muted
        playsInline
        className="camera-block__video"
      />

      {recording && (
        <div className="camera-block__recording-badge">
          <span className="camera-block__recording-dot" />
          Recording
        </div>
      )}

      {!externalControls && (
        <div className="camera-block__controls">
          {!recording ? (
            <button
              type="button"
              className="camera-block__btn camera-block__btn--start"
              onClick={startRecording}
              disabled={!cameraReady}
            >
              {cameraReady ? "Start interview" : "Loading camera…"}
            </button>
          ) : (
            <button
              type="button"
              className="camera-block__btn camera-block__btn--stop"
              onClick={stopRecording}
            >
              Stop interview
            </button>
          )}
        </div>
      )}
    </div>
  );
});

export default Camera;
