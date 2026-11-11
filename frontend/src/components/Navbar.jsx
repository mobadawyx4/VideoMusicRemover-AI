import React from "react";
import { AudioWaveform, Cpu, ShieldCheck, Sparkles } from "lucide-react";

export default function Navbar({ health }) {
  const isHealthy = health?.status === "ok";
  const modelReady = health?.ai_model_ready;

  return (
    <header className="sticky top-0 z-30 border-b border-white/10 bg-obsidian-950/80 backdrop-blur-xl">
      <div className="mx-auto flex max-w-7xl items-center justify-between px-4 py-3.5 sm:px-6 lg:px-8">
        {/* Brand Logo: SilentTrack AI */}
        <a href="#top" className="flex items-center gap-3 group">
          <div className="relative flex h-10 w-10 items-center justify-center rounded-xl bg-gradient-to-br from-purple-600 via-violet-600 to-cyan-500 p-[1px] shadow-lg shadow-purple-500/25">
            <div className="flex h-full w-full items-center justify-center rounded-[11px] bg-obsidian-900/90 transition group-hover:bg-transparent">
              <AudioWaveform className="h-5 w-5 text-cyan-300 transition group-hover:text-white" />
            </div>
          </div>
          <div>
            <div className="flex items-center gap-2">
              <span className="text-lg font-extrabold tracking-tight text-white">
                SilentTrack{" "}
                <span className="bg-gradient-to-r from-purple-400 via-violet-400 to-cyan-400 bg-clip-text text-transparent">
                  AI
                </span>
              </span>
              <span className="hidden rounded-full border border-purple-500/30 bg-purple-500/10 px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wider text-purple-300 sm:inline-block">
                TIGER-DnR Engine
              </span>
            </div>
            <p className="text-[11px] text-slate-400 hidden sm:block">
              Neural Video Background Music Remover • Speech &amp; Ambience Preservation
            </p>
          </div>
        </a>

        {/* Live System Status Badges */}
        <div className="flex items-center gap-2.5">
          <div
            className={`flex items-center gap-1.5 rounded-full border px-3 py-1 text-xs font-medium ${
              isHealthy && modelReady
                ? "border-emerald-500/30 bg-emerald-500/10 text-emerald-300"
                : "border-amber-500/30 bg-amber-500/10 text-amber-300"
            }`}
            title={
              health
                ? `Model: ${health.ai_model_name} | Device: ${health.device?.toUpperCase()}`
                : "Connecting to backend..."
            }
          >
            <span
              className={`h-2 w-2 rounded-full ${
                isHealthy && modelReady
                  ? "bg-emerald-400 animate-pulse"
                  : "bg-amber-400"
              }`}
            />
            <span className="hidden md:inline">
              {isHealthy && modelReady
                ? "AI Engine Ready"
                : health
                ? "Engine Initializing"
                : "Connecting..."}
            </span>
            <span className="md:hidden">
              {isHealthy && modelReady ? "Ready" : "..."}
            </span>
          </div>

          {health?.device && (
            <div className="hidden items-center gap-1.5 rounded-full border border-white/10 bg-white/5 px-3 py-1 text-xs text-slate-300 sm:flex">
              <Cpu className="h-3.5 w-3.5 text-cyan-400" />
              <span className="font-mono uppercase">{health.device}</span>
            </div>
          )}

          <div className="hidden items-center gap-1.5 rounded-full border border-cyan-500/20 bg-cyan-500/10 px-3 py-1 text-xs text-cyan-300 lg:flex">
            <ShieldCheck className="h-3.5 w-3.5" />
            <span>Auto-Cleanup Active</span>
          </div>
        </div>
      </div>
    </header>
  );
}
