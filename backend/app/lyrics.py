"""Phase 9b - lyrics for a chord sheet.

Lyrics come from LRCLIB, a free crowd-sourced database of time-synced lyrics.
No key, no account, and the text is human-entered, so when it has the track the
words are simply right. That is worth far more than transcribing the vocal stem:
Whisper on sung vocals runs around 21% word error rate even at large, and a
draft where one word in five is wrong costs more to fix than it saves.

When LRCLIB has no match the answer is to paste the words in, not to guess at
them. Both paths land in the same place, so the rest of the app cannot tell
them apart.

Everything here fails soft. A sheet without lyrics is still a usable chord
chart, so a lookup that times out or comes back in an unexpected shape leaves
the sheet exactly as it was.
"""

from __future__ import annotations

import json
import re
import urllib.error
import urllib.parse
import urllib.request

LRCLIB_BASE = "https://lrclib.net"
# LRCLIB asks clients to identify themselves rather than send a generic agent.
USER_AGENT = "SixramBandStudio/0.9 (local stem mixer; chord sheet module)"
TIMEOUT_SECONDS = 12

# Junk that video titles carry and track databases do not.
_TITLE_NOISE = re.compile(
    r"""\s*(?:
        \((?:[^()]*?(?:official|video|audio|lyric|lyrics|hd|hq|4k|remaster(?:ed)?|
            live|mv|m/v|visualizer|explicit|clean|full|album\s+version)[^()]*?)\)
      | \[(?:[^\[\]]*?(?:official|video|audio|lyric|lyrics|hd|hq|4k|remaster(?:ed)?|
            live|mv|m/v|visualizer|explicit|clean|full)[^\[\]]*?)\]
      | \b(?:official\s+(?:music\s+)?video|official\s+audio|lyric\s+video|
            music\s+video|audio\s+only)\b
    )""",
    re.IGNORECASE | re.VERBOSE,
)

_FEATURING = re.compile(r"\s*[\(\[]?\b(?:feat\.?|ft\.?|featuring)\b[^\)\]]*[\)\]]?", re.IGNORECASE)

# The dashes uploaders actually use between artist and title.
_SPLITTERS = (" - ", " – ", " — ", " ~ ", " | ")

# [mm:ss.xx] or [mm:ss] - a line may carry several when it repeats.
_LRC_STAMP = re.compile(r"\[(\d{1,3}):(\d{2})(?:[.:](\d{1,3}))?\]")
# [ar: ...] and friends, which are metadata rather than a lyric line.
_LRC_META = re.compile(r"^\[[a-z]{2,}:.*\]$", re.IGNORECASE)
# [Verse 1] / [Chorus] / [Bridge] style section headings in pasted lyrics.
_SECTION_MARKER_RE = re.compile(r"^\s*\[([A-Z][^\[\]\n]{1,40})\]\s*$", re.MULTILINE)
# Same pattern used inside the Genius page scraper.
_GENIUS_SECTION_RE = re.compile(
    r"^\s*\[([A-Z][^\[\]\n]{1,40})\]\s*$"
    r"(?:\n[ \t]*)*"               # skip blank / whitespace-only lines
    r"([A-Za-z\"\'\(][^\[\]\n]{0,120})?",  # first lyric line (optional)
    re.MULTILINE,
)


