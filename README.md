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

## Stem Splitter (Phase 8)

A standalone module at `/stem-splitter`, reached from the header nav. It is
separate from the mix and mastering workflow and never touches project data.

Paste a media URL, pick a stem set, and the backend downloads the audio,
separates it with Demucs, and opens a player where each instrument has mute,
solo and a level fader. Stems download individually, or as a custom mixdown.

### Enabling it

Separation dependencies are optional on purpose. Without them the backend still
starts, the whole mix and mastering flow works normally, and only the Stem
Splitter page reports what is missing.

```powershell
backend\.venv\Scripts\python.exe -m pip install torch --index-url https://download.pytorch.org/whl/cpu
backend\.venv\Scripts\python.exe -m pip install -r backend\requirements-splitter.txt
```

Install torch from the CPU index first, or pip pulls the much larger CUDA build.
The model weights (~300 MB) download on the first split.

### Stem sets

- 6 stems: vocals, drums, bass, guitar, piano, other (`htdemucs_6s`)
- 4 stems: vocals, drums, bass, other (`htdemucs`) - faster, and every stem is
  cleaner because the model is not trying to pull guitar and piano apart

### What to expect

Separation is CPU-bound and runs one split at a time. Measured on a 12th Gen
Core i7-1255U (10 threads): a 5:32 song separated into 6 stems in 6.2 minutes,
about 1.1x realtime. The job runs in the background and survives leaving the
page. Results are cached by video ID, so re-splitting the
same link is instant.

Vocals, drums and bass separate well. Guitar is usable. Piano is the weakest
source and carries audible bleed - the Demucs authors flag this themselves. The
player marks limited stems so the quality expectation is visible in the UI.

Splits are stored under:

```text
storage/splits/{splitId}/source/
storage/splits/{splitId}/stems/
storage/splits/{splitId}/preview/
storage/splits/{splitId}/exports/
storage/splits/{splitId}/logs/
```

### Test command

```powershell
backend\.venv\Scripts\python.exe backend\tests\smoke_phase8.py
```

## Chord Sheet (Phase 9)

A chord chart for any song you have already split, reached from the `Chord
sheet` button on a split card. It is a consumer of the Stem Splitter, not a
second pipeline: a sheet holds a `splitId` and reads the stems that split
already produced, so downloading, separating and caching all come for free and
a song that has been split before analyses in seconds.

Analysis needs `librosa`, which is already in `requirements.txt`. It does not
need torch or demucs - those are only required if the link has never been
split, because then a split has to be made first.

### What it detects

- **Chords** - beat-synchronous chroma against harmonically weighted triad
  templates, smoothed with Viterbi over a circle-of-fifths transition prior.
  Major and minor triads only.
- **A confidence per chord** - the margin between the winner and the runner-up
  on the raw evidence, before smoothing. The UI dims anything below the
  threshold and marks it for checking. This is the number to watch: a chart
  that is 70% right is only useful if it can say which 30% to distrust.
- **Key** - estimated twice, from the chord histogram and from the chroma
  profile. Agreement between the two is itself a confidence signal. The key
  also decides whether the sheet reads in sharps or flats.
- **Tempo and the beat grid** - tracked on the isolated drum stem, seeded from
  its own tempo curve so it cannot land an octave out.
- **Reference pitch** - the recording's offset from A440 in cents, and whether
  that offset holds across the track. A steady offset is a tuning reference; a
  drifting one means the upload was speed-changed.

### What it does not detect

**Guitar tuning.** Chords are recognised as sounding pitches, which are correct
whatever the guitar is tuned to - tuning only changes which shape a player
fingers. Inferring that shape from a mix is not reliable, because a flat key
scores exactly like a detuned guitar and separation bleed regularly puts energy
below a guitar's low E. So standard tuning is always assumed, alternatives are
offered with their open-shape coverage, and you choose.

### Transpose, capo and tuning

All three are the same operation - one semitone shift applied when the sheet is
rendered - so they never re-analyse anything and come back instantly. Spelling
follows the key you end up reading in, not the one the song was recorded in: G
minor transposed up a semitone prints C#m, not Dbm.

The canonical format is ChordPro, which is what makes that cheap. Exports write
`.pro` and `.txt` into the sheet's exports folder.

### What to expect

Simple strummed pop, folk and worship: mostly right, a few fixes. A full rock
mix: the progression right, the details wrong. Jazz and anything with
extensions: not usable. Treat the output as a first draft.

Measured on the reference split (Toto - Rosanna, 5:32, 6 stems): analysed in
about 30 seconds, roughly 11x realtime, on a cached split.

Sheets are stored under:

```text
storage/chordsheets/{sheetId}/analysis/
storage/chordsheets/{sheetId}/sheet/
storage/chordsheets/{sheetId}/exports/
storage/chordsheets/{sheetId}/logs/
```

Deleting a split does not delete its chord sheet. The sheet keeps its chords
and any corrections; it only loses the stems behind it.

### Lyrics

A sheet starts as a chord chart. `Find lyrics` looks the track up on
[LRCLIB](https://lrclib.net) by artist, title and duration, derived from the
video title; a match comes back time-synced and the chords are laid over the
words. No key or account is needed.

No match is the ordinary outcome for local, regional and unreleased material,
and the answer then is `Paste lyrics`, not a guess. Plain lines work; LRC
timestamps (`[01:20.70] the words`) place the chords far more accurately. Both
paths produce the same thing, so nothing downstream can tell them apart.

There is deliberately **no speech recognition**. Whisper on sung vocals runs
around 21% word error rate even at large, and source separation does not
improve it - the artifacts cancel out the reduced interference. A draft where
one word in five is wrong costs more to correct than pasting the real words.

Chord positions within a line are proportional to time: a chord a third of the
way through a line's duration sits about a third of the way along its text.
That is an approximation rather than forced alignment, but chord changes
cluster at line starts anyway, so it reads correctly far more often than it
misses. Stretches with no singing - intros, solos, outros - become their own
chord-only rows instead of being absorbed by the nearest line.

With lyrics attached, the ChordPro export switches to inline chords
(`[Bb]Counting out the [F]hours`) and the text export prints chords above
words.

### Probe script

`tools/chord_probe.py` runs the same analysis straight from a split directory
and prints the chart to the terminal, with no backend or database involved. It
is the fastest way to judge accuracy on a new song:

```powershell
backend\.venv\Scripts\python.exe tools\chord_probe.py storage\splits\<splitId>
```

### Test command

```powershell
backend\.venv\Scripts\python.exe backend\tests\smoke_phase9.py
```

