import React, { useRef, useState } from "react";
import {
  FileVideo,
  Film,
  Loader2,
  Sparkles,
  UploadCloud,
  Wand2,
} from "lucide-react";

const SUPPORTED_FORMATS = ["MP4", "MOV", "MKV", "WEBM"];

export default function UploadZone({
  onSelectFile,
  onLoadDemo,
  isUploading,
  uploadProgress,
  maxUploadMb = 500,
}) {
  const inputRef = useRef(null);
  const [isDragging, setIsDragging] = useState(false);

  const handleDragOver = (e) => {
    e.preventDefault();
    e.stopPropagation();
    if (!isUploading) setIsDragging(true);
  };

  const handleDragLeave = (e) => {
    e.preventDefault();
    e.stopPropagation();
    setIsDragging(false);
  };

  const handleDrop = (e) => {
    e.preventDefault();
    e.stopPropagation();
    setIsDragging(false);
    if (isUploading) return;
    const files = e.dataTransfer?.files;
    if (files && files.length > 0) {
      onSelectFile(files[0]);
    }
  };

  const handleFileChange = (e) => {
    const files = e.target.files;
    if (files && files.length > 0) {
      onSelectFile(files[0]);
    }
  };

  return (
    <div
      onDragOver={handleDragOver}
      onDragLeave={handleDragLeave}
      onDrop={handleDrop}
      onClick={() => !isUploading && inputRef.current?.click()}
      className={`group relative cursor-pointer overflow-hidden rounded-3xl border-2 border-dashed p-8 sm:p-12 transition-all duration-300 ${
        isDragging
          ? "border-cyan-400 bg-gradient-to-b from-purple-900/30 via-obsidian-900 to-cyan-900/30 scale-[1.01] shadow-2xl shadow-cyan-500/20"
          : "border-white/15 bg-obsidian-900/75 hover:border-purple-400/60 hover:bg-obsidian-900/95 shadow-xl shadow-black/40"
      }`}
    >
      {/* Decorative Background Glow */}
      <div className="pointer-events-none absolute -top-24 left-1/2 h-48 w-96 -translate-x-1/2 rounded-full bg-gradient-to-r from-purple-600/20 via-violet-500/20 to-cyan-500/20 blur-3xl transition-opacity duration-300 group-hover:opacity-100 opacity-60" />

      <input
        ref={inputRef}
        type="file"
        accept=".mp4,.mov,.mkv,.webm,video/mp4,video/quicktime,video/x-matroska,video/webm"
        onChange={handleFileChange}
        className="hidden"
        aria-label="Upload video file"
      />

      <div className="relative z-10 flex flex-col items-center text-center">
        <div className="mb-5 flex h-20 w-20 items-center justify-center rounded-2xl border border-purple-500/30 bg-gradient-to-br from-purple-500/20 via-obsidian-800 to-cyan-500/20 shadow-inner transition-transform duration-300 group-hover:scale-105">
          {isUploading ? (
            <Loader2 className="h-10 w-10 animate-spin text-cyan-400" />
          ) : (
            <UploadCloud className="h-10 w-10 text-purple-400 transition-colors group-hover:text-cyan-300" />
          )}
        </div>

        <h2 className="text-xl sm:text-2xl font-bold text-white">
          {isUploading
            ? "Uploading & Validating Video..."
            : isDragging
            ? "Drop Your Video Here to Begin"
            : "Drag & Drop Your Video File Here"}
        </h2>

        <p className="mt-2 max-w-lg text-sm text-slate-400">
          Automatically isolate and strip background music while preserving clear
          human dialogue, vocals, and natural environmental sound effects.
        </p>

        {/* Format Badges */}
        <div className="mt-5 flex flex-wrap items-center justify-center gap-2">
          {SUPPORTED_FORMATS.map((fmt) => (
            <span
              key={fmt}
              className="rounded-lg border border-white/10 bg-white/5 px-2.5 py-1 font-mono text-xs font-medium text-slate-300"
            >
              .{fmt}
            </span>
          ))}
          <span className="rounded-lg border border-purple-500/25 bg-purple-500/10 px-2.5 py-1 text-xs font-medium text-purple-300">
            Up to {maxUploadMb} MB
          </span>
        </div>

        {/* Upload Progress or Action Buttons */}
        {isUploading ? (
          <div className="mt-7 w-full max-w-md">
            <div className="mb-2 flex items-center justify-between text-xs font-mono text-cyan-300">
              <span>Streaming video to workspace...</span>
              <span>{uploadProgress}%</span>
            </div>
            <div className="h-2.5 w-full overflow-hidden rounded-full bg-white/10">
              <div
                className="h-full rounded-full bg-gradient-to-r from-purple-500 via-violet-500 to-cyan-400 transition-all duration-200"
                style={{ width: `${uploadProgress}%` }}
              />
            </div>
          </div>
        ) : (
          <div
            className="mt-7 flex flex-wrap items-center justify-center gap-3"
            onClick={(e) => e.stopPropagation()}
          >
            <button
              type="button"
              onClick={() => inputRef.current?.click()}
              className="inline-flex items-center gap-2 rounded-xl bg-gradient-to-r from-purple-600 via-violet-600 to-cyan-500 px-6 py-3 text-sm font-semibold text-white shadow-lg shadow-purple-600/30 transition hover:brightness-110 active:scale-[0.99]"
            >
              <FileVideo className="h-4 w-4" />
              <span>Upload Video</span>
            </button>

            <button
              type="button"
              onClick={onLoadDemo}
              className="inline-flex items-center gap-2 rounded-xl border border-white/15 bg-white/5 px-5 py-3 text-sm font-medium text-slate-200 transition hover:border-cyan-400/50 hover:bg-white/10 hover:text-white"
            >
              <Wand2 className="h-4 w-4 text-cyan-400" />
              <span>Try Instant Sample Video</span>
            </button>
          </div>
        )}
      </div>
    </div>
  );
}
