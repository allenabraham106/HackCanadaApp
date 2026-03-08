import { useRef, useState, useEffect, forwardRef, useImperativeHandle } from "react";
import "./Camera.css";

const Camera = forwardRef(function Camera({ onRecordingComplete, onCameraReady, externalControls = false }, ref) {
  const videoRef = useRef(null);
  const streamRef = useRef(null);
  const mediaRecorderRef = useRef(null);
  const chunksRef = useRef([]);
  const stopResolveRef = useRef(null);
  const mountedRef = useRef(false);

  const [cameraReady, setCameraReady] = useState(false);
  const [recording, setRecording] = useState(false);
  const [error, setError] = useState(null);

  function stopStream(stream) {
    stream?.getTracks?.().forEach((track) => track.stop());
  }

  async function startCamera() {
    setError(null);
    try {
      const stream = await navigator.mediaDevices.getUserMedia({
        video: { width: { ideal: 640 }, height: { ideal: 360 }, frameRate: { ideal: 8, max: 10 } },
        audio: true,
      });

      if (!mountedRef.current) {
        stopStream(stream);
        return;
      }

      if (streamRef.current && streamRef.current !== stream) {
        stopStream(streamRef.current);
      }

      streamRef.current = stream;
      const video = videoRef.current;
      if (video) {
        video.srcObject = stream;
        video.play().catch(() => {});
      }
      setCameraReady(true);
      onCameraReady?.();
    } catch (err) {
      if (mountedRef.current) {
        setCameraReady(false);
        setError("Camera access denied. Please allow camera permissions.");
      }
      cleanupCameraSession();
      console.error("Camera error:", err);
    }
  }

  function cleanupCameraSession() {
    const mr = mediaRecorderRef.current;
    if (mr && mr.state !== "inactive") {
      mr.ondataavailable = null;
      mr.onstop = null;
      try {
        mr.stop();
      } catch {
        // no-op: recorder may already be stopping
      }
    }

    mediaRecorderRef.current = null;
    chunksRef.current = [];
    if (stopResolveRef.current) {
      stopResolveRef.current({ blob: null, url: null });
      stopResolveRef.current = null;
    }

    stopStream(streamRef.current);
    streamRef.current = null;

    if (videoRef.current?.srcObject) {
      videoRef.current.srcObject = null;
    }

    if (mountedRef.current) {
      setCameraReady(false);
      setRecording(false);
    }
  }

  useEffect(() => {
    mountedRef.current = true;
    const frameId = window.requestAnimationFrame(() => {
      startCamera();
    });
    return () => {
      window.cancelAnimationFrame(frameId);
      mountedRef.current = false;
      cleanupCameraSession();
    };
  }, []);

  useEffect(() => {
    function handleVisibilityChange() {
      if (document.visibilityState === "hidden") {
        cleanupCameraSession();
      } else if (document.visibilityState === "visible" && !streamRef.current && mountedRef.current) {
        startCamera();
      }
    }

    function handlePageLeave() {
      cleanupCameraSession();
    }

    document.addEventListener("visibilitychange", handleVisibilityChange);
    window.addEventListener("pagehide", handlePageLeave);
    window.addEventListener("beforeunload", handlePageLeave);

    return () => {
      document.removeEventListener("visibilitychange", handleVisibilityChange);
      window.removeEventListener("pagehide", handlePageLeave);
      window.removeEventListener("beforeunload", handlePageLeave);
    };
  }, []);

  function startRecording() {
    if (mediaRecorderRef.current?.state === "recording") return;

    const stream = videoRef.current?.srcObject;
    if (!stream) return;
    chunksRef.current = [];

    let mediaRecorder;
    try {
      mediaRecorder = new MediaRecorder(stream, {
        mimeType: "video/webm",
        videoBitsPerSecond: 350000,
        audioBitsPerSecond: 64000,
      });
    } catch (err) {
      setError("Recording could not start. Please retry camera permissions.");
      cleanupCameraSession();
      console.error("Recorder setup error:", err);
      return;
    }

    mediaRecorder.ondataavailable = (e) => {
      if (e.data.size > 0) chunksRef.current.push(e.data);
    };
    mediaRecorder.onerror = () => {
      cleanupCameraSession();
    };
    mediaRecorder.onstop = () => {
      const flushAndDeliver = () => {
        const blob = new Blob(chunksRef.current, { type: "video/webm" });
        const url = URL.createObjectURL(blob);
        if (onRecordingComplete) onRecordingComplete(blob, url);
        if (stopResolveRef.current) {
          stopResolveRef.current({ blob, url });
          stopResolveRef.current = null;
        }
        if (mountedRef.current) {
          setRecording(false);
        }
        mediaRecorderRef.current = null;
      };
      setTimeout(flushAndDeliver, 150);
    };

    mediaRecorderRef.current = mediaRecorder;
    mediaRecorder.start(1000);
    setRecording(true);
  }

  function stopRecording() {
    const mr = mediaRecorderRef.current;
    if (mr?.state === "recording") {
      const promise = new Promise((resolve) => {
        stopResolveRef.current = resolve;
      });
      mr.stop();
      return promise;
    }
    return Promise.resolve({ blob: null, url: null });
  }

  useImperativeHandle(ref, () => ({
    startRecording,
    stopRecording,
    cleanup: cleanupCameraSession,
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