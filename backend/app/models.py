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


class GenerateMasterRequest(BaseModel):
    selectedMixVersionId: str
    preset: str
    outputFormat: str
    brightness: float = Field(default=0, ge=-50, le=50)
    warmth: float = Field(default=0, ge=-50, le=50)
    compressionAmount: float = Field(default=45, ge=0, le=100)
    limiterStrength: float = Field(default=55, ge=0, le=100)
    stereoWidth: float = Field(default=55, ge=0, le=100)


class ExportMixRequest(BaseModel):
    selectedMixVersionId: str
    outputFormat: str


class ProjectBackupRequest(BaseModel):
    includeOriginalStems: bool = False


class UpdateCleaningSettingsRequest(BaseModel):
    enabled: bool | None = None
    mode: str | None = None
    humRemoval: bool | None = None
    humFrequency: int | None = Field(default=None, ge=50, le=60)
    useCleanedInMix: bool | None = None


VOCAL_ENHANCER_PRESETS = [
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
    preset: str = "Natural Clean"
    pitchCorrection: str = "Off"
    key: str = "Auto"
    scale: str = "Major"
    fxStyle: str = "Natural Plate"
    fxAmount: float = 25
    bodyAmount: float = 0
    presenceAmount: float = 0
    airAmount: float = 0
    deEssAmount: float = 50
    compressionAmount: float = 50
    riderAmount: float = 50
    saturationAmount: float = 50
    doublerAmount: float = 50
    breathReductionAmount: float = 35
    mouthClickReductionAmount: float = 30
    pitchStrength: float = 50
    pitchHumanize: float = 60
    useEnhancedInMix: bool = True


class StemVocalEnhancementResult(BaseModel):
    stemId: str
    status: str = "Pending"
    enhancedAt: str | None = None
    sourceFilePath: str | None = None
    sourceKind: str = "Original"
    enhancedFilePath: str | None = None
    enhancedFileUrl: str | None = None
    preset: str = "Natural Clean"
    pitchCorrection: str = "Off"
    key: str = "Auto"
    scale: str = "Major"
    fxStyle: str = "Natural Plate"
    fxAmount: float = 25
    bodyAmount: float = 0
    presenceAmount: float = 0
    airAmount: float = 0
    deEssAmount: float = 50
    compressionAmount: float = 50
    riderAmount: float = 50
    saturationAmount: float = 50
    doublerAmount: float = 50
    breathReductionAmount: float = 35
    mouthClickReductionAmount: float = 30
    pitchStrength: float = 50
    pitchHumanize: float = 60
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
    compressionAmount: float = 50


class MixControls(BaseModel):
    preset: str = "Balanced"
    vocalBoost: float = 1.5
    vocalBusLevel: float = 0
    vocalGlueAmount: float = 45
    vocalDelayAmount: float = 25
    backingVocalWidth: float = 60
    drumPunch: float = 50
    bassWeight: float = 50
    brightness: float = 0
    warmth: float = 0
    width: float = 55
    reverbAmount: float = 35
    vocalReverbAmount: float = 35
    roomSize: float = 45


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
