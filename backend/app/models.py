from pydantic import BaseModel, Field

from .config import STEM_TYPES


class CreateProjectRequest(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    artistName: str | None = Field(default=None, max_length=120)
    songTitle: str | None = Field(default=None, max_length=120)
    notes: str | None = Field(default=None, max_length=2000)


class UpdateProjectRequest(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    artistName: str | None = Field(default=None, max_length=120)
    songTitle: str | None = Field(default=None, max_length=120)
    notes: str | None = Field(default=None, max_length=2000)


class UpdateStemRequest(BaseModel):
    stemType: str


class StemDetectionResult(BaseModel):
    stemId: str
    suggestedStemType: str
    confidence: int = Field(ge=0, le=100)
    reason: str
    method: str
    detectedAt: str
    accepted: bool = False
    features: dict[str, float | int | None] = Field(default_factory=dict)


class UpdateMixStemRequest(BaseModel):
    gainDb: float | None = Field(default=None, ge=-48, le=24)
    pan: float | None = Field(default=None, ge=-100, le=100)
    mute: bool | None = None
    solo: bool | None = None
    processingChainEnabled: bool | None = None
    reverbSend: float | None = Field(default=None, ge=0, le=100)
    delaySend: float | None = Field(default=None, ge=0, le=100)
    presenceAmount: float | None = Field(default=None, ge=-50, le=50)
    compressionAmount: float | None = Field(default=None, ge=0, le=100)


class UpdateMixControlsRequest(BaseModel):
    preset: str | None = None
    vocalBoost: float | None = Field(default=None, ge=-6, le=6)
    vocalBusLevel: float | None = Field(default=None, ge=-6, le=6)
    vocalGlueAmount: float | None = Field(default=None, ge=0, le=100)
    vocalDelayAmount: float | None = Field(default=None, ge=0, le=100)
    backingVocalWidth: float | None = Field(default=None, ge=0, le=100)
    drumPunch: float | None = Field(default=None, ge=0, le=100)
    bassWeight: float | None = Field(default=None, ge=0, le=100)
    brightness: float | None = Field(default=None, ge=-50, le=50)
    warmth: float | None = Field(default=None, ge=-50, le=50)
    width: float | None = Field(default=None, ge=0, le=100)
    reverbAmount: float | None = Field(default=None, ge=0, le=100)
    vocalReverbAmount: float | None = Field(default=None, ge=0, le=100)
    roomSize: float | None = Field(default=None, ge=0, le=100)


class UpdateMixVersionRequest(BaseModel):
    label: str = Field(min_length=1, max_length=80)


class UpdateMasteringControlsRequest(BaseModel):
    selectedMixVersionId: str | None = None
    preset: str | None = None
    brightness: float | None = Field(default=None, ge=-50, le=50)
    warmth: float | None = Field(default=None, ge=-50, le=50)
    compressionAmount: float | None = Field(default=None, ge=0, le=100)
    limiterStrength: float | None = Field(default=None, ge=0, le=100)
    stereoWidth: float | None = Field(default=None, ge=0, le=100)
    outputFormat: str | None = None
    trimStartSeconds: float | None = Field(default=None, ge=0)
    trimEndSeconds: float | None = Field(default=None, ge=0)


class GenerateMasterRequest(BaseModel):
    selectedMixVersionId: str
    preset: str
    outputFormat: str
    brightness: float = Field(default=0, ge=-50, le=50)
    warmth: float = Field(default=0, ge=-50, le=50)
    compressionAmount: float = Field(default=45, ge=0, le=100)
    limiterStrength: float = Field(default=55, ge=0, le=100)
    stereoWidth: float = Field(default=55, ge=0, le=100)
    trimStartSeconds: float = Field(default=0, ge=0)
    trimEndSeconds: float = Field(default=0, ge=0)


class ExportMixRequest(BaseModel):
    selectedMixVersionId: str
    outputFormat: str
    trimStartSeconds: float = Field(default=0, ge=0)
    trimEndSeconds: float = Field(default=0, ge=0)


class VideoFocusPlacement(BaseModel):
    id: str | None = None
    clipId: str
    startSeconds: float = Field(default=0, ge=0)
    durationSeconds: float | None = Field(default=None, ge=0.25)
    sourceStartSeconds: float = Field(default=0, ge=0)


class UpdateVideoEditorSettingsRequest(BaseModel):
    selectedAudioAssetId: str | None = None
    useSelectedMasterAudio: bool | None = None
    useOriginalVideoAudio: bool | None = None
    clipOrderIds: list[str] | None = None
    audioOffsetMs: int | None = Field(default=None, ge=-600000, le=600000)
    trimStartSeconds: float | None = Field(default=None, ge=0)
    trimEndSeconds: float | None = Field(default=None, ge=0)
    fadeInSeconds: float | None = Field(default=None, ge=0, le=8)
    fadeOutSeconds: float | None = Field(default=None, ge=0, le=8)
    exportPreset: str | None = None
    transitionStyle: str | None = None
    transitionDurationSeconds: float | None = Field(default=None, ge=0, le=2)
    focusPlacements: list[VideoFocusPlacement] | None = None
    songTitle: str | None = Field(default=None, max_length=120)
    artistName: str | None = Field(default=None, max_length=120)
    sessionLabel: str | None = Field(default=None, max_length=120)
    overlayPosition: str | None = None
    overlayStyle: str | None = None
    overlaySize: str | None = None
    watermarkEnabled: bool | None = None
    watermarkPosition: str | None = None
    watermarkOpacity: float | None = Field(default=None, ge=0.05, le=1)
    watermarkScale: float | None = Field(default=None, ge=0.05, le=0.5)
    introEnabled: bool | None = None
    introDurationSeconds: float | None = Field(default=None, ge=0.5, le=10)
    introTitle: str | None = Field(default=None, max_length=120)
    introSubtitle: str | None = Field(default=None, max_length=180)
    outroEnabled: bool | None = None
    outroDurationSeconds: float | None = Field(default=None, ge=0.5, le=10)
    outroTitle: str | None = Field(default=None, max_length=120)
    outroSubtitle: str | None = Field(default=None, max_length=180)


class CreateVideoBrandingTemplateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=80)


class ProjectBackupRequest(BaseModel):
    includeOriginalStems: bool = False


class UpdateCleaningSettingsRequest(BaseModel):
    enabled: bool | None = None
    mode: str | None = None
    humRemoval: bool | None = None
    humFrequency: int | None = Field(default=None, ge=50, le=60)
    useCleanedInMix: bool | None = None


VOCAL_ENHANCER_PRESETS = [
    "AI Pop Clean",
    "AI Studio Clear",
    "Suno-Style Lead",
    "Suno Clean Dry",
    "Natural Clean",
    "Pop Vocal",
    "Worship Lead",
    "Live Vocal Fix",
    "Bright AI Polish",
    "Warm Ballad",
    "Backing Vocal Wide",
]
PITCH_CORRECTION_MODES = ["Off", "Natural", "Medium", "Strong"]
VOCAL_FX_STYLES = ["Dry", "Natural Plate", "Small Hall", "Slap Delay", "Quarter Delay", "Worship Wide"]
MUSIC_KEYS = ["Auto", "C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]
MUSIC_SCALES = ["Major", "Minor", "Chromatic"]


class UpdateVocalEnhancementSettingsRequest(BaseModel):
    enabled: bool | None = None
    preset: str | None = None
    pitchCorrection: str | None = None
    key: str | None = None
    scale: str | None = None
    fxStyle: str | None = None
    fxAmount: float | None = Field(default=None, ge=0, le=100)
    bodyAmount: float | None = Field(default=None, ge=-50, le=50)
    presenceAmount: float | None = Field(default=None, ge=-50, le=50)
    airAmount: float | None = Field(default=None, ge=-50, le=50)
    deEssAmount: float | None = Field(default=None, ge=0, le=100)
    compressionAmount: float | None = Field(default=None, ge=0, le=100)
    riderAmount: float | None = Field(default=None, ge=0, le=100)
    saturationAmount: float | None = Field(default=None, ge=0, le=100)
    doublerAmount: float | None = Field(default=None, ge=0, le=100)
    breathReductionAmount: float | None = Field(default=None, ge=0, le=100)
    mouthClickReductionAmount: float | None = Field(default=None, ge=0, le=100)
    pitchStrength: float | None = Field(default=None, ge=0, le=100)
    pitchHumanize: float | None = Field(default=None, ge=0, le=100)
    useEnhancedInMix: bool | None = None


class CreateVocalPresetRequest(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    settings: UpdateVocalEnhancementSettingsRequest


class StemMetadata(BaseModel):
    durationSeconds: float | None = None
    sampleRate: int | None = None
    channels: int | None = None


class AnalysisResult(BaseModel):
    stemId: str
    status: str = "Pending"
    analyzedAt: str | None = None
    durationSeconds: float | None = None
    sampleRate: int | None = None
    channels: int | None = None
    peakDbfs: float | None = None
    rmsDbfs: float | None = None
    integratedLufs: float | None = None
    truePeakDbfs: float | None = None
    clippingDetected: bool = False
    clippingSampleCount: int = 0
    clippingPercentage: float = 0
    silencePercentage: float | None = None
    noiseFloorDbfs: float | None = None
    warnings: list[str] = Field(default_factory=list)
    error: str | None = None


class AutoBalanceSuggestion(BaseModel):
    stemId: str
    suggestedGainDb: float
    suggestedPan: float
    rolePriority: int
    targetLufs: float
    rationale: str
    generatedAt: str


class StemCleaningSettings(BaseModel):
    enabled: bool = False
    mode: str = "Off"
    humRemoval: bool = False
    humFrequency: int = 60
    useCleanedInMix: bool = True


class CleaningMetrics(BaseModel):
    durationSeconds: float | None = None
    sampleRate: int | None = None
    channels: int | None = None
    peakDbfs: float | None = None
    rmsDbfs: float | None = None
    integratedLufs: float | None = None
    truePeakDbfs: float | None = None
    silencePercentage: float | None = None
    noiseFloorDbfs: float | None = None


class StemCleaningResult(BaseModel):
    stemId: str
    status: str = "Pending"
    cleanedAt: str | None = None
    originalFilePath: str | None = None
    cleanedFilePath: str | None = None
    cleanedFileUrl: str | None = None
    mode: str = "Off"
    humRemoval: bool = False
    humFrequency: int = 60
    peakDbfs: float | None = None
    rmsDbfs: float | None = None
    noiseFloorDbfs: float | None = None
    originalMetrics: CleaningMetrics | None = None
    cleanedMetrics: CleaningMetrics | None = None
    metricDeltas: dict[str, float | None] = Field(default_factory=dict)
    operations: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    report: dict = Field(default_factory=dict)
    error: str | None = None


class StemVocalEnhancementSettings(BaseModel):
    enabled: bool = False
    preset: str = "AI Pop Clean"
    pitchCorrection: str = "Off"
    key: str = "Auto"
    scale: str = "Major"
    fxStyle: str = "Dry"
    fxAmount: float = 0
    bodyAmount: float = 0
    presenceAmount: float = 0
    airAmount: float = 0
    deEssAmount: float = 50
    compressionAmount: float = 40
    riderAmount: float = 36
    saturationAmount: float = 18
    doublerAmount: float = 16
    breathReductionAmount: float = 35
    mouthClickReductionAmount: float = 30
    pitchStrength: float = 42
    pitchHumanize: float = 72
    useEnhancedInMix: bool = True


class StemVocalEnhancementResult(BaseModel):
    stemId: str
    status: str = "Pending"
    enhancedAt: str | None = None
    sourceFilePath: str | None = None
    sourceKind: str = "Original"
    enhancedFilePath: str | None = None
    enhancedFileUrl: str | None = None
    preset: str = "AI Pop Clean"
    pitchCorrection: str = "Off"
    key: str = "Auto"
    scale: str = "Major"
    fxStyle: str = "Dry"
    fxAmount: float = 0
    bodyAmount: float = 0
    presenceAmount: float = 0
    airAmount: float = 0
    deEssAmount: float = 50
    compressionAmount: float = 40
    riderAmount: float = 36
    saturationAmount: float = 18
    doublerAmount: float = 16
    breathReductionAmount: float = 35
    mouthClickReductionAmount: float = 30
    pitchStrength: float = 42
    pitchHumanize: float = 72
    peakDbfs: float | None = None
    rmsDbfs: float | None = None
    integratedLufs: float | None = None
    originalMetrics: CleaningMetrics | None = None
    enhancedMetrics: CleaningMetrics | None = None
    metricDeltas: dict[str, float | None] = Field(default_factory=dict)
    operations: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    report: dict = Field(default_factory=dict)
    error: str | None = None


class VocalIssue(BaseModel):
    type: str
    severity: str
    message: str


class StemVocalAnalysisResult(BaseModel):
    stemId: str
    status: str = "Pending"
    analyzedAt: str | None = None
    sourceFilePath: str | None = None
    sourceKind: str = "Original"
    confidence: int = Field(default=0, ge=0, le=100)
    summary: str | None = None
    issues: list[VocalIssue] = Field(default_factory=list)
    recommendedSettings: dict[str, float | str | bool] = Field(default_factory=dict)
    features: dict[str, float | int | str | None] = Field(default_factory=dict)
    warnings: list[str] = Field(default_factory=list)
    error: str | None = None


class StemVocalQualityDoctorResult(BaseModel):
    stemId: str
    status: str = "Pending"
    diagnosedAt: str | None = None
    score: int = Field(default=0, ge=0, le=100)
    summary: str | None = None
    problems: list[VocalIssue] = Field(default_factory=list)
    recommendedSettings: dict[str, float | str | bool] = Field(default_factory=dict)
    mixControlSuggestions: dict[str, float | str | bool] = Field(default_factory=dict)
    nextSteps: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    error: str | None = None


class Stem(BaseModel):
    id: str
    projectId: str
    originalFilename: str
    storedFilename: str
    filePath: str
    fileExtension: str
    fileSize: int
    uploadedAt: str
    status: str = "Uploaded"
    stemType: str = "Unknown"
    metadata: StemMetadata = Field(default_factory=StemMetadata)
    analysisStatus: str = "Pending"
    analysisResult: AnalysisResult | None = None
    autoBalanceSuggestion: AutoBalanceSuggestion | None = None
    detectionResult: StemDetectionResult | None = None
    stemTypeSource: str = "Unknown"
    cleaningSettings: StemCleaningSettings = Field(default_factory=StemCleaningSettings)
    cleaningStatus: str = "Not Cleaned"
    cleaningResult: StemCleaningResult | None = None
    vocalEnhancementSettings: StemVocalEnhancementSettings = Field(default_factory=StemVocalEnhancementSettings)
    vocalEnhancementStatus: str = "Not Enhanced"
    vocalEnhancementResult: StemVocalEnhancementResult | None = None
    vocalAnalysisResult: StemVocalAnalysisResult | None = None
    vocalQualityDoctorResult: StemVocalQualityDoctorResult | None = None


class MixStemSetting(BaseModel):
    stemId: str
    gainDb: float = 0
    pan: float = 0
    mute: bool = False
    solo: bool = False
    autoBalanceApplied: bool = False
    processingChainEnabled: bool = True
    reverbSend: float = 35
    delaySend: float = 0
    presenceAmount: float = 0
    compressionAmount: float = 45


class MixControls(BaseModel):
    preset: str = "Balanced"
    vocalBoost: float = 1.5
    vocalBusLevel: float = 0
    vocalGlueAmount: float = 32
    vocalDelayAmount: float = 12
    backingVocalWidth: float = 55
    drumPunch: float = 50
    bassWeight: float = 50
    brightness: float = 0
    warmth: float = 0
    width: float = 55
    reverbAmount: float = 24
    vocalReverbAmount: float = 22
    roomSize: float = 38


class MixVersionSource(BaseModel):
    stemId: str
    filename: str
    stemType: str
    sourceFilePath: str
    sourceKind: str
    gainDb: float
    pan: float
    processingChainEnabled: bool
    reverbSend: float
    delaySend: float
    presenceAmount: float
    compressionAmount: float


class MixVersion(BaseModel):
    id: str
    projectId: str
    versionNumber: int
    label: str
    preset: str
    createdAt: str
    wavPath: str
    mp3Path: str | None = None
    wavUrl: str
    mp3Url: str | None = None
    metadataPath: str | None = None
    integratedLufs: float | None = None
    peakDbfs: float | None = None
    truePeakDbfs: float | None = None
    limiterGainDb: float = 0
    targetLufsRecommendation: float | None = None
    settings: dict = Field(default_factory=dict)
    sourceFiles: list[MixVersionSource] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)


class MixSettings(BaseModel):
    stems: list[MixStemSetting] = Field(default_factory=list)
    controls: MixControls = Field(default_factory=MixControls)
    autoBalanceGeneratedAt: str | None = None
    autoBalanceAppliedAt: str | None = None
    roughMixWavPath: str | None = None
    roughMixMp3Path: str | None = None
    roughMixWavUrl: str | None = None
    roughMixMp3Url: str | None = None
    mixVersions: list[MixVersion] = Field(default_factory=list)
    latestMixVersionId: str | None = None
    updatedAt: str | None = None


class MasteringControls(BaseModel):
    selectedMixVersionId: str | None = None
    preset: str = "Streaming"
    brightness: float = 0
    warmth: float = 0
    compressionAmount: float = 45
    limiterStrength: float = 55
    stereoWidth: float = 55
    outputFormat: str = "WAV 16-bit"
    trimStartSeconds: float = 0
    trimEndSeconds: float = 0


class LoudnessReport(BaseModel):
    integratedLufs: float | None = None
    peakDbfs: float | None = None
    truePeakDbfs: float | None = None
    dynamicRangeDb: float | None = None
    clippingDetected: bool = False
    clippingSampleCount: int = 0
    clippingPercentage: float = 0
    preset: str
    outputFormat: str
    filePath: str
    timestamp: str
    targetLufs: float
    truePeakCeilingDb: float
    sourceMixVersionId: str
    sourceMixLabel: str | None = None
    inputMetrics: dict = Field(default_factory=dict)
    outputMetrics: dict = Field(default_factory=dict)
    operations: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)


class MasterVersion(BaseModel):
    id: str
    projectId: str
    versionNumber: int
    label: str
    sourceMixVersionId: str
    sourceMixLabel: str | None = None
    preset: str
    outputFormat: str
    createdAt: str
    filePath: str
    fileUrl: str
    reportJsonPath: str
    reportTxtPath: str
    reportJsonUrl: str
    reportTxtUrl: str
    targetLufs: float
    truePeakCeilingDb: float = -1.0
    integratedLufs: float | None = None
    peakDbfs: float | None = None
    truePeakDbfs: float | None = None
    dynamicRangeDb: float | None = None
    clippingDetected: bool = False
    warnings: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)
    settings: dict = Field(default_factory=dict)
    report: LoudnessReport | None = None


