import React from "react";
import {
  AudioLines,
  CheckCircle2,
  Cpu,
  Film,
  Loader2,
  Sliders,
} from "lucide-react";

const PIPELINE_STEPS = [
  {
    key: "extracting_audio",
    label: "Extract Audio",
    desc: "FFmpeg lossless 44.1kHz PCM stream",
    threshold: 6,
    icon: AudioLines,
  },
  {
    key: "separating_stems",
    label: "AI Stem Separation",
    desc: "TIGER-DnR (Speech / SFX / Music)",
    threshold: 18,
    icon: Cpu,
  },
  {
    key: "reconstructing_audio",
    label: "Audio Reconstruction",
    desc: "Suppress music & preserve ambience",
    threshold: 82,
    icon: Sliders,
  },
  {
    key: "rendering_video",
    label: "Sync & Export Video",
    desc: "Lossless stream muxing via FFmpeg",
    threshold: 90,
    icon: Film,
  },
];

export default function ProgressPipeline({ status, progress, stageMessage }) {
  const pct = Math.min(100, Math.max(0, Math.round(progress || 0)));
  const isCompleted = status === "completed";

  return (
    <div className="rounded-2xl border border-purple-500/25 bg-obsidian-900/90 p-5 sm:p-6 shadow-xl">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="flex items-center gap-2.5">
          {isCompleted ? (
            <CheckCircle2 className="h-5 w-5 text-emerald-400" />
          ) : (
            <Loader2 className="h-5 w-5 animate-spin text-cyan-400" />
          )}
          <span className="text-sm font-semibold text-white">
            {stageMessage || "Processing video audio streams..."}
          </span>
        </div>
        <span className="rounded-lg border border-cyan-500/30 bg-cyan-500/10 px-2.5 py-0.5 font-mono text-xs font-bold text-cyan-300">
          {pct}%
        </span>
      </div>

      {/* Main Gradient Progress Bar */}
      <div className="mt-3.5 h-3 w-full overflow-hidden rounded-full bg-white/10 p-0.5">
        <div
          className="h-full rounded-full bg-gradient-to-r from-purple-500 via-violet-500 to-cyan-400 transition-all duration-300"
          style={{ width: `${pct}%` }}
        />
      </div>

      {/* Step Cards */}
      <div className="mt-5 grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-4">
        {PIPELINE_STEPS.map((step, idx) => {
          const nextThreshold =
            idx < PIPELINE_STEPS.length - 1
              ? PIPELINE_STEPS[idx + 1].threshold
              : 100;
          const stepDone = isCompleted || pct >= nextThreshold;
          const stepActive =
            !isCompleted &&
            (status === step.key ||
              (pct >= step.threshold && pct < nextThreshold));
          const Icon = step.icon;

          return (
            <div
              key={step.key}
              className={`flex items-start gap-3 rounded-xl border p-3 transition ${
                stepDone
                  ? "border-emerald-500/30 bg-emerald-500/10 text-emerald-200"
                  : stepActive
                  ? "border-cyan-400/50 bg-cyan-500/10 text-white shadow-md shadow-cyan-500/10"
                  : "border-white/10 bg-white/[0.02] text-slate-400"
              }`}
            >
              <div
                className={`mt-0.5 flex h-8 w-8 shrink-0 items-center justify-center rounded-lg ${
                  stepDone
                    ? "bg-emerald-500/20 text-emerald-300"
                    : stepActive
                    ? "bg-cyan-500/20 text-cyan-300"
                    : "bg-white/5 text-slate-500"
                }`}
              >
                {stepDone ? (
                  <CheckCircle2 className="h-4 w-4" />
                ) : stepActive ? (
                  <Loader2 className="h-4 w-4 animate-spin" />
                ) : (
                  <Icon className="h-4 w-4" />
                )}
              </div>
              <div className="min-w-0">
                <p className="text-xs font-semibold">{step.label}</p>
                <p className="mt-0.5 text-[11px] opacity-75 truncate">
                  {step.desc}
                </p>
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