def _genius_sections(track: str, artist: str | None, timeout: int = 8) -> list[dict] | None:
    """
    Fetch song-section structure from Genius (best-effort, never raises).

    Returns [{"label": "Verse 1", "firstLine": "..."}, ...] in song order,
    with firstLine="" for instrumental sections that carry no sung words.
    Returns None on any network error or when the song cannot be found.
    """
    query = f"{artist} {track}".strip() if artist else track
    encoded = urllib.parse.quote(query)
    # Genius's multi-search endpoint works without an OAuth token.
    search_url = f"https://genius.com/api/search/multi?per_page=3&q={encoded}"
    try:
        req = urllib.request.Request(
            search_url,
            headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        song_url: str | None = None
        for section in data.get("response", {}).get("sections", []):
            if section.get("type") == "song":
                hits = section.get("hits", [])
                if hits:
                    song_url = hits[0]["result"]["url"]
                    break
        # Basic SSRF guard.
        if not song_url or not song_url.startswith("https://genius.com/"):
            return None
    except Exception:
        return None

    try:
        page_req = urllib.request.Request(
            song_url,
            headers={
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/120.0.0.0 Safari/537.36"
                ),
                "Accept": "text/html,application/xhtml+xml",
                "Accept-Language": "en-US,en;q=0.9",
            },
        )
        with urllib.request.urlopen(page_req, timeout=timeout + 2) as resp:
            html = resp.read().decode("utf-8", errors="replace")
    except Exception:
        return None

    # Strip <script> and <style> blocks first so their content (which may
    # contain '[...]' patterns) doesn't pollute the section detection.
    html = re.sub(r"<script[^>]*>.*?</script>", "", html, flags=re.DOTALL | re.IGNORECASE)
    html = re.sub(r"<style[^>]*>.*?</style>", "", html, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r"<[^>]+>", "\n", html)
    for entity, char in [
        ("&amp;", "&"), ("&lt;", "<"), ("&gt;", ">"),
        ("&#x27;", "'"), ("&quot;", '"'), ("&#39;", "'"), ("&nbsp;", " "),
    ]:
        text = text.replace(entity, char)

    sections: list[dict] = []
    for match in _GENIUS_SECTION_RE.finditer(text):
        label = match.group(1).strip()
        first_line = (match.group(2) or "").strip()
        sections.append({"label": label, "firstLine": first_line})

    return sections or None


def _extract_pasted_sections(text: str) -> list[dict]:
    """
    Pull [Section] markers out of pasted lyrics text (Genius-style format).

    Returns sections in order: [{"label": "Verse 1", "firstLine": "..."}, ...].
    The firstLine is the first actual lyric line after the marker (empty string
    when the section is purely instrumental and no lyric follows).
    """
    sections: list[dict] = []
    lines = text.splitlines()
    for i, line in enumerate(lines):
        m = re.fullmatch(r"\s*\[([A-Z][^\[\]]{1,40})\]\s*", line)
        if not m:
            continue
        label = m.group(1).strip()
        first_line = ""
        for j in range(i + 1, min(i + 6, len(lines))):
            candidate = _LRC_STAMP.sub("", lines[j]).strip()
            if candidate and not re.fullmatch(r"\[[^\[\]]+\]", candidate):
                first_line = candidate
                break
        sections.append({"label": label, "firstLine": first_line})
    return sections


def _add_genius_sections(result: dict, track: str, artist: str | None) -> dict:
    """Augment a lyrics dict with Genius song-structure (best-effort)."""
    track_name = (result.get("trackName") or track or "").strip()
    artist_name = (result.get("artistName") or artist or "").strip() or None
    result["sections"] = _genius_sections(track_name, artist_name) or [] if track_name else []
    return result


def clean_title(raw: str) -> tuple[str | None, str]:
    """Pull an artist and a track name out of a video title.

    'Toto - Rosanna (Official HD Video)' becomes ('Toto', 'Rosanna'). When there
    is no separator the whole thing is the track name and the artist is left to
    the caller, who may know it from the uploader.
    """
    text = _TITLE_NOISE.sub("", raw or "")
    text = _FEATURING.sub("", text)
    text = re.sub(r"\s{2,}", " ", text).strip(" -–—|~\t")

    for splitter in _SPLITTERS:
        if splitter in text:
            left, right = text.split(splitter, 1)
            left, right = left.strip(), right.strip()
            if left and right:
                return left, right
    return None, text


def parse_lrc(text: str) -> list[dict]:
    """Turn an LRC document into timed lines, in order.

    A stamped line may carry several timestamps when the same words repeat; each
    one becomes its own line. Metadata tags and empty stamps are dropped.
    """
    lines: list[dict] = []
    for raw in (text or "").splitlines():
        raw = raw.rstrip()
        if not raw or _LRC_META.match(raw.strip()):
            continue

        stamps = list(_LRC_STAMP.finditer(raw))
        if not stamps:
            continue

        body = _LRC_STAMP.sub("", raw).strip()
        for stamp in stamps:
            minutes, seconds, fraction = stamp.group(1), stamp.group(2), stamp.group(3)
            total = int(minutes) * 60 + int(seconds)
            if fraction:
                total += int(fraction) / (10 ** len(fraction))
            lines.append({"startSeconds": round(float(total), 3), "text": body})

    lines.sort(key=lambda line: line["startSeconds"])
    for index, line in enumerate(lines):
        line["index"] = index
    return lines