class ExportFile(BaseModel):
    id: str
    projectId: str
    type: str
    label: str
    sourceMixVersionId: str | None = None
    outputFormat: str | None = None
    createdAt: str
    filePath: str
    fileUrl: str
    sizeBytes: int | None = None
    includeOriginalStems: bool | None = None
    warnings: list[str] = Field(default_factory=list)


class VideoRawFile(BaseModel):
    id: str
    projectId: str
    role: str = "Primary"
    originalFilename: str
    storedFilename: str
    filePath: str
    fileUrl: str
    fileSize: int
    uploadedAt: str
    durationSeconds: float | None = None
    width: int | None = None
    height: int | None = None
    fps: float | None = None
    hasAudioTrack: bool = False


class VideoAssemblySettings(BaseModel):
    transitionStyle: str = "Crossfade"
    transitionDurationSeconds: float = 0.45
    focusPlacements: list[VideoFocusPlacement] = Field(default_factory=list)


class VideoLogoFile(BaseModel):
    id: str
    projectId: str
    originalFilename: str
    storedFilename: str
    filePath: str
    fileUrl: str
    fileSize: int
    uploadedAt: str


class VideoAudioAsset(BaseModel):
    id: str
    kind: str
    label: str
    filePath: str
    fileUrl: str
    createdAt: str | None = None
    durationSeconds: float | None = None
    outputFormat: str | None = None


