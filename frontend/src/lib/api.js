/**
 * API client for VideoMusicRemover AI backend
 */

const API_BASE = import.meta.env.VITE_API_BASE_URL || "";

export function resolveMediaUrl(relativePath, cacheBuster = null) {
  if (!relativePath) return null;
  const base = relativePath.startsWith("http")
    ? relativePath
    : `${API_BASE}${relativePath}`;
  if (cacheBuster) {
    const sep = base.includes("?") ? "&" : "?";
    return `${base}${sep}v=${encodeURIComponent(cacheBuster)}`;
  }
  return base;
}

export async function fetchHealth() {
  const res = await fetch(`${API_BASE}/api/health`);
  if (!res.ok) {
    throw new Error(`Health check failed (${res.status})`);
  }
  return res.json();
}

export function uploadVideoFile(file, onProgress) {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open("POST", `${API_BASE}/api/jobs/upload`);

    xhr.upload.onprogress = (event) => {
      if (event.lengthComputable && onProgress) {
        const pct = Math.round((event.loaded / event.total) * 100);
        onProgress(pct);
      }
    };

    xhr.onload = () => {
      try {
        const data = JSON.parse(xhr.responseText || "{}");
        if (xhr.status >= 200 && xhr.status < 300) {
          resolve(data);
        } else {
          reject(new Error(data.detail || `Upload failed (HTTP ${xhr.status})`));
        }
      } catch (err) {
        reject(new Error(`Unexpected server response (${xhr.status})`));
      }
    };

    xhr.onerror = () => {
      reject(new Error("Network error while uploading video file."));
    };

    const formData = new FormData();
    formData.append("file", file);
    xhr.send(formData);
  });
}

export async function createDemoVideoJob() {
  const res = await fetch(`${API_BASE}/api/jobs/demo`, {
    method: "POST",
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    throw new Error(data.detail || "Failed to generate demo video.");
  }
  return data;
}

export async function startVideoProcessing(jobId, token, options) {
  const query = token ? `?token=${encodeURIComponent(token)}` : "";
  const res = await fetch(`${API_BASE}/api/jobs/${jobId}/process${query}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(options),
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    throw new Error(data.detail || "Failed to start AI processing.");
  }
  return data;
}

export async function fetchJobStatus(jobId, token) {
  const query = token ? `?token=${encodeURIComponent(token)}` : "";
  const res = await fetch(`${API_BASE}/api/jobs/${jobId}${query}`);
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    throw new Error(data.detail || "Failed to fetch job status.");
  }
  return data;
}

export async function remixJobAudio(jobId, token, remixOptions) {
  const query = token ? `?token=${encodeURIComponent(token)}` : "";
  const res = await fetch(`${API_BASE}/api/jobs/${jobId}/remix${query}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(remixOptions),
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    throw new Error(data.detail || "Failed to remix audio stems.");
  }
  return data;
}

export async function deleteJob(jobId, token) {
  const query = token ? `?token=${encodeURIComponent(token)}` : "";
  const res = await fetch(`${API_BASE}/api/jobs/${jobId}${query}`, {
    method: "DELETE",
  });
  if (!res.ok) {
    const data = await res.json().catch(() => ({}));
    throw new Error(data.detail || "Failed to delete job.");
  }
  return res.json();
}
