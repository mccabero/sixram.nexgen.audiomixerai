const API_BASE = "/api";

async function request(path, options = {}) {
  const response = await fetch(`${API_BASE}${path}`, {
    headers: {
      "Content-Type": "application/json",
      ...options.headers,
    },
    ...options,
  });

  const contentType = response.headers.get("content-type") || "";
  const payload = contentType.includes("application/json") ? await response.json() : await response.text();

  if (!response.ok) {
    const detail = typeof payload === "object" && payload?.detail ? payload.detail : "Request failed.";
    throw new Error(Array.isArray(detail) ? detail.map((item) => item.msg).join(", ") : detail);
  }

  return payload;
}

export function listProjects() {
  return request("/projects");
}

export function getHealth() {
  return request("/health");
}

export function createProject(project) {
  return request("/projects", {
    method: "POST",
    body: JSON.stringify(project),
  });
}

export function getProject(projectId) {
  return request(`/projects/${projectId}`);
}

export function getProjectLogs(projectId, limit = 120) {
  return request(`/projects/${projectId}/logs?limit=${encodeURIComponent(limit)}`);
}

export function updateProject(projectId, project) {
  return request(`/projects/${projectId}`, {
    method: "PATCH",
    body: JSON.stringify(project),
  });
}

export function updateStemType(projectId, stemId, stemType) {
  return request(`/projects/${projectId}/stems/${stemId}`, {
    method: "PATCH",
    body: JSON.stringify({ stemType }),
  });
}

export function deleteStem(projectId, stemId) {
  return request(`/projects/${projectId}/stems/${stemId}`, {
    method: "DELETE",
  });
}

export function getDetectionMemory() {
  return request("/detection-memory");
}

export function clearDetectionMemory() {
  return request("/detection-memory", {
    method: "DELETE",
  });
}

export function detectStemTypes(projectId) {
  return request(`/projects/${projectId}/detect-stems`, {
    method: "POST",
  });
}

export function acceptAllStemDetections(projectId) {
  return request(`/projects/${projectId}/accept-all-detections`, {
    method: "POST",
  });
}

export function acceptStemDetection(projectId, stemId) {
  return request(`/projects/${projectId}/stems/${stemId}/accept-detection`, {
    method: "POST",
  });
}

export function startAnalysis(projectId) {
  return request(`/projects/${projectId}/analyze`, {
    method: "POST",
  });
}

export function getProcessingJob(projectId, jobId) {
  return request(`/projects/${projectId}/jobs/${jobId}`);
}

export function abandonProcessingJob(projectId, jobId) {
  return request(`/projects/${projectId}/jobs/${jobId}/abandon`, {
    method: "POST",
  });
}

export function updateCleaningSettings(projectId, stemId, updates) {
  return request(`/projects/${projectId}/stems/${stemId}/cleaning`, {
    method: "PATCH",
    body: JSON.stringify(updates),
  });
}

export function startCleaning(projectId) {
  return request(`/projects/${projectId}/clean-stems`, {
    method: "POST",
  });
}

export function listVocalEnhancerPresets() {
  return request("/vocal-enhancer-presets");
}

export function updateVocalEnhancementSettings(projectId, stemId, updates) {
  return request(`/projects/${projectId}/stems/${stemId}/vocal-enhancement`, {
    method: "PATCH",
    body: JSON.stringify(updates),
  });
}

export function startVocalEnhancement(projectId) {
  return request(`/projects/${projectId}/enhance-vocals`, {
    method: "POST",
  });
}

export function generateAutoBalance(projectId) {
  return request(`/projects/${projectId}/auto-balance`, {
    method: "POST",
  });
}

export function applyAutoBalance(projectId) {
  return request(`/projects/${projectId}/apply-auto-balance`, {
    method: "POST",
  });
}

export function updateMixStem(projectId, stemId, updates) {
  return request(`/projects/${projectId}/mix-settings/${stemId}`, {
    method: "PATCH",
    body: JSON.stringify(updates),
  });
}

export function listMixPresets() {
  return request("/mix-presets");
}

export function listMasteringPresets() {
  return request("/mastering-presets");
}

export function updateMixControls(projectId, updates) {
  return request(`/projects/${projectId}/mix-controls`, {
    method: "PATCH",
    body: JSON.stringify(updates),
  });
}

export function resetAdvancedMix(projectId) {
  return request(`/projects/${projectId}/reset-advanced-mix`, {
    method: "POST",
  });
}

export function generateRoughMix(projectId) {
  return request(`/projects/${projectId}/rough-mix`, {
    method: "POST",
  });
}

export function generateAdvancedMix(projectId) {
  return request(`/projects/${projectId}/advanced-mix`, {
    method: "POST",
  });
}

export function startAdvancedMix(projectId) {
  return request(`/projects/${projectId}/advanced-mix-job`, {
    method: "POST",
  });
}

export function generateInstrumentalMix(projectId) {
  return request(`/projects/${projectId}/instrumental-mix`, {
    method: "POST",
  });
}

export function startInstrumentalMix(projectId) {
  return request(`/projects/${projectId}/instrumental-mix-job`, {
    method: "POST",
  });
}

export function renameMixVersion(projectId, versionId, label) {
  return request(`/projects/${projectId}/mix-versions/${versionId}`, {
    method: "PATCH",
    body: JSON.stringify({ label }),
  });
}

export function deleteMixVersion(projectId, versionId) {
  return request(`/projects/${projectId}/mix-versions/${versionId}`, {
    method: "DELETE",
  });
}

export function updateMasteringControls(projectId, updates) {
  return request(`/projects/${projectId}/mastering-controls`, {
    method: "PATCH",
    body: JSON.stringify(updates),
  });
}

export function generateMaster(projectId, payload) {
  return request(`/projects/${projectId}/masters`, {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function startMasteringJob(projectId, payload) {
  return request(`/projects/${projectId}/masters-job`, {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function exportMixWithoutMastering(projectId, payload) {
  return request(`/projects/${projectId}/exports/mix`, {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function exportInstrumental(projectId, payload) {
  return request(`/projects/${projectId}/exports/instrumental`, {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function createProjectBackup(projectId, payload) {
  return request(`/projects/${projectId}/exports/backup`, {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function uploadStems(projectId, files, onProgress) {
  return new Promise((resolve, reject) => {
    const formData = new FormData();
    files.forEach((file) => formData.append("files", file));

    const xhr = new XMLHttpRequest();
    xhr.open("POST", `${API_BASE}/projects/${projectId}/stems`);

    xhr.upload.onprogress = (event) => {
      if (!event.lengthComputable || !onProgress) return;
      onProgress(Math.round((event.loaded / event.total) * 100));
    };

    xhr.onload = () => {
      try {
        const payload = JSON.parse(xhr.responseText || "{}");
        if (xhr.status >= 200 && xhr.status < 300) {
          resolve(payload);
        } else {
          reject(new Error(payload.detail || "Upload failed."));
        }
      } catch (error) {
        reject(error);
      }
    };

    xhr.onerror = () => reject(new Error("Could not reach the local API."));
    xhr.send(formData);
  });
}
