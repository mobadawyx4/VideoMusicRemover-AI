import React, { useEffect, useRef, useState } from "react";
import {
  AlertTriangle,
  AudioWaveform,
  CheckCircle2,
  Clock,
  Download,
  FileAudio,
  Film,
  HardDrive,
  Layers,
  Loader2,
  Maximize2,
  Mic,
  Music2,
  RefreshCw,
  Shield,
  Sliders,
  Sparkles,
  Trash2,
  Trees,
  Video,
  Volume2,
  VolumeX,
  Wand2,
} from "lucide-react";
import Navbar from "./components/Navbar";
import UploadZone from "./components/UploadZone";
import ProgressPipeline from "./components/ProgressPipeline";
import AudioComparisonStudio from "./components/AudioComparisonStudio";
import {
  createDemoVideoJob,
  deleteJob,
  fetchHealth,
  fetchJobStatus,
  remixJobAudio,
  resolveMediaUrl,
  startVideoProcessing,
  uploadVideoFile,
} from "./lib/api";
import { formatBytes, formatDuration } from "./lib/formatters";

const ACTIVE_POLL_STATES = new Set([
  "queued",
  "extracting_audio",
  "separating_stems",
  "reconstructing_audio",
  "rendering_video",
]);

export default function App() {
  const [health, setHealth] = useState(null);
  const [job, setJob] = useState(null);
  const [jobToken, setJobToken] = useState(null);

  const [isUploading, setIsUploading] = useState(false);
  const [uploadProgress, setUploadProgress] = useState(0);
  const [isStartingProcess, setIsStartingProcess] = useState(false);
  const [isRemixing, setIsRemixing] = useState(false);
  const [errorMsg, setErrorMsg] = useState(null);

  // User-adjustable AI controls
  const [musicRemovalStrength, setMusicRemovalStrength] = useState(100); // 0..100%
  const [speechGain, setSpeechGain] = useState(100); // 0..200%
  const [effectsGain, setEffectsGain] = useState(100); // 0..200%
  const [separationMode, setSeparationMode] = useState("balanced");

  // Video player toggle: "original" | "processed"
  const [videoPreviewMode, setVideoPreviewMode] = useState("original");
  const videoRef = useRef(null);

  // Fetch system health on mount
  useEffect(() => {
    let mounted = true;
    fetchHealth()
      .then((data) => {
        if (mounted) setHealth(data);
      })
      .catch(() => {});
    return () => {
      mounted = false;
    };
  }, []);

  // Poll job status while processing is active
  useEffect(() => {
    if (!job?.job_id || !ACTIVE_POLL_STATES.has(job.status)) {
      return undefined;
    }

    const interval = setInterval(async () => {
      try {
        const updated = await fetchJobStatus(job.job_id, jobToken);
        setJob((prev) => ({
          ...updated,
          access_token: updated.access_token || prev?.access_token || jobToken,
        }));
        if (updated.status === "completed") {
          setVideoPreviewMode("processed");
        } else if (updated.status === "failed" && updated.error) {
          setErrorMsg(updated.error);
        }
      } catch (err) {
        // Ignore transient network hiccups during polling
      }
    }, 1000);

    return () => clearInterval(interval);
  }, [job?.job_id, job?.status, jobToken]);

  const handleSelectFile = async (file) => {
    if (!file) return;
    setErrorMsg(null);
    setIsUploading(true);
    setUploadProgress(0);
    try {
      const createdJob = await uploadVideoFile(file, (pct) =>
        setUploadProgress(pct)
      );
      setJob(createdJob);
      setJobToken(createdJob.access_token);
      setVideoPreviewMode("original");
      setMusicRemovalStrength(
        Math.round((createdJob.options?.music_removal_strength ?? 1.0) * 100)
      );
      setSpeechGain(Math.round((createdJob.options?.speech_gain ?? 1.0) * 100));
      setEffectsGain(
        Math.round((createdJob.options?.effects_gain ?? 1.0) * 100)
      );
    } catch (err) {
      setErrorMsg(err.message || "Failed to upload video file.");
    } finally {
      setIsUploading(false);
    }
  };

  const handleLoadDemo = async () => {
    setErrorMsg(null);
    setIsUploading(true);
    setUploadProgress(45);
    try {
      const demoJob = await createDemoVideoJob();
      setUploadProgress(100);
      setJob(demoJob);
      setJobToken(demoJob.access_token);
      setVideoPreviewMode("original");
    } catch (err) {
      setErrorMsg(err.message || "Could not create sample video.");
    } finally {
      setIsUploading(false);
    }
  };

  const handleStartRemoveMusic = async () => {
    if (!job?.job_id) return;
    setErrorMsg(null);
    setIsStartingProcess(true);
    try {
      const updated = await startVideoProcessing(job.job_id, jobToken, {
        music_removal_strength: musicRemovalStrength / 100.0,
        speech_gain: speechGain / 100.0,
        effects_gain: effectsGain / 100.0,
        separation_mode: separationMode,
      });
      setJob((prev) => ({
        ...updated,
        access_token: updated.access_token || prev?.access_token || jobToken,
      }));
    } catch (err) {
      setErrorMsg(err.message || "Could not start AI music removal.");
    } finally {
      setIsStartingProcess(false);
    }
  };

  const handleInstantRemix = async () => {
    if (!job?.job_id || job.status !== "completed") return;
    setErrorMsg(null);
    setIsRemixing(true);
    try {
      const updated = await remixJobAudio(job.job_id, jobToken, {
        music_removal_strength: musicRemovalStrength / 100.0,
        speech_gain: speechGain / 100.0,
        effects_gain: effectsGain / 100.0,
      });
      setJob((prev) => ({
        ...updated,
        access_token: updated.access_token || prev?.access_token || jobToken,
      }));
      setVideoPreviewMode("processed");
    } catch (err) {
      setErrorMsg(err.message || "Failed to remix audio stems.");
    } finally {
      setIsRemixing(false);
    }
  };

  const handleResetOrDelete = async () => {
    if (job?.job_id) {
      try {
        await deleteJob(job.job_id, jobToken);
      } catch (_) {}
    }
    setJob(null);
    setJobToken(null);
    setErrorMsg(null);
    setVideoPreviewMode("original");
  };

  const switchVideoPreviewMode = (mode) => {
    if (mode === videoPreviewMode) return;
    const vid = videoRef.current;
    const savedTime = vid ? vid.currentTime : 0;
    const wasPaused = vid ? vid.paused : true;
    setVideoPreviewMode(mode);
    setTimeout(() => {
      if (videoRef.current) {
        videoRef.current.currentTime = savedTime;
        if (!wasPaused) {
          videoRef.current.play().catch(() => {});
        }
      }
    }, 50);
  };

  const isProcessing = job && ACTIVE_POLL_STATES.has(job.status);
  const isCompleted = job?.status === "completed";
  const meta = job?.metadata;

  const activeVideoUrl =
    videoPreviewMode === "processed" && job?.processed_video_url
      ? resolveMediaUrl(job.processed_video_url, job.updated_at)
      : resolveMediaUrl(job?.original_video_url, job?.created_at);

  const downloadProcessedVideoUrl = job?.processed_video_url
    ? `${resolveMediaUrl(job.processed_video_url, job.updated_at)}&download=true`
    : null;

  const downloadOriginalVideoUrl = job?.original_video_url
    ? `${resolveMediaUrl(job.original_video_url)}&download=true`
    : null;

  return (
    <div id="top" className="min-h-screen bg-grid-pattern flex flex-col">
      <Navbar health={health} />

      <main className="mx-auto w-full max-w-7xl flex-1 px-4 py-8 sm:px-6 lg:px-8">
        {/* Hero Header */}
        <section className="mx-auto max-w-3xl text-center mb-8 sm:mb-10">
          <div className="mb-4 inline-flex items-center gap-2 rounded-full border border-purple-500/30 bg-purple-500/10 px-3.5 py-1 text-xs font-semibold text-purple-300 shadow-sm">
            <Sparkles className="h-3.5 w-3.5 text-cyan-400" />
            <span>Powered by TIGER-DnR 3-Stem Neural Audio Separation</span>
          </div>

          <h1 className="text-3xl font-extrabold tracking-tight text-white sm:text-5xl lg:text-[52px] lg:leading-[1.12]">
            Remove Background Music from{" "}
            <span className="bg-gradient-to-r from-purple-400 via-violet-400 to-cyan-400 bg-clip-text text-transparent">
              Any Video
            </span>
          </h1>

          <p className="mt-4 text-sm sm:text-base text-slate-300 leading-relaxed">
            VideoMusicRemover AI uses deep time-frequency source separation to split
            your video&apos;s soundtrack into{" "}
            <strong className="text-white font-semibold">Human Speech</strong>,{" "}
            <strong className="text-white font-semibold">
              Natural Environmental Sounds
            </strong>
            , and{" "}
            <strong className="text-white font-semibold">
              Background Music
            </strong>
            —eliminating music while keeping dialogue, footsteps, and room
            ambience crystal clear.
          </p>
        </section>

        {/* Error Notification Banner */}
        {errorMsg && (
          <div
            role="alert"
            className="mb-6 flex items-start justify-between gap-4 rounded-2xl border border-rose-500/40 bg-rose-950/60 p-4 text-sm text-rose-200 shadow-lg"
          >
            <div className="flex items-start gap-3">
              <AlertTriangle className="mt-0.5 h-5 w-5 shrink-0 text-rose-400" />
              <div>
                <p className="font-semibold text-white">Processing Alert</p>
                <p className="mt-0.5 text-rose-200/90">{errorMsg}</p>
              </div>
            </div>
            <button
              type="button"
              onClick={() => setErrorMsg(null)}
              className="rounded-lg border border-rose-400/30 px-2.5 py-1 text-xs font-medium text-rose-200 hover:bg-rose-500/20"
            >
              Dismiss
            </button>
          </div>
        )}

        {/* Step 1: Upload Zone (shown when no job is loaded) */}
        {!job && (
          <UploadZone
            onSelectFile={handleSelectFile}
            onLoadDemo={handleLoadDemo}
            isUploading={isUploading}
            uploadProgress={uploadProgress}
            maxUploadMb={health?.max_upload_size_mb || 500}
          />
        )}

        {/* Active Job Workspace Dashboard */}
        {job && (
          <div className="space-y-6">
            {/* Top Workspace Bar */}
            <div className="flex flex-wrap items-center justify-between gap-3 rounded-2xl border border-white/10 bg-obsidian-900/80 px-5 py-3.5">
              <div className="flex items-center gap-3 min-w-0">
                <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-xl bg-purple-500/15 text-purple-300">
                  <Film className="h-5 w-5" />
                </div>
                <div className="min-w-0">
                  <p className="truncate text-sm font-bold text-white">
                    {meta?.filename || "Uploaded Video"}
                  </p>
                  <p className="font-mono text-[11px] text-slate-400">
                    Job ID: {job.job_id.slice(0, 8)}… • Status:{" "}
                    <span className=" uppercase text-cyan-300 font-semibold">
                      {job.status.replace(/_/g, " ")}
                    </span>
                  </p>
                </div>
              </div>

              <div className="flex items-center gap-2.5">
                <button
                  type="button"
                  onClick={handleResetOrDelete}
                  disabled={isProcessing}
                  className="inline-flex items-center gap-1.5 rounded-xl border border-white/15 bg-white/5 px-3.5 py-2 text-xs font-medium text-slate-300 transition hover:border-rose-500/40 hover:bg-rose-500/10 hover:text-rose-200 disabled:opacity-40"
                >
                  <Trash2 className="h-3.5 w-3.5" />
                  <span>Upload Another Video</span>
                </button>
              </div>
            </div>

            {/* Processing Progress Pipeline */}
            {(isProcessing || isCompleted) && (
              <ProgressPipeline
                status={job.status}
                progress={job.progress}
                stageMessage={job.stage_message}
              />
            )}

            {/* Main 2-Column Studio Grid: Left = Video Preview & Metadata, Right = AI Controls & Download */}
            <div className="grid grid-cols-1 gap-6 lg:grid-cols-12">
              {/* Left Column: Video Player & Technical Specs (7 cols) */}
              <div className="space-y-5 lg:col-span-7">
                <div className="overflow-hidden rounded-3xl border border-white/10 bg-obsidian-900/90 shadow-2xl">
                  {/* Video Mode Switcher Header */}
                  <div className="flex flex-wrap items-center justify-between gap-2 border-b border-white/10 px-5 py-3.5">
                    <div className="flex items-center gap-2">
                      <Video className="h-4 w-4 text-purple-400" />
                      <span className="text-sm font-bold text-white">
                        Video Preview
                      </span>
                    </div>

                    <div className="flex items-center gap-1.5 rounded-xl border border-white/10 bg-obsidian-950 p-1">
                      <button
                        type="button"
                        onClick={() => switchVideoPreviewMode("original")}
                        className={`inline-flex items-center gap-1.5 rounded-lg px-3 py-1 text-xs font-semibold transition ${
                          videoPreviewMode === "original"
                            ? "bg-purple-600 text-white shadow"
                            : "text-slate-400 hover:text-white"
                        }`}
                      >
                        <Volume2 className="h-3.5 w-3.5" />
                        <span>Original Video</span>
                      </button>

                      <button
                        type="button"
                        disabled={!isCompleted}
                        onClick={() => switchVideoPreviewMode("processed")}
                        className={`inline-flex items-center gap-1.5 rounded-lg px-3 py-1 text-xs font-semibold transition ${
                          videoPreviewMode === "processed"
                            ? "bg-gradient-to-r from-purple-600 to-cyan-500 text-white shadow"
                            : isCompleted
                            ? "text-cyan-300 hover:bg-white/5"
                            : "text-slate-600 cursor-not-allowed"
                        }`}
                      >
                        <Sparkles className="h-3.5 w-3.5" />
                        <span>Music Removed Video</span>
                      </button>
                    </div>
                  </div>

                  {/* HTML5 Video Player */}
                  <div className="relative bg-black aspect-video flex items-center justify-center">
                    {activeVideoUrl ? (
                      <video
                        ref={videoRef}
                        key={activeVideoUrl}
                        src={activeVideoUrl}
                        controls
                        playsInline
                        className="h-full w-full max-h-[460px] object-contain"
                      />
                    ) : (
                      <div className="text-sm text-slate-500">
                        Loading video stream...
                      </div>
                    )}

                    {/* Active Stream Badge Overlay */}
                    <div className="pointer-events-none absolute top-3 left-3">
                      <span
                        className={`inline-flex items-center gap-1.5 rounded-full px-3 py-1 text-[11px] font-bold backdrop-blur-md ${
                          videoPreviewMode === "processed"
                            ? "bg-cyan-500/80 text-obsidian-950"
                            : "bg-black/70 text-slate-200 border border-white/15"
                        }`}
                      >
                        {videoPreviewMode === "processed" ? (
                          <>
                            <Sparkles className="h-3 w-3" />
                            <span>AI Clean Audio Stream</span>
                          </>
                        ) : (
                          <>
                            <Volume2 className="h-3 w-3" />
                            <span>Original Audio Stream</span>
                          </>
                        )}
                      </span>
                    </div>
                  </div>

                  {/* Video Technical Metadata Bar */}
                  {meta && (
                    <div className="grid grid-cols-2 gap-2.5 border-t border-white/10 bg-obsidian-950/60 p-4 sm:grid-cols-4">
                      <div className="flex items-center gap-2.5 rounded-xl border border-white/5 bg-white/[0.02] px-3 py-2">
                        <Maximize2 className="h-4 w-4 text-purple-400 shrink-0" />
                        <div>
                          <p className="text-[10px] uppercase tracking-wider text-slate-400">
                            Resolution
                          </p>
                          <p className="font-mono text-xs font-bold text-white">
                            {meta.width}×{meta.height} ({meta.aspect_ratio})
                          </p>
                        </div>
                      </div>

                      <div className="flex items-center gap-2.5 rounded-xl border border-white/5 bg-white/[0.02] px-3 py-2">
                        <Clock className="h-4 w-4 text-cyan-400 shrink-0" />
                        <div>
                          <p className="text-[10px] uppercase tracking-wider text-slate-400">
                            Duration &amp; FPS
                          </p>
                          <p className="font-mono text-xs font-bold text-white">
                            {formatDuration(meta.duration_seconds)} • {meta.fps}{" "}
                            fps
                          </p>
                        </div>
                      </div>

                      <div className="flex items-center gap-2.5 rounded-xl border border-white/5 bg-white/[0.02] px-3 py-2">
                        <HardDrive className="h-4 w-4 text-emerald-400 shrink-0" />
                        <div>
                          <p className="text-[10px] uppercase tracking-wider text-slate-400">
                            File Size
                          </p>
                          <p className="font-mono text-xs font-bold text-white">
                            {formatBytes(meta.file_size_bytes)}
                          </p>
                        </div>
                      </div>

                      <div className="flex items-center gap-2.5 rounded-xl border border-white/5 bg-white/[0.02] px-3 py-2">
                        <Layers className="h-4 w-4 text-blue-400 shrink-0" />
                        <div>
                          <p className="text-[10px] uppercase tracking-wider text-slate-400">
                            Streams
                          </p>
                          <p className="font-mono text-xs font-bold text-white uppercase">
                            {meta.video_codec} / {meta.audio_codec || "pcm"}
                          </p>
                        </div>
                      </div>
                    </div>
                  )}
                </div>
              </div>

              {/* Right Column: AI Separation Controls & Download Panel (5 cols) */}
              <div className="space-y-5 lg:col-span-5">
                {/* AI Music Removal Controls Card */}
                <div className="rounded-3xl border border-white/10 bg-obsidian-900/90 p-5 sm:p-6 shadow-2xl">
                  <div className="flex items-center justify-between border-b border-white/10 pb-4">
                    <div className="flex items-center gap-2">
                      <Sliders className="h-5 w-5 text-purple-400" />
                      <h2 className="text-base font-bold text-white">
                        AI Separation &amp; Mix Controls
                      </h2>
                    </div>
                    <span className="rounded-md border border-cyan-500/30 bg-cyan-500/10 px-2 py-0.5 font-mono text-[11px] text-cyan-300">
                      TIGER-DnR
                    </span>
                  </div>

                  <div className="mt-5 space-y-5">
                    {/* Music Removal Strength Slider */}
                    <div>
                      <div className="mb-2 flex items-center justify-between text-xs">
                        <span className="flex items-center gap-1.5 font-semibold text-white">
                          <VolumeX className="h-4 w-4 text-rose-400" />
                          <span>Music Removal Strength</span>
                        </span>
                        <span className="rounded-md bg-purple-500/20 px-2 py-0.5 font-mono font-bold text-purple-300">
                          {musicRemovalStrength}%
                        </span>
                      </div>
                      <input
                        type="range"
                        min="0"
                        max="100"
                        step="5"
                        value={musicRemovalStrength}
                        onChange={(e) =>
                          setMusicRemovalStrength(Number(e.target.value))
                        }
                        disabled={isProcessing}
                        className="st-slider w-full"
                        aria-label="Music Removal Strength"
                      />
                      <div className="mt-1 flex justify-between text-[11px] text-slate-400">
                        <span>0% (Keep Music)</span>
                        <span>50% (Duck Music)</span>
                        <span>100% (Full Removal)</span>
                      </div>
                    </div>

                    {/* Speech Preservation / Boost Slider */}
                    <div>
                      <div className="mb-2 flex items-center justify-between text-xs">
                        <span className="flex items-center gap-1.5 font-semibold text-white">
                          <Mic className="h-4 w-4 text-emerald-400" />
                          <span>Human Speech &amp; Dialogue Level</span>
                        </span>
                        <span className="rounded-md bg-emerald-500/20 px-2 py-0.5 font-mono font-bold text-emerald-300">
                          {speechGain}%
                        </span>
                      </div>
                      <input
                        type="range"
                        min="0"
                        max="200"
                        step="5"
                        value={speechGain}
                        onChange={(e) => setSpeechGain(Number(e.target.value))}
                        disabled={isProcessing}
                        className="st-slider w-full"
                        aria-label="Human Speech Level"
                      />
                    </div>

                    {/* Environmental Sounds Preservation Slider */}
                    <div>
                      <div className="mb-2 flex items-center justify-between text-xs">
                        <span className="flex items-center gap-1.5 font-semibold text-white">
                          <Trees className="h-4 w-4 text-cyan-400" />
                          <span>Environmental Sounds &amp; SFX Level</span>
                        </span>
                        <span className="rounded-md bg-cyan-500/20 px-2 py-0.5 font-mono font-bold text-cyan-300">
                          {effectsGain}%
                        </span>
                      </div>
                      <input
                        type="range"
                        min="0"
                        max="200"
                        step="5"
                        value={effectsGain}
                        onChange={(e) => setEffectsGain(Number(e.target.value))}
                        disabled={isProcessing}
                        className="st-slider w-full"
                        aria-label="Environmental Sounds Level"
                      />
                    </div>

                    {/* AI Quality Mode Selector */}
                    <div>
                      <label className="mb-2 block text-xs font-semibold text-slate-300">
                        Neural Separation Precision Mode
                      </label>
                      <div className="grid grid-cols-3 gap-2">
                        {[
                          {
                            id: "fast",
                            title: "Fast",
                            sub: "Single-pass",
                          },
                          {
                            id: "balanced",
                            title: "Balanced",
                            sub: "Overlap-add",
                          },
                          {
                            id: "high_quality",
                            title: "High Quality",
                            sub: "3-Model Ensemble",
                          },
                        ].map((m) => (
                          <button
                            key={m.id}
                            type="button"
                            disabled={isProcessing}
                            onClick={() => setSeparationMode(m.id)}
                            className={`rounded-xl border p-2.5 text-left transition ${
                              separationMode === m.id
                                ? "border-purple-400 bg-purple-500/15 text-white shadow-sm"
                                : "border-white/10 bg-white/[0.02] text-slate-400 hover:border-white/20 hover:text-slate-200"
                            }`}
                          >
                            <p className="text-xs font-bold">{m.title}</p>
                            <p className="text-[10px] opacity-75">{m.sub}</p>
                          </button>
                        ))}
                      </div>
                    </div>

                    {/* Primary CTA Button: "Remove Music" + Instant Remix */}
                    <div className="pt-2 space-y-2.5">
                      <button
                        type="button"
                        onClick={handleStartRemoveMusic}
                        disabled={isProcessing || isStartingProcess}
                        className="w-full flex items-center justify-center gap-2.5 rounded-2xl bg-gradient-to-r from-purple-600 via-violet-600 to-cyan-500 px-6 py-4 text-base font-extrabold text-white shadow-xl shadow-purple-600/30 transition hover:brightness-110 active:scale-[0.99] disabled:opacity-50 disabled:cursor-not-allowed"
                      >
                        {isProcessing || isStartingProcess ? (
                          <>
                            <Loader2 className="h-5 w-5 animate-spin" />
                            <span>Removing Background Music...</span>
                          </>
                        ) : (
                          <>
                            <Wand2 className="h-5 w-5" />
                            <span>Remove Music</span>
                          </>
                        )}
                      </button>

                      {isCompleted && (
                        <button
                          type="button"
                          onClick={handleInstantRemix}
                          disabled={isRemixing}
                          className="w-full flex items-center justify-center gap-2 rounded-xl border border-cyan-400/40 bg-cyan-500/10 px-4 py-2.5 text-xs font-bold text-cyan-200 transition hover:bg-cyan-500/20 disabled:opacity-50"
                        >
                          {isRemixing ? (
                            <>
                              <Loader2 className="h-4 w-4 animate-spin" />
                              <span>Updating Audio Mix &amp; Video...</span>
                            </>
                          ) : (
                            <>
                              <RefreshCw className="h-3.5 w-3.5" />
                              <span>
                                Apply Instant Stem Remix (No Re-Inference)
                              </span>
                            </>
                          )}
                        </button>
                      )}
                    </div>
                  </div>
                </div>

                {/* Download Panel (Shown when completed) */}
                {isCompleted && (
                  <div className="rounded-3xl border border-emerald-500/30 bg-gradient-to-b from-emerald-950/30 via-obsidian-900 to-obsidian-900 p-5 sm:p-6 shadow-2xl">
                    <div className="flex items-center gap-2.5">
                      <CheckCircle2 className="h-5 w-5 text-emerald-400" />
                      <h3 className="text-base font-bold text-white">
                        Ready to Download
                      </h3>
                    </div>
                    <p className="mt-1 text-xs text-slate-300">
                      Original resolution ({meta?.width}×{meta?.height}), frame
                      rate ({meta?.fps} fps), and aspect ratio (
                      {meta?.aspect_ratio}) preserved.
                    </p>

                    <div className="mt-4 space-y-2.5">
                      <a
                        href={downloadProcessedVideoUrl}
                        download
                        className="w-full flex items-center justify-center gap-2.5 rounded-2xl bg-gradient-to-r from-emerald-500 via-teal-500 to-cyan-500 px-5 py-3.5 text-sm font-extrabold text-obsidian-950 shadow-lg shadow-emerald-500/25 transition hover:brightness-110"
                      >
                        <Download className="h-4 w-4 stroke-[2.5]" />
                        <span>Download Processed Video (.MP4)</span>
                      </a>

                      <a
                        href={downloadOriginalVideoUrl}
                        download
                        className="w-full flex items-center justify-center gap-2 rounded-xl border border-white/15 bg-white/5 px-4 py-2.5 text-xs font-semibold text-slate-200 transition hover:bg-white/10"
                      >
                        <Film className="h-3.5 w-3.5 text-slate-400" />
                        <span>Download Original Video</span>
                      </a>
                    </div>

                    {/* Individual Stem WAV Downloads */}
                    <div className="mt-4 border-t border-white/10 pt-4">
                      <p className="mb-2.5 text-[11px] font-semibold uppercase tracking-wider text-slate-400">
                        Export Individual Audio Tracks (.WAV)
                      </p>
                      <div className="grid grid-cols-2 gap-2">
                        <a
                          href={`${resolveMediaUrl(
                            job.processed_audio_url,
                            job.updated_at
                          )}&download=true`}
                          download
                          className="flex items-center gap-1.5 rounded-lg border border-white/10 bg-white/[0.03] px-3 py-2 text-xs text-cyan-300 hover:bg-white/10"
                        >
                          <FileAudio className="h-3.5 w-3.5 shrink-0" />
                          <span className="truncate">Clean Audio Mix</span>
                        </a>
                        <a
                          href={`${resolveMediaUrl(
                            job.speech_stem_url
                          )}&download=true`}
                          download
                          className="flex items-center gap-1.5 rounded-lg border border-white/10 bg-white/[0.03] px-3 py-2 text-xs text-emerald-300 hover:bg-white/10"
                        >
                          <Mic className="h-3.5 w-3.5 shrink-0" />
                          <span className="truncate">Speech Only</span>
                        </a>
                        <a
                          href={`${resolveMediaUrl(
                            job.effects_stem_url
                          )}&download=true`}
                          download
                          className="flex items-center gap-1.5 rounded-lg border border-white/10 bg-white/[0.03] px-3 py-2 text-xs text-blue-300 hover:bg-white/10"
                        >
                          <Trees className="h-3.5 w-3.5 shrink-0" />
                          <span className="truncate">Ambience / SFX</span>
                        </a>
                        <a
                          href={`${resolveMediaUrl(
                            job.music_stem_url
                          )}&download=true`}
                          download
                          className="flex items-center gap-1.5 rounded-lg border border-white/10 bg-white/[0.03] px-3 py-2 text-xs text-rose-300 hover:bg-white/10"
                        >
                          <Music2 className="h-3.5 w-3.5 shrink-0" />
                          <span className="truncate">Removed Music</span>
                        </a>
                      </div>
                    </div>
                  </div>
                )}
              </div>
            </div>

            {/* Before & After Audio Comparison Studio (Shown once completed) */}
            {isCompleted && <AudioComparisonStudio job={job} />}
          </div>
        )}

        {/* Feature & Architecture Highlights Section */}
        <section className="mt-14 border-t border-white/10 pt-10">
          <div className="grid grid-cols-1 gap-5 sm:grid-cols-3">
            <div className="rounded-2xl border border-white/10 bg-obsidian-900/60 p-5">
              <div className="mb-3 flex h-10 w-10 items-center justify-center rounded-xl bg-purple-500/15 text-purple-300">
                <AudioWaveform className="h-5 w-5" />
              </div>
              <h3 className="text-sm font-bold text-white">
                3-Stem Cinematic Separation (DnR)
              </h3>
              <p className="mt-1.5 text-xs leading-relaxed text-slate-400">
                Unlike standard 2-stem vocal splitters that wipe out footsteps,
                applause, and room tone, TIGER-DnR explicitly separates{" "}
                <span className="text-slate-200">Speech</span>,{" "}
                <span className="text-slate-200">Sound Effects</span>, and{" "}
                <span className="text-slate-200">Music</span>.
              </p>
            </div>

            <div className="rounded-2xl border border-white/10 bg-obsidian-900/60 p-5">
              <div className="mb-3 flex h-10 w-10 items-center justify-center rounded-xl bg-cyan-500/15 text-cyan-300">
                <Film className="h-5 w-5" />
              </div>
              <h3 className="text-sm font-bold text-white">
                Lossless Video Stream Copy
              </h3>
              <p className="mt-1.5 text-xs leading-relaxed text-slate-400">
                FFmpeg remuxes the reconstructed audio directly onto your
                original video stream (`-c:v copy`), preserving 100% of your
                original resolution, frame rate, aspect ratio, and visual
                quality.
              </p>
            </div>

            <div className="rounded-2xl border border-white/10 bg-obsidian-900/60 p-5">
              <div className="mb-3 flex h-10 w-10 items-center justify-center rounded-xl bg-emerald-500/15 text-emerald-300">
                <Shield className="h-5 w-5" />
              </div>
              <h3 className="text-sm font-bold text-white">
                Isolated Jobs &amp; Auto-Cleanup
              </h3>
              <p className="mt-1.5 text-xs leading-relaxed text-slate-400">
                Each upload runs in a token-protected UUID workspace with
                chunked file streaming and automatic TTL cleanup of temporary
                files.
              </p>
            </div>
          </div>
        </section>
      </main>

      <footer className="mt-12 border-t border-white/10 bg-obsidian-950/90 py-6 text-center text-xs text-slate-500">
        <div className="mx-auto max-w-7xl px-4 flex flex-col sm:flex-row items-center justify-between gap-2">
          <p className="font-semibold text-slate-400">
            VideoMusicRemover AI — Production Neural Video Music Remover
          </p>
          <p>
            Powered by FastAPI • PyTorch • TIGER-DnR • FFmpeg • React &amp;
            Tailwind CSS
          </p>
        </div>
      </footer>
    </div>
  );
}