class VideoOverlaySettings(BaseModel):
    songTitle: str | None = None
    artistName: str | None = None
    sessionLabel: str | None = None
    position: str = "Lower Left"
    style: str = "Boxed"
    size: str = "Medium"


class VideoWatermarkSettings(BaseModel):
    enabled: bool = False
    logo: VideoLogoFile | None = None
    position: str = "Top Right"
    opacity: float = 0.82
    scale: float = 0.14


class VideoTitleCardSettings(BaseModel):
    enabled: bool = False
    durationSeconds: float = 2.5
    title: str | None = None
    subtitle: str | None = None


class VideoAutoSyncResult(BaseModel):
    status: str = "Not Run"
    offsetMs: int | None = None
    confidence: float | None = None
    analyzedAt: str | None = None
    message: str | None = None


class VideoBrandingTemplate(BaseModel):
    id: str
    name: str
    createdAt: str
    updatedAt: str
    overlay: VideoOverlaySettings = Field(default_factory=VideoOverlaySettings)
    watermark: VideoWatermarkSettings = Field(default_factory=VideoWatermarkSettings)
    introCard: VideoTitleCardSettings = Field(default_factory=VideoTitleCardSettings)
    outroCard: VideoTitleCardSettings = Field(default_factory=VideoTitleCardSettings)