def parse_plain(text: str) -> list[dict]:
    """Untimed lyrics. Kept in order, with no timing claimed for them."""
    lines = []
    for raw in (text or "").splitlines():
        body = raw.strip()
        lines.append({"index": len(lines), "startSeconds": None, "text": body})
    while lines and not lines[-1]["text"]:
        lines.pop()
    return lines


def _request(path: str, params: dict) -> object | None:
    url = f"{LRCLIB_BASE}{path}?{urllib.parse.urlencode(params)}"
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            return None  # a clean miss, not a failure
        raise
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, UnicodeDecodeError):
        return None


def _usable(record: object, duration: float | None) -> dict | None:
    """Accept a record only if it actually carries words for roughly this song."""
    if not isinstance(record, dict):
        return None
    if record.get("instrumental"):
        return None
    synced = record.get("syncedLyrics") or ""
    plain = record.get("plainLyrics") or ""
    if not synced.strip() and not plain.strip():
        return None
    # A match whose length is far off is a different recording - a live cut, an
    # edit, a different release - and its timings would not fit this audio.
    if duration and record.get("duration"):
        try:
            if abs(float(record["duration"]) - float(duration)) > 15:
                return None
        except (TypeError, ValueError):
            pass
    return record


def fetch_from_lrclib(track: str, artist: str | None, duration: float | None, album: str | None = None) -> dict | None:
    """Exact lookup first, then a search. Returns None when nothing fits.

    Network failures are swallowed on purpose: a sheet with no lyrics is a
    working chord chart, and this should never be the thing that breaks it.
    """
    if not track:
        return None

    if artist:
        params = {"artist_name": artist, "track_name": track}
        if album:
            params["album_name"] = album
        if duration:
            params["duration"] = int(round(duration))
        try:
            record = _usable(_request("/api/get", params), duration)
        except Exception:
            record = None
        if record:
            return _add_genius_sections(_shape(record, "lrclib-exact"), track, artist)

    query = f"{artist} {track}".strip() if artist else track
    try:
        results = _request("/api/search", {"q": query})
    except Exception:
        results = None

    if isinstance(results, list):
        # Prefer a synced match, then the closest duration.
        scored = []
        for item in results[:20]:
            record = _usable(item, duration)
            if not record:
                continue
            synced = bool((record.get("syncedLyrics") or "").strip())
            gap = abs(float(record.get("duration") or 0) - float(duration or 0)) if duration else 0
            scored.append((not synced, gap, record))
        if scored:
            scored.sort(key=lambda row: (row[0], row[1]))
            return _add_genius_sections(_shape(scored[0][2], "lrclib-search"), track, artist)

    return None


def _shape(record: dict, source: str) -> dict:
    synced = (record.get("syncedLyrics") or "").strip()
    plain = (record.get("plainLyrics") or "").strip()
    lines = parse_lrc(synced) if synced else parse_plain(plain)
    return {
        "source": source,
        "synced": bool(synced),
        "trackName": record.get("trackName"),
        "artistName": record.get("artistName"),
        "albumName": record.get("albumName"),
        "duration": record.get("duration"),
        "lines": lines,
        "sections": [],  # populated by _add_genius_sections() after this call
    }


def from_pasted(text: str) -> dict:
    """Lyrics the user typed or pasted. LRC timestamps are honoured if present.

    If the text includes Genius-style section markers ([Verse 1], [Chorus], …)
    they are extracted as section structure and stripped from the lyric lines
    so they don't appear as sung words.
    """
    body = text or ""
    sections = _extract_pasted_sections(body)
    if sections:
        # Remove the marker lines before parsing so they don't become lyric rows.
        body = _SECTION_MARKER_RE.sub("", body)
    synced = bool(_LRC_STAMP.search(body))
    return {
        "source": "manual",
        "synced": synced,
        "trackName": None,
        "artistName": None,
        "albumName": None,
        "duration": None,
        "lines": parse_lrc(body) if synced else parse_plain(body),
        "sections": sections,
    }


# ---------------------------------------------------------------------------
# placing chords over words
# ---------------------------------------------------------------------------


def _annotate_rows_with_sections(rows: list[dict], sections: list[dict]) -> list[dict]:
    """
    Assign a section label to every lyric row using song structure from Genius.

    Vocal sections (those with a firstLine) are matched to rows by forward-only
    text similarity.  Instrumental sections (firstLine="") are placed between
    matched vocal sections based on their position in the Genius ordered list.
    Every subsequent row inherits the current section until a new one starts.
    """
    if not sections or not rows:
        return rows

    vocal_rows = [r for r in rows if not r.get("instrumental")]

    # Phase 1 — match sections that carry a first lyric line.
    # bindings: (genius_idx, row_idx_or_-1, label)
    bindings: list[tuple[int, int, str]] = []
    min_row_idx = 0

    for g_idx, section in enumerate(sections):
        label = section.get("label", "")
        first_line = (section.get("firstLine") or "").strip()

        if not first_line or len(re.findall(r"[a-z]+", first_line.lower())) < 2:
            bindings.append((g_idx, -1, label))
            continue

        words = set(re.findall(r"[a-z]+", first_line.lower()))
        best_idx, best_score = -1, 0.0
        for row in vocal_rows:
            if row["index"] < min_row_idx:
                continue
            line_words = set(re.findall(r"[a-z]+", (row.get("text") or "").lower()))
            if not line_words:
                continue
            score = len(words & line_words) / len(words | line_words)
            if score > best_score and score >= 0.4:
                best_score, best_idx = score, row["index"]

        bindings.append((g_idx, best_idx, label))
        if best_idx >= 0:
            min_row_idx = best_idx + 1

    if not any(ridx >= 0 for _, ridx, _ in bindings):
        return rows  # nothing matched — leave rows without section field

    # Phase 2 — build a timeline: (row_idx, label) for every section.
    timeline: list[tuple[int, str]] = [
        (ridx, lbl) for _, ridx, lbl in bindings if ridx >= 0
    ]

    for b_idx, (_, ridx, label) in enumerate(bindings):
        if ridx >= 0:
            continue  # already in timeline

        prev = next((r for _, r, _ in reversed(bindings[:b_idx]) if r >= 0), None)
        nxt = next((r for _, r, _ in bindings[b_idx + 1:] if r >= 0), None)

        if prev is None:
            # Comes before all matched sections — Intro / pre-song material.
            timeline.append((0, label))
        elif nxt is None:
            # Comes after all matched sections — Outro / tail.
            timeline.append((rows[-1]["index"] + 1, label))
        else:
            # In between: start at the first instrumental row in that gap,
            # or at the midpoint as a fallback.
            start = next(
                (r["index"] for r in rows if prev < r["index"] < nxt and r.get("instrumental")),
                (prev + nxt) // 2,
            )
            if start < nxt:
                timeline.append((start, label))

    timeline.sort(key=lambda t: t[0])

    # Deduplicate: keep the first entry for each row index.
    seen: set[int] = set()
    timeline = [(r, l) for r, l in timeline if not (r in seen or seen.add(r))]  # type: ignore[func-returns-value]

    # Phase 3 — walk rows, applying the current section label.
    result: list[dict] = []
    tl_idx = 0
    current_section: str | None = None

    for row in rows:
        while tl_idx < len(timeline) and row["index"] >= timeline[tl_idx][0]:
            current_section = timeline[tl_idx][1]
            tl_idx += 1
        result.append({**row, "section": current_section})

    return result


