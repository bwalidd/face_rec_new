import React, { useEffect, useRef, useState } from "react";
import { Progress } from "@nextui-org/react";
import adapter from "webrtc-adapter";
import Janus from "janus-gateway";

// Initialize adapter globally
if (typeof window !== 'undefined') {
  window.adapter = adapter;
}

// TURN server configuration
const iceServers = [
  {
    urls: "turn:34.60.157.241:3478",
    username: "admin",
    credential: "admin",
    credentialType: "password"
  },
  // Fallback to STUN
  {
    urls: "stun:34.60.157.241:3478"
  }
];

const StreamWebRtc = ({ id }) => {
  const videoRef = useRef(null);
  let janusInstance = null;
  let streamingPlugin = null;
  const [loading, setLoading] = useState(true);
  const [hidden, setHidden] = useState("hidden");
  const [error, setError] = useState(false);
  const [loadingStatus, setLoadingStatus] = useState("Initializing...");
  const [progress, setProgress] = useState(0);

  // Function to update progress based on loading status
  const updateProgress = (status) => {
    setLoadingStatus(status);
    switch (status) {
      case "Initializing Janus...":
        setProgress(10);
        break;
      case "Connecting to Janus server...":
        setProgress(30);
        break;
      case "Attaching to streaming plugin...":
        setProgress(50);
        break;
      case "Requesting stream...":
        setProgress(60);
        break;
      case "Stream is starting...":
        setProgress(70);
        break;
      case "Stream started, waiting for video...":
        setProgress(80);
        break;
      case "Creating WebRTC answer...":
        setProgress(90);
        break;
      case "Video playing":
        setProgress(100);
        break;
      default:
        // Keep current progress
        break;
    }
  };

  useEffect(() => {
    const initJanus = () => {
      updateProgress("Initializing Janus...");
      console.log("Initializing Janus...");

      if (typeof Janus === 'undefined') {
        console.error("Janus not loaded");
        setError(true);
        setLoading(false);
        return;
      }

      Janus.init({
        debug: false,
        callback: () => {
          updateProgress("Connecting to Janus server...");
          console.log("Connecting to Janus server...");
          janusInstance = new Janus({
            server: `http://${import.meta.env.VITE_APP_IP}:8088/janus`,
            iceServers: iceServers,
            ipv6: false,
            withCredentials: false,
            max_poll_events: 10,
            success: () => {
              updateProgress("Attaching to streaming plugin...");
              console.log("Attaching to streaming plugin...");
              janusInstance.attach({
                plugin: "janus.plugin.streaming",
                success: (pluginHandle) => {
                  streamingPlugin = pluginHandle;
                  updateProgress("Requesting stream...");
                  console.log("Requesting stream...");
                  const body = { request: "watch", id: parseInt(id.toString()) };
                  streamingPlugin.send({ message: body });
                },
                error: (error) => {
                  console.error("Error attaching plugin:", error);
                  setError(true);
                  setLoading(false);
                },
                onmessage: (msg, jsep) => {
                  console.log("Received message:", msg);
                  try {
                    if (msg.result?.status === "starting") {
                      updateProgress("Stream is starting...");
                      console.log("Stream is starting...");
                    } else if (msg.result?.status === "started") {
                      updateProgress("Stream started, waiting for video...");
                      console.log("Stream started, waiting for video...");
                    }
                  } catch (e) {
                    console.log("Error in onmessage", e);
                    setHidden("hidden");
                    setLoading(false);
                    setError(true);
                  }
                  if (jsep !== undefined && jsep !== null) {
                    updateProgress("Creating WebRTC answer...");
                    console.log("Creating WebRTC answer...");
                    streamingPlugin.createAnswer({
                      jsep: jsep,
                      media: {
                        audioSend: false,
                        videoSend: false,
                        audioRecv: true,
                        videoRecv: true
                      },
                      iceRestart: true,
                      success: (jsep) => {
                        updateProgress("Starting stream...");
                        console.log("Starting stream...");
                        const body = { request: "start" };
                        streamingPlugin.send({ message: body, jsep: jsep });
                      },
                      error: (error) => {
                        console.error("Error creating WebRTC answer:", error);
                      },
                    });
                  }
                },
                onremotestream: (stream) => {
                  console.log("Received remote stream:", stream);
                  if (videoRef.current) {
                    videoRef.current.srcObject = stream;
                    videoRef.current
                      .play()
                      .then(() => {
                        setLoading(false);
                        updateProgress("Video playing");
                        console.log("Video playing");
                      })
                      .catch((e) => console.error("Error playing video:", e));
                  }
                },
                onicecandidate: (candidate) => {
                  if (candidate) {
                    console.log("Received ICE candidate:", candidate);
                  }
                },
                onremotetrack: (track, mid, on) => {
                  console.log("Remote track received:", track, "MID:", mid, "ON:", on);
                  if (videoRef.current) {
                    let stream = videoRef.current.srcObject || new MediaStream();
                    if (on) {
                      stream.addTrack(track);
                      videoRef.current.srcObject = stream;
                    } else {
                      stream.removeTrack(track);
                    }
                    videoRef.current.play()
                      .then(() => {
                        setLoading(false);
                        updateProgress("Video playing");
                        console.log("Video playing");
                      })
                      .catch((e) => console.error("Error playing video:", e));
                  }
                },
                oncleanup: () => {
                  console.log("Janus cleanup");
                  setHidden("");
                },
                onlocaltrack: (track) => {
                  console.log("Local track:", track);
                  setHidden("hidden");
                  setLoading(false);
                  setError(true);
                },
              });
            },
            error: (error) => {
              console.error("Janus error:", error);
              setHidden("hidden");
              setLoading(false);
              setError(true);
            },
            destroyed: () => {
              console.log("Janus session destroyed");
              setHidden("hidden");
              setLoading(false);
              setError(true);
            },
          });
        },
      });
    };

    initJanus();

    if (videoRef.current) {
      videoRef.current.addEventListener("loadedmetadata", () => {
        console.log("Video metadata loaded:", videoRef.current.videoWidth, videoRef.current.videoHeight);
        setHidden("");
        setLoading(false);
      });
    }

    return () => {
      if (streamingPlugin) {
        const body = { request: "stop" };
        streamingPlugin.send({ message: body });
        streamingPlugin.detach();
        setHidden("hidden");
        setLoading(false);
        setError(true);
        videoRef.current = null;
      }

      if (janusInstance) {
        janusInstance.destroy();
      }
    };
  }, [id]);

  return (
    <>
      <div className={`${hidden} flex gap-4 w-full min-h-72 min-w-72 items-center justify-center`}>
        <video
          ref={videoRef}
          autoPlay
          playsInline
          controls
          muted
          className="w-full h-full object-contain"
          aria-label="Live Stream Video"
        />
      </div>
      {loading && (
        <div className="flex flex-col gap-4 w-full min-h-72 min-w-72 items-center justify-center p-4">
          <Progress
            value={progress}
            color="primary"
            size="md"
            className="w-full max-w-md"
            showValueLabel={true}

          />
          <p className="text-sm text-gray-500">{loadingStatus}</p>
        </div>
      )}
      {error && (
        <div className="flex gap-4 w-full min-h-72 min-w-72 items-center justify-center">
          <h1 className="text-red-500">Error in streaming</h1>
        </div>
      )}
    </>
  );
};

export default StreamWebRtc;