class VideoWaveformTrack(BaseModel):
    label: str
    peaks: list[float] = Field(default_factory=list)
    previewDurationSeconds: float | None = None


class VideoWaveformStateResponse(BaseModel):
    offsetMs: int = 0
    windowDurationSeconds: float | None = None
    rawVideo: VideoWaveformTrack | None = None
    selectedAudio: VideoWaveformTrack | None = None


class VideoExportFile(BaseModel):
    id: str
    projectId: str
    label: str
    createdAt: str
    filePath: str
    fileUrl: str
    sizeBytes: int | None = None
    durationSeconds: float | None = None
    width: int | None = None
    height: int | None = None
    fps: float | None = None
    sourceVideoFilename: str | None = None
    secondaryVideoFilenames: list[str] = Field(default_factory=list)
    sourceVideoFilenames: list[str] = Field(default_factory=list)
    clipCount: int = 0
    sourceAudioAssetId: str | None = None
    sourceAudioAssetLabel: str | None = None
    sourceAudioAssetKind: str | None = None
    exportPreset: str | None = None
    settings: dict = Field(default_factory=dict)
    warnings: list[str] = Field(default_factory=list)


class VideoEditorSettings(BaseModel):
    rawVideo: VideoRawFile | None = None
    rawVideos: list[VideoRawFile] = Field(default_factory=list)
    selectedAudioAssetId: str | None = None
    selectedAudioAssetKind: str | None = None
    selectedAudioAssetPath: str | None = None
    useSelectedMasterAudio: bool = True
    useOriginalVideoAudio: bool = False
    audioOffsetMs: int = 0
    trimStartSeconds: float = 0
    trimEndSeconds: float = 0
    fadeInSeconds: float = 0
    fadeOutSeconds: float = 0
    exportPreset: str = "YouTube 1080p"
    assembly: VideoAssemblySettings = Field(default_factory=VideoAssemblySettings)
    overlay: VideoOverlaySettings = Field(default_factory=VideoOverlaySettings)
    watermark: VideoWatermarkSettings = Field(default_factory=VideoWatermarkSettings)
    introCard: VideoTitleCardSettings = Field(default_factory=VideoTitleCardSettings)
    outroCard: VideoTitleCardSettings = Field(default_factory=VideoTitleCardSettings)
    autoSyncResult: VideoAutoSyncResult = Field(default_factory=VideoAutoSyncResult)
    brandingTemplates: list[VideoBrandingTemplate] = Field(default_factory=list)
    previewRender: VideoExportFile | None = None
    finalExport: VideoExportFile | None = None
    finalExports: list[VideoExportFile] = Field(default_factory=list)
    updatedAt: str | None = None


