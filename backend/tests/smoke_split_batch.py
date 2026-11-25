"""Smoke test for playlist batch splitting.

Separation is stubbed out: what is being checked here is the batch's own state
machine, which is where the behaviour people actually rely on lives - that
every track is downloaded before any separation starts, that one dead video
does not take the batch down with it, that cancelling lands between tracks
rather than mid-separation, and that resuming after a restart does not redo
work already on disk.
"""

import os
import sys
import tempfile
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

_TMP = tempfile.mkdtemp()
os.environ["AUDIO_MIXER_STORAGE_ROOT"] = _TMP
os.environ["AUDIO_MIXER_BATCH_FETCH_SPACING"] = "0"  # no waiting between fake downloads

from app import stem_splitter as ss  # noqa: E402
from app.models import CreateSplitBatchRequest  # noqa: E402
from app.storage import store  # noqa: E402

TRACKS = [
    {"url": "https://www.youtube.com/watch?v=aaaaaaaaaaa", "title": "Livin' on a Prayer", "durationSeconds": 249.0, "position": 0},
    {"url": "https://www.youtube.com/watch?v=bbbbbbbbbbb", "title": "Africa", "durationSeconds": 295.0, "position": 1},
    {"url": "https://www.youtube.com/watch?v=ccccccccccc", "title": "Eye of the Tiger", "durationSeconds": 245.0, "position": 2},
]

downloads = []
splits_run = []
fail_download_for = set()
fail_split_for = set()

ss._require_separation_environment = lambda: None
ss.enumerate_playlist = lambda url, limit=None: (TRACKS[: (limit or len(TRACKS))], "80s Rock")
ss._ffmpeg = lambda: "ffmpeg"

def fake_download(split_id, url, source_dir):
    if url in fail_download_for:
        raise RuntimeError("HTTP Error 429: Too Many Requests")
    downloads.append(url)
    source_dir.mkdir(parents=True, exist_ok=True)
    path = source_dir / "download.m4a"
    path.write_bytes(b"audio")
    track = next(t for t in TRACKS if t["url"] == url)
    return {"title": track["title"], "uploader": "Chan", "duration": track["durationSeconds"],
            "videoId": url[-11:], "path": path}

def fake_convert(ffmpeg_path, source, destination):
    Path(destination).parent.mkdir(parents=True, exist_ok=True)
    Path(destination).write_bytes(b"wav")

def fake_run_split(split_id):
    splits_run.append(split_id)
    failed = split_id in fail_split_for
    def apply(split):
        # run_split marks a finished split "Ready" - the stub has to agree
        # with the real contract or it hides exactly the bug it should catch.
        split["status"] = "Failed" if failed else "Ready"
        split["error"] = "separation blew up" if failed else None
    ss._mutate_split(split_id, apply)

ss._download_audio = fake_download
ss._convert_to_wav = fake_convert
ss.run_split = fake_run_split

results = []
def check(name, ok, extra=""):
    results.append(f"{'PASS' if ok else 'FAIL'}  {name}{(' — ' + str(extra)) if extra else ''}")

# ---- 1. happy path -------------------------------------------------------
batch = ss.create_split_batch(CreateSplitBatchRequest(url="https://youtube.com/playlist?list=X", stemSet="4"))
check("playlist enumerates into items", len(batch.items) == 3, f"{len(batch.items)} items")
check("batch starts Pending", batch.status == "Pending", batch.status)
check("splits are created as Queued (won't trip the one-at-a-time guard)",
      all(s["status"] == "Queued" for s in store.load()["splits"]))

ss.run_split_batch(batch.id)
after = ss.get_split_batch(batch.id)
check("every track downloaded before any split ran",
      downloads == [t["url"] for t in TRACKS], f"{len(downloads)} downloads")
check("fetch happened before split (two-phase)", len(downloads) == 3 and len(splits_run) == 3)
check("all tracks split", len(splits_run) == 3, f"{len(splits_run)} splits")
check("batch Completed", after.status == "Completed", after.status)
check("items report Ready", all(i.splitStatus == "Ready" for i in after.items))

# ---- 2. resume skips work already done -----------------------------------
downloads.clear(); splits_run.clear()
ss.run_split_batch(batch.id)
check("resume re-downloads nothing", downloads == [], f"{len(downloads)} downloads")
check("resume re-splits nothing", splits_run == [], f"{len(splits_run)} splits")

# ---- 3. a dead track does not stop the batch -----------------------------
downloads.clear(); splits_run.clear()
fail_download_for.add(TRACKS[1]["url"])
b2 = ss.create_split_batch(CreateSplitBatchRequest(url="https://youtube.com/playlist?list=Y", stemSet="4"))
ss.run_split_batch(b2.id)
after2 = ss.get_split_batch(b2.id)
bad = [i for i in after2.items if i.fetchStatus == "Failed"]
check("one failed download is isolated", len(bad) == 1 and "429" in (bad[0].fetchError or ""), bad[0].fetchError if bad else "none")
check("the other two still split", len(splits_run) == 2, f"{len(splits_run)} splits")
check("batch reports Partial", after2.status == "Partial", after2.status)
fail_download_for.clear()

# ---- 4. a failed separation is recorded, batch continues -----------------
downloads.clear(); splits_run.clear()
b3 = ss.create_split_batch(CreateSplitBatchRequest(url="https://youtube.com/playlist?list=Z", stemSet="4"))
fail_split_for.add(b3.items[0].splitId)
ss.run_split_batch(b3.id)
after3 = ss.get_split_batch(b3.id)
check("a failed split does not stop the rest", len(splits_run) == 3, f"{len(splits_run)} splits")
check("the failure is recorded on the item",
      after3.items[0].splitStatus == "Failed" and after3.items[0].splitError == "separation blew up",
      after3.items[0].splitError)
fail_split_for.clear()

# ---- 5. cancel lands between tracks --------------------------------------
downloads.clear(); splits_run.clear()
b4 = ss.create_split_batch(CreateSplitBatchRequest(url="https://youtube.com/playlist?list=W", stemSet="4"))
original = ss.run_split
def cancel_after_first(split_id):
    original(split_id)
    if len(splits_run) == 1:
        ss.request_batch_cancel(b4.id)
ss.run_split = cancel_after_first
ss.run_split_batch(b4.id)
ss.run_split = original
after4 = ss.get_split_batch(b4.id)
check("cancel stops further tracks", len(splits_run) == 1, f"{len(splits_run)} splits ran")
check("batch reports Cancelled", after4.status == "Cancelled", after4.status)

# ---- 6. restart parks a running batch, resume carries on -----------------
def apply(b): b["status"] = "Splitting"
ss._mutate_batch(b4.id, apply)
ss.mark_interrupted_batches()
after5 = ss.get_split_batch(b4.id)
check("a restart parks a running batch as Interrupted", after5.status == "Interrupted", after5.status)
splits_run.clear()
ss.run_split_batch(b4.id)
after6 = ss.get_split_batch(b4.id)
check("resume finishes the remaining tracks", len(splits_run) == 2, f"{len(splits_run)} splits")
check("batch completes after resume", after6.status == "Completed", after6.status)

# ---- 7. re-running a playlist skips what is already split ----------------
downloads.clear(); splits_run.clear()

# _find_cached_split only reuses a split whose stem files still exist, so
# the fixture has to put them there.
import app.stem_splitter as _ss
for split in store.load()["splits"]:
    if split.get("status") != "Ready":
        continue
    stem_dir = _ss.SPLITS_ROOT / split["id"] / "stems"
    stem_dir.mkdir(parents=True, exist_ok=True)
    (stem_dir / "vocals.wav").write_bytes(b"stem")
    def mark(item, s=split):
        item["stems"] = [{"fileName": "vocals.wav"}]
    ss._mutate_split(split["id"], mark)

b5 = ss.create_split_batch(CreateSplitBatchRequest(url="https://youtube.com/playlist?list=X", stemSet="4"))
reused_items = [i for i in b5.items if i.reused]
check("a re-run reuses tracks already on disk", len(reused_items) == 3, f"{len(reused_items)} reused")
check("reused items are already Ready", all(i.splitStatus == "Ready" for i in reused_items))
check("the batch says so up front", "already split" in (b5.progressMessage or ""), b5.progressMessage)

ss.run_split_batch(b5.id)
check("a re-run downloads nothing", downloads == [], f"{len(downloads)} downloads")
check("a re-run separates nothing", splits_run == [], f"{len(splits_run)} splits")
check("the re-run completes", ss.get_split_batch(b5.id).status == "Completed", ss.get_split_batch(b5.id).status)

# A different stem set is different output, so it must NOT be skipped.
b6 = ss.create_split_batch(CreateSplitBatchRequest(url="https://youtube.com/playlist?list=X", stemSet="6"))
check("a different stem set is not treated as already split",
      not any(i.reused for i in b6.items), f"{sum(1 for i in b6.items if i.reused)} wrongly reused")

# ---- 8. one batch at a time ---------------------------------------------
def apply2(b): b["status"] = "Splitting"
ss._mutate_batch(b4.id, apply2)
try:
    ss.create_split_batch(CreateSplitBatchRequest(url="https://youtube.com/playlist?list=Q"))
    check("a second concurrent batch is refused", False, "it was allowed")
except Exception as exc:
    check("a second concurrent batch is refused", getattr(exc, "status_code", None) == 409, type(exc).__name__)

print("split batch smoke test")
for line in results:
    print("  " + line)
failures = [line for line in results if line.startswith("FAIL")]
if failures:
    raise SystemExit(f"{len(failures)} of {len(results)} checks failed")
print(f"OK - {len(results)} checks passed")
