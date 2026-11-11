import React, { useEffect, useRef, useState } from "react";
import {
  Activity,
  AudioWaveform,
  Mic,
  Music,
  Pause,
  Play,
  Sparkles,
  Trees,
  Volume2,
} from "lucide-react";
import { resolveMediaUrl } from "../lib/api";
import { formatDb, formatDuration } from "../lib/formatters";

const TRACK_MODES = [
  {
    id: "processed",
    label: "Processed Audio (Music Removed)",
    shortLabel: "Processed Clean",
    icon: Sparkles,
    badgeColor: "from-purple-600 to-cyan-500 text-white",
    barColor: "bg-cyan-400",
    urlField: "processed_audio_url",
    peaksField: "processed_peaks",
  },
  {
    id: "original",
    label: "Original Audio (With Music)",
    shortLabel: "Original Audio",
    icon: Volume2,
    badgeColor: "from-slate-700 to-slate-600 text-slate-100",
    barColor: "bg-purple-400",
    urlField: "original_audio_url",
    peaksField: "original_peaks",
  },
  {
    id: "speech",
    label: "Isolated Speech / Dialogue",
    shortLabel: "Speech Stem",
    icon: Mic,
    badgeColor: "from-emerald-600 to-teal-500 text-white",
    barColor: "bg-emerald-400",
    urlField: "speech_stem_url",
    peaksField: "speech_peaks",
  },
  {
    id: "effects",
    label: "Environmental Sounds & SFX",
    shortLabel: "Environment Stem",
    icon: Trees,
    badgeColor: "from-blue-600 to-indigo-500 text-white",
    barColor: "bg-blue-400",
    urlField: "effects_stem_url",
    peaksField: "effects_peaks",
  },
  {
    id: "music",
    label: "Removed Background Music",
    shortLabel: "Removed Music",
    icon: Music,
    badgeColor: "from-rose-600 to-pink-600 text-white",
    barColor: "bg-rose-400",
    urlField: "music_stem_url",
    peaksField: "music_peaks",
  },
];