class VideoEditorStateResponse(BaseModel):
    settings: VideoEditorSettings
    availableAudioAssets: list[VideoAudioAsset] = Field(default_factory=list)


class MasteringSettings(BaseModel):
    controls: MasteringControls = Field(default_factory=MasteringControls)
    masterVersions: list[MasterVersion] = Field(default_factory=list)
    latestMasterVersionId: str | None = None
    exportFiles: list[ExportFile] = Field(default_factory=list)
    updatedAt: str | None = None


class DetectionSummary(BaseModel):
    learnedPatternCount: int = 0
    confidentPendingCount: int = 0
    acceptedCount: int = 0


class ProcessingJobError(BaseModel):
    stemId: str | None = None
    filename: str | None = None
    error: str


class ProcessingJob(BaseModel):
    id: str
    projectId: str
    type: str
    status: str
    progress: int = 0
    currentStemId: str | None = None
    message: str | None = None
    errors: list[ProcessingJobError] = Field(default_factory=list)
    createdAt: str
    updatedAt: str
    completedAt: str | None = None


class Project(BaseModel):
    id: str
    name: str
    artistName: str | None = None
    songTitle: str | None = None
    notes: str | None = None
    createdAt: str
    updatedAt: str
    status: str
    stems: list[Stem] = Field(default_factory=list)
    processingJobs: list[ProcessingJob] = Field(default_factory=list)
    mixSettings: MixSettings = Field(default_factory=MixSettings)
    masteringSettings: MasteringSettings = Field(default_factory=MasteringSettings)
    videoEditorSettings: VideoEditorSettings = Field(default_factory=VideoEditorSettings)
    detectionSummary: DetectionSummary = Field(default_factory=DetectionSummary)