def place_chords(lines: list[dict], chords: list[dict], duration: float, sections: list[dict] | None = None) -> list[dict]:
    """Put each chord above the word it lands on.

    With line-level timing the position within a line is proportional: a chord a
    third of the way through a line's time sits about a third of the way along
    its text. That is an approximation, but chord changes cluster at the start
    of lines anyway, so it reads correctly far more often than it misses - and
    it needs no alignment model.

    Chords that fall between sung lines become instrumental rows, so intros,
    solos and outros keep their chords instead of being swallowed by whichever
    line happens to be nearest.
    """
    playing = [c for c in chords if c.get("label") != "N"]
    timed = [line for line in lines if line.get("startSeconds") is not None]

    if not timed:
        # No timing at all: hand back the words with the chords ahead of them,
        # so at least both are on the page and a person can line them up.
        rows = [dict(line, chords=[], instrumental=False, endSeconds=None) for line in lines]
        if rows and playing:
            rows[0]["chords"] = [_chord_at(c, 0) for c in playing]
        return rows

    # Each line runs until the next one starts - but only for as long as a line
    # plausibly lasts. Without that cap the last line of a verse reaches all the
    # way to the next one, or to the end of the song, and every chord in the
    # solo piles up above six words.
    gaps = [
        timed[i + 1]["startSeconds"] - timed[i]["startSeconds"]
        for i in range(len(timed) - 1)
        if timed[i + 1]["startSeconds"] > timed[i]["startSeconds"]
    ]
    typical = sorted(gaps)[len(gaps) // 2] if gaps else 6.0
    longest_line = max(6.0, typical * 2.0)

    for position, line in enumerate(timed):
        following = timed[position + 1]["startSeconds"] if position + 1 < len(timed) else duration
        span = float(following) - float(line["startSeconds"])
        line["endSeconds"] = round(float(line["startSeconds"]) + min(span, longest_line), 3)

    rows: list[dict] = []
    cursor = 0.0

    for line in timed:
        start, end = float(line["startSeconds"]), float(line["endSeconds"])

        _append_instrumental(rows, [c for c in playing if cursor <= c["startSeconds"] < start], cursor, start)

        # A stamped line with no words marks a gap, not something to sing.
        if not line["text"].strip():
            cursor = max(cursor, start)
            continue

        span = max(end - start, 0.001)
        text = line["text"]
        placed: list[dict] = []
        taken = -1
        for chord in [c for c in playing if start <= c["startSeconds"] < end]:
            ratio = (chord["startSeconds"] - start) / span
            offset = int(round(len(text) * min(max(ratio, 0.0), 1.0)))
            # Never let two labels collide or run backwards.
            offset = max(offset, taken + 1)
            placed.append(_chord_at(chord, offset))
            taken = offset + len(chord["label"])

        rows.append(
            {
                "index": len(rows),
                "startSeconds": round(start, 3),
                "endSeconds": round(end, 3),
                "text": text,
                "instrumental": False,
                "chords": placed,
            }
        )
        cursor = end

    _append_instrumental(rows, [c for c in playing if c["startSeconds"] >= cursor], cursor, duration)

    if sections:
        rows = _annotate_rows_with_sections(rows, sections)

    return rows


# An instrumental stretch is read as a chord chart, so it is broken into rows of
# this many chords rather than run out as one endless line.
CHORDS_PER_INSTRUMENTAL_ROW = 8


def _append_instrumental(rows: list[dict], chords: list[dict], start: float, end: float) -> None:
    if not chords:
        return
    for offset in range(0, len(chords), CHORDS_PER_INSTRUMENTAL_ROW):
        chunk = chords[offset : offset + CHORDS_PER_INSTRUMENTAL_ROW]
        rows.append(
            {
                "index": len(rows),
                "startSeconds": round(float(chunk[0]["startSeconds"]), 3),
                "endSeconds": round(float(end), 3),
                "text": "",
                "instrumental": True,
                "chords": [_chord_at(c, position * 6) for position, c in enumerate(chunk)],
            }
        )


def _chord_at(chord: dict, offset: int) -> dict:
    return {
        "label": chord["label"],
        "charOffset": int(offset),
        "startSeconds": chord["startSeconds"],
        "confidence": chord.get("confidence", 0.0),
        "lowConfidence": bool(chord.get("lowConfidence")),
        "edited": bool(chord.get("edited")),
    }


def render_text(rows: list[dict]) -> str:
    """Chords over words, the way a chord sheet is read on paper."""
    out: list[str] = []
    for row in rows:
        chord_line = ""
        for chord in row["chords"]:
            pad = max(chord["charOffset"] - len(chord_line), 0 if not chord_line else 1)
            chord_line += " " * pad + chord["label"]
        if chord_line.strip():
            out.append(chord_line)
        out.append(row["text"])
    return "\n".join(out)
