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

export function listAudioInputDevices() {
  return request("/audio-input-devices");
}

export function getDirectRecordingStatus(projectId) {
  return request(`/projects/${projectId}/direct-recording`);
}

export function startDirectRecording(projectId, payload) {
  return request(`/projects/${projectId}/direct-recording/start`, {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function stopDirectRecording(projectId) {
  return request(`/projects/${projectId}/direct-recording/stop`, {
    method: "POST",
  });
}

export function getVideoEditorState(projectId) {
  return request(`/projects/${projectId}/video-editor`);
}

export function updateVideoEditorSettings(projectId, updates) {
  return request(`/projects/${projectId}/video-editor/settings`, {
    method: "PATCH",
    body: JSON.stringify(updates),
  });
}

export function getVideoWaveforms(projectId) {
  return request(`/projects/${projectId}/video-editor/waveforms`);
}

export function createVideoBrandingTemplate(projectId, payload) {
  return request(`/projects/${projectId}/video-editor/templates`, {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function applyVideoBrandingTemplate(projectId, templateId) {
  return request(`/projects/${projectId}/video-editor/templates/${templateId}/apply`, {
    method: "POST",
  });
}

export function deleteVideoBrandingTemplate(projectId, templateId) {
  return request(`/projects/${projectId}/video-editor/templates/${templateId}`, {
    method: "DELETE",
  });
}

export function startVideoExportJob(projectId) {
  return request(`/projects/${projectId}/video-editor/export-job`, {
    method: "POST",
  });
}

export function startVideoPreviewJob(projectId) {
  return request(`/projects/${projectId}/video-editor/preview-job`, {
    method: "POST",
  });
}

export function getVideoExportJob(projectId, jobId) {
  return request(`/projects/${projectId}/video-editor/jobs/${jobId}`);
}

export function runVideoAutoSync(projectId) {
  return request(`/projects/${projectId}/video-editor/auto-sync`, {
    method: "POST",
  });
}

export function deleteVideoExport(projectId, exportId) {
  return request(`/projects/${projectId}/video-editor/exports/${exportId}`, {
    method: "DELETE",
  });
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

export function deleteProject(projectId) {
  return request(`/projects/${projectId}`, {
    method: "DELETE",
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

export function deleteAnalysisResults(projectId) {
  return request(`/projects/${projectId}/analysis-results`, {
    method: "DELETE",
  });
}

export function deleteStemDetections(projectId) {
  return request(`/projects/${projectId}/stem-detections`, {
    method: "DELETE",
  });
}

export function deleteAutoBalance(projectId) {
  return request(`/projects/${projectId}/auto-balance`, {
    method: "DELETE",
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

export function cancelProcessingJob(projectId, jobId) {
  return request(`/projects/${projectId}/jobs/${jobId}/cancel`, {
    method: "POST",
  });
}

export function cancelVideoExportJob(projectId, jobId) {
  return request(`/projects/${projectId}/video-editor/jobs/${jobId}/cancel`, {
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

export function deleteCleanedStems(projectId) {
  return request(`/projects/${projectId}/cleaned-stems`, {
    method: "DELETE",
  });
}

export function listVocalEnhancerPresets() {
  return request("/vocal-enhancer-presets");
}

export function listCustomVocalPresets() {
  return request("/vocal-custom-presets");
}

export function createCustomVocalPreset(payload) {
  return request("/vocal-custom-presets", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function deleteCustomVocalPreset(presetId) {
  return request(`/vocal-custom-presets/${presetId}`, {
    method: "DELETE",
  });
}

export function updateVocalEnhancementSettings(projectId, stemId, updates) {
  return request(`/projects/${projectId}/stems/${stemId}/vocal-enhancement`, {
    method: "PATCH",
    body: JSON.stringify(updates),
  });
}

export function analyzeVocalRecommendations(projectId) {
  return request(`/projects/${projectId}/analyze-vocals`, {
    method: "POST",
  });
}

export function applyVocalRecommendation(projectId, stemId) {
  return request(`/projects/${projectId}/stems/${stemId}/apply-vocal-recommendation`, {
    method: "POST",
  });
}

export function applyAllVocalRecommendations(projectId) {
  return request(`/projects/${projectId}/apply-vocal-recommendations`, {
    method: "POST",
  });
}

export function runVocalQualityDoctor(projectId) {
  return request(`/projects/${projectId}/vocal-quality-doctor`, {
    method: "POST",
  });
}

export function applyVocalDoctorFix(projectId, stemId) {
  return request(`/projects/${projectId}/stems/${stemId}/apply-vocal-doctor-fix`, {
    method: "POST",
  });
}

export function startVocalEnhancement(projectId) {
  return request(`/projects/${projectId}/enhance-vocals`, {
    method: "POST",
  });
}

export function deleteVocalEnhancements(projectId) {
  return request(`/projects/${projectId}/vocal-enhancements`, {
    method: "DELETE",
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

export function resetStemProcessing(projectId) {
  return request(`/projects/${projectId}/reset-stem-processing`, {
    method: "POST",
  });
}

export function generateRoughMix(projectId) {
  return request(`/projects/${projectId}/rough-mix`, {
    method: "POST",
  });
}

export function deleteRoughMix(projectId) {
  return request(`/projects/${projectId}/rough-mix`, {
    method: "DELETE",
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

export function deleteAllMixVersions(projectId) {
  return request(`/projects/${projectId}/mix-versions`, {
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

export function deleteMasters(projectId) {
  return request(`/projects/${projectId}/masters`, {
    method: "DELETE",
  });
}

export function deleteExports(projectId) {
  return request(`/projects/${projectId}/exports`, {
    method: "DELETE",
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

export function uploadRawVideo(projectId, file, role = "auto", onProgress) {
  return new Promise((resolve, reject) => {
    const formData = new FormData();
    formData.append("file", file);

    const xhr = new XMLHttpRequest();
    xhr.open("POST", `${API_BASE}/projects/${projectId}/video-editor/raw-video?role=${encodeURIComponent(role)}`);

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
          reject(new Error(payload.detail || "Video upload failed."));
        }
      } catch (error) {
        reject(error);
      }
    };

    xhr.onerror = () => reject(new Error("Could not reach the local API."));
    xhr.send(formData);
  });
}

export function deleteVideoRawClip(projectId, clipId) {
  return request(`/projects/${projectId}/video-editor/raw-videos/${clipId}`, {
    method: "DELETE",
  });
}

export function uploadVideoWatermarkLogo(projectId, file, onProgress) {
  return new Promise((resolve, reject) => {
    const formData = new FormData();
    formData.append("file", file);

    const xhr = new XMLHttpRequest();
    xhr.open("POST", `${API_BASE}/projects/${projectId}/video-editor/watermark-logo`);

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
          reject(new Error(payload.detail || "Logo upload failed."));
        }
      } catch (error) {
        reject(error);
      }
    };

    xhr.onerror = () => reject(new Error("Could not reach the local API."));
    xhr.send(formData);
  });
}