class ProjectListItem(BaseModel):
    id: str
    name: str
    artistName: str | None = None
    songTitle: str | None = None
    createdAt: str
    updatedAt: str
    status: str
    stemCount: int


class UploadError(BaseModel):
    filename: str
    error: str


class UploadResponse(BaseModel):
    uploaded: list[Stem]
    errors: list[UploadError]


class AudioInputDevice(BaseModel):
    id: int
    name: str
    hostApi: str
    maxInputChannels: int
    defaultSampleRate: int
    isDefault: bool = False
    isZoomDevice: bool = False


class AudioInputDeviceListResponse(BaseModel):
    devices: list[AudioInputDevice] = Field(default_factory=list)


class StartDirectRecordingRequest(BaseModel):
    deviceId: int
    channelCount: int | None = Field(default=None, ge=1, le=64)
    sampleRate: int | None = Field(default=None, ge=8000, le=192000)
    splitToMono: bool = True
    baseName: str | None = Field(default=None, max_length=80)


class DirectRecordingStatus(BaseModel):
    projectId: str
    active: bool = False
    status: str = "Idle"
    sessionId: str | None = None
    deviceId: int | None = None
    deviceName: str | None = None
    hostApi: str | None = None
    channelCount: int | None = None
    sampleRate: int | None = None
    splitToMono: bool = True
    startedAt: str | None = None
    durationSeconds: float = 0
    framesCaptured: int = 0
    multitrackFilePath: str | None = None
    multitrackFileUrl: str | None = None
    error: str | None = None


class StopDirectRecordingResponse(BaseModel):
    recording: DirectRecordingStatus
    uploaded: list[Stem] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)


class RoughMixResponse(BaseModel):
    wavPath: str
    mp3Path: str | None = None
    wavUrl: str
    mp3Url: str | None = None
    peakDbfs: float
    limiterGainDb: float


def validate_stem_type(stem_type: str) -> bool:
    return stem_type in STEM_TYPES


def validate_cleaning_mode(mode: str) -> bool:
    return mode in {"Off", "Light", "Medium", "Strong"}


def validate_vocal_enhancer_preset(preset: str) -> bool:
    return preset in VOCAL_ENHANCER_PRESETS


def validate_pitch_correction_mode(mode: str) -> bool:
    return mode in PITCH_CORRECTION_MODES


def validate_vocal_fx_style(style: str) -> bool:
    return style in VOCAL_FX_STYLES


def validate_music_key(key: str) -> bool:
    return key in MUSIC_KEYS


def validate_music_scale(scale: str) -> bool:
    return scale in MUSIC_SCALES