export default function AudioComparisonStudio({ job }) {
  const [activeTrack, setActiveTrack] = useState("processed");
  const [isPlaying, setIsPlaying] = useState(false);
  const [currentTime, setCurrentTime] = useState(0);
  const [duration, setDuration] = useState(job?.metadata?.duration_seconds || 0);
  const audioRef = useRef(null);

  const selectedMode =
    TRACK_MODES.find((m) => m.id === activeTrack) || TRACK_MODES[0];
  const audioSrc = resolveMediaUrl(
    job?.[selectedMode.urlField],
    job?.updated_at
  );

  // Switch audio source seamlessly while preserving current playback time
  const handleSelectTrack = (modeId) => {
    if (modeId === activeTrack) return;
    const wasPlaying = isPlaying;
    const savedTime = audioRef.current ? audioRef.current.currentTime : 0;
    setActiveTrack(modeId);

    setTimeout(() => {
      if (audioRef.current) {
        audioRef.current.currentTime = savedTime;
        if (wasPlaying) {
          audioRef.current.play().catch(() => setIsPlaying(false));
        }
      }
    }, 40);
  };

  useEffect(() => {
    const el = audioRef.current;
    if (!el) return;
    const onTime = () => setCurrentTime(el.currentTime || 0);
    const onLoaded = () => {
      if (el.duration && !Number.isNaN(el.duration)) {
        setDuration(el.duration);
      }
    };
    const onEnded = () => setIsPlaying(false);

    el.addEventListener("timeupdate", onTime);
    el.addEventListener("loadedmetadata", onLoaded);
    el.addEventListener("ended", onEnded);
    return () => {
      el.removeEventListener("timeupdate", onTime);
      el.removeEventListener("loadedmetadata", onLoaded);
      el.removeEventListener("ended", onEnded);
    };
  }, [audioSrc]);

  const togglePlay = () => {
    const el = audioRef.current;
    if (!el) return;
    if (isPlaying) {
      el.pause();
      setIsPlaying(false);
    } else {
      el.play()
        .then(() => setIsPlaying(true))
        .catch(() => setIsPlaying(false));
    }
  };

  const handleWaveformSeek = (e) => {
    const el = audioRef.current;
    if (!el || !duration) return;
    const rect = e.currentTarget.getBoundingClientRect();
    const ratio = Math.min(1, Math.max(0, (e.clientX - rect.left) / rect.width));
    el.currentTime = ratio * duration;
    setCurrentTime(el.currentTime);
  };

  const origPeaks = job?.waveform?.original_peaks || [];
  const activePeaks =
    job?.waveform?.[selectedMode.peaksField] ||
    job?.waveform?.processed_peaks ||
    [];
  const playRatio = duration > 0 ? Math.min(1, currentTime / duration) : 0;
  const metrics = job?.metrics;

  return (
    <div className="rounded-3xl border border-white/10 bg-obsidian-900/90 p-5 sm:p-7 shadow-2xl">
      <audio ref={audioRef} src={audioSrc || undefined} preload="metadata" />

      <div className="flex flex-wrap items-center justify-between gap-4 border-b border-white/10 pb-5">
        <div>
          <div className="flex items-center gap-2">
            <AudioWaveform className="h-5 w-5 text-cyan-400" />
            <h3 className="text-lg font-bold text-white">
              Before &amp; After Audio Comparison Studio
            </h3>
          </div>
          <p className="mt-1 text-xs text-slate-400">
            Toggle seamlessly between the original audio, the clean music-free
            mix, or audition each AI-isolated stem in real time.
          </p>
        </div>

        {/* Quick Original vs Processed Toggle */}
        <div className="flex flex-wrap items-center gap-1.5 rounded-xl border border-white/10 bg-obsidian-950 p-1">
          {TRACK_MODES.map((m) => {
            const Icon = m.icon;
            const active = activeTrack === m.id;
            return (
              <button
                key={m.id}
                type="button"
                onClick={() => handleSelectTrack(m.id)}
                className={`inline-flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-xs font-semibold transition ${
                  active
                    ? `bg-gradient-to-r ${m.badgeColor} shadow-md`
                    : "text-slate-400 hover:bg-white/5 hover:text-slate-200"
                }`}
              >
                <Icon className="h-3.5 w-3.5" />
                <span>{m.shortLabel}</span>
              </button>
            );
          })}
        </div>
      </div>

      {/* Player Transport & Dual Waveform Display */}
      <div className="mt-5 grid grid-cols-1 gap-4 lg:grid-cols-12 items-center">
        {/* Play/Pause Button & Timecode */}
        <div className="flex items-center gap-4 lg:col-span-3">
          <button
            type="button"
            onClick={togglePlay}
            className="flex h-14 w-14 shrink-0 items-center justify-center rounded-2xl bg-gradient-to-br from-purple-600 via-violet-600 to-cyan-500 text-white shadow-lg shadow-purple-500/30 transition hover:brightness-110 active:scale-95"
            aria-label={isPlaying ? "Pause audio preview" : "Play audio preview"}
          >
            {isPlaying ? (
              <Pause className="h-6 w-6 fill-current" />
            ) : (
              <Play className="h-6 w-6 fill-current ml-0.5" />
            )}
          </button>

          <div className="min-w-0">
            <span className="inline-block rounded-md border border-white/10 bg-white/5 px-2 py-0.5 text-[11px] font-semibold text-cyan-300">
              {selectedMode.label}
            </span>
            <div className="mt-1.5 font-mono text-sm font-semibold text-white">
              {formatDuration(currentTime)}{" "}
              <span className="text-slate-500">/</span>{" "}
              <span className="text-slate-400">{formatDuration(duration)}</span>
            </div>
          </div>
        </div>

        {/* Synchronized Dual Waveforms (Before vs After/Active) */}
        <div
          onClick={handleWaveformSeek}
          className="cursor-pointer rounded-2xl border border-white/10 bg-obsidian-950/90 p-4 lg:col-span-9 space-y-3"
          title="Click anywhere on the waveform to seek"
        >
          {/* Original Waveform Row */}
          <div>
            <div className="mb-1 flex items-center justify-between text-[11px] text-slate-400">
              <span className="font-medium text-purple-300">
                BEFORE • Original Mix (Speech + Environment + Music)
              </span>
              <span className="font-mono">
                {formatDb(metrics?.original_rms_db)}
              </span>
            </div>
            <div className="flex h-10 items-end gap-[2px]">
              {origPeaks.map((peak, i) => {
                const passed = i / origPeaks.length <= playRatio;
                return (
                  <div
                    key={i}
                    className={`flex-1 rounded-full transition-colors ${
                      passed ? "bg-purple-400" : "bg-purple-500/25"
                    }`}
                    style={{ height: `${Math.max(12, Math.round(peak * 100))}%` }}
                  />
                );
              })}
            </div>
          </div>

          {/* Active / Processed Waveform Row */}
          <div className="border-t border-white/5 pt-2.5">
            <div className="mb-1 flex items-center justify-between text-[11px] text-slate-400">
              <span className="font-medium text-cyan-300">
                AFTER • {selectedMode.label}
              </span>
              <span className="font-mono">
                {activeTrack === "processed"
                  ? formatDb(metrics?.processed_rms_db)
                  : activeTrack === "speech"
                  ? formatDb(metrics?.speech_rms_db)
                  : activeTrack === "effects"
                  ? formatDb(metrics?.effects_rms_db)
                  : activeTrack === "music"
                  ? formatDb(metrics?.music_rms_db)
                  : formatDb(metrics?.original_rms_db)}
              </span>
            </div>
            <div className="flex h-10 items-end gap-[2px]">
              {activePeaks.map((peak, i) => {
                const passed = i / activePeaks.length <= playRatio;
                return (
                  <div
                    key={i}
                    className={`flex-1 rounded-full transition-colors ${
                      passed ? selectedMode.barColor : "bg-cyan-500/25"
                    }`}
                    style={{ height: `${Math.max(12, Math.round(peak * 100))}%` }}
                  />
                );
              })}
            </div>
          </div>
        </div>
      </div>

      {/* Stem Telemetry Metrics */}
      {metrics && (
        <div className="mt-5 grid grid-cols-2 gap-3 sm:grid-cols-4">
          <div className="rounded-xl border border-white/10 bg-white/[0.02] p-3">
            <p className="text-[11px] text-slate-400">Music Suppression</p>
            <p className="mt-1 font-mono text-base font-bold text-emerald-400">
              -{metrics.music_suppression_db} dB
            </p>
          </div>
          <div className="rounded-xl border border-white/10 bg-white/[0.02] p-3">
            <p className="text-[11px] text-slate-400">Preserved Speech Level</p>
            <p className="mt-1 font-mono text-base font-bold text-cyan-300">
              {formatDb(metrics.speech_rms_db)}
            </p>
          </div>
          <div className="rounded-xl border border-white/10 bg-white/[0.02] p-3">
            <p className="text-[11px] text-slate-400">
              Environmental Ambience
            </p>
            <p className="mt-1 font-mono text-base font-bold text-purple-300">
              {formatDb(metrics.effects_rms_db)}
            </p>
          </div>
          <div className="rounded-xl border border-white/10 bg-white/[0.02] p-3">
            <p className="text-[11px] text-slate-400">Processing Time</p>
            <p className="mt-1 font-mono text-base font-bold text-slate-200">
              {metrics.processing_time_seconds}s
            </p>
          </div>
        </div>
      )}
    </div>
  );
}
