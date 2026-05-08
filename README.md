# Sixram Band Studio - Local Stem Mixer AI

Local-only React/FastAPI app for uploading stems, analyzing, cleaning, enhancing vocals, mixing, mastering, and exporting.

## Run Locally

Backend:

```powershell
.\run-backend.ps1
```

If PowerShell blocks local scripts, run `.\run-backend.cmd` instead.

The script creates `backend\.venv` if needed, installs `backend\requirements.txt`
when it changes, and starts FastAPI at `http://127.0.0.1:8000`.

Frontend:

```powershell
cd frontend
npm install
npm run dev
```

Open `http://127.0.0.1:5173`.

## Required Tools

- Python virtual environment with backend requirements installed
- Node.js/npm for the frontend
- ffmpeg available through `imageio-ffmpeg` or system PATH

## Local Storage

Original files are never overwritten. Project files are stored under:

```text
storage/projects/{projectId}/original/
storage/projects/{projectId}/processed/cleaned/
storage/projects/{projectId}/processed/vocals/
storage/projects/{projectId}/processed/mixes/
storage/projects/{projectId}/exports/
storage/projects/{projectId}/logs/
```

## Workflow

Dashboard -> Upload -> Analyze/Detect -> Cleaning -> Vocal Enhancer -> Mixer -> Mastering/Export

## Workflow Time Reference

Typical upload-to-master timing for a 3-5 minute song:

- Fast path without cleaning or vocal polish: 3-8 minutes
- Normal full workflow: 10-25 minutes
- Many stems, dirty vocals, or strong cleanup: 30-45+ minutes

Step estimates:

- Upload: seconds to 2 minutes
- Analyze/detect: 1-3 minutes
- Cleaning: 2-10 minutes
- Vocal enhancement: 1-5 minutes per vocal stem
- Mixer render: 30 seconds to 2 minutes
- Master/export: 1-4 minutes

The biggest variables are song length, number of stems, cleaning strength, number of vocal stems, pitch processing, and local CPU speed.

## Phase 7 Vocal Enhancer

The Vocal Enhancer creates versioned, non-destructive enhanced vocal stems under `processed/vocals/`.

Presets:

- Natural Clean
- AI Studio Clear
- Suno-Style Lead
- Pop Vocal
- Worship Lead
- Live Vocal Fix
- Bright AI Polish
- Warm Ballad
- Backing Vocal Wide

Controls:

- Enable per vocal stem
- Analyze vocal recommendations before rendering
- Use enhanced vocal in mix
- Preset
- Pitch polish: Off, Natural, Medium, Strong
- Key and scale
- Vocal FX style: Dry, Natural Plate, Small Hall, Slap Delay, Quarter Delay, Worship Wide
- Vocal FX amount
- Fine-tune controls: Body, Presence, Air, De-ess, Compression, Vocal Rider, Saturation, Doubler
- Repair controls: Breath Softener and Mouth Clicks
- Pitch controls: Strength and Humanize
- Key-aware vocal recommendations and Apply All recommendations
- Before/after vocal report after each render
- Custom vocal preset save/apply/delete for reusable local settings
- A/B in mix context preview using the latest mix as a quiet backing bed
- Source/enhanced A/B preview
- Loudness-matched A/B preview attenuation when LUFS metrics are available

The recommendation pass checks vocal tone, sibilance, harshness, muddiness, noise floor, level spread, clipping, silence, loudness, and estimated key/scale. It saves a separate recommendation on each vocal stem and only changes enhancer settings when you click `Apply Recommendation` or `Apply All`.

The mixer uses enhanced vocals first when enabled and completed, then cleaned stems, then originals. The advanced mixer also includes vocal bus controls for vocal level, glue compression, delay, and backing vocal width.

## Test Commands

```powershell
backend\.venv\Scripts\python.exe -m compileall backend\app backend\tests
backend\.venv\Scripts\python.exe backend\tests\smoke_phase4.py
backend\.venv\Scripts\python.exe backend\tests\smoke_phase5.py
backend\.venv\Scripts\python.exe backend\tests\smoke_phase6.py
backend\.venv\Scripts\python.exe backend\tests\smoke_phase7.py
backend\.venv\Scripts\python.exe backend\tests\smoke_hardening.py
cd frontend
npm run build
```
