"""Smoke test for Phase 9 - Chord Sheets.

Three things matter here and none of them needs a real song:

1. Chord sheets degrade safely. Without torch/demucs the backend still boots,
   every existing endpoint behaves as before, and asking for a sheet on an
   unsplit URL says so instead of exploding.
2. The music theory the module owns is right - template shapes, transposition,
   enharmonic spelling, and the bar/row chart the UI renders.
3. Transpose, capo and tuning are a re-spelling and never a re-analysis, so
   they must compose into one shift and round-trip back to concert pitch.

A real analysis needs separated stems and takes half a minute, so it is
deliberately out of scope.
"""

import os
import sys
import tempfile
from pathlib import Path


BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))


def check(label: str, condition: bool, detail: str = "") -> None:
    if not condition:
        raise AssertionError(f"{label} failed. {detail}".strip())
    print(f"  ok  {label}")


def main() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        os.environ["AUDIO_MIXER_STORAGE_ROOT"] = tmp

        import numpy as np
        from fastapi.testclient import TestClient

        from app import chord_engine as ce
        from app.chord_sheet import build_chart, to_chordpro, to_plain_text
        from app.main import app

        client = TestClient(app)

        print("environment")
        env = client.get("/api/chord-sheets/environment")
        check("environment endpoint answers", env.status_code == 200, str(env.status_code))
        body = env.json()
        check("reports a missing list", isinstance(body.get("missing"), list))
        check("reports the separation environment", "separation" in body)
        check("reports the confidence threshold", isinstance(body.get("lowConfidenceThreshold"), float))
        print(f"  ..  analysis available: {bool(body.get('ok'))}")

        print("\nendpoints degrade safely")
        listing = client.get("/api/chord-sheets")
        check("listing answers", listing.status_code == 200, str(listing.status_code))
        check("listing is empty on a fresh store", listing.json() == [])
        missing = client.get("/api/chord-sheets/does-not-exist")
        check("unknown sheet is a 404", missing.status_code == 404, str(missing.status_code))
        bad = client.post("/api/chord-sheets", json={})
        check("a sheet with no url and no split is refused", bad.status_code in (400, 503), str(bad.status_code))

        print("\nexisting endpoints are untouched")
        health = client.get("/api/health")
        check("health still answers", health.status_code == 200, str(health.status_code))
        splits = client.get("/api/splits")
        check("splits still answer", splits.status_code == 200, str(splits.status_code))

        print("\nchord templates")
        templates = ce.build_templates()
        check("25 templates", templates.shape == (25, 12), str(templates.shape))
        check("every template is unit length", bool(np.allclose(np.linalg.norm(templates, axis=1), 1.0)))
        # C major must prefer C major over every other triad.
        c_major = np.zeros(12)
        for note in (0, 4, 7):
            c_major[note] = 1.0
        c_major /= np.linalg.norm(c_major)
        scores = templates @ c_major
        check("a C major triad scores C major highest", int(np.argmax(scores)) == 0, ce.chord_name(int(np.argmax(scores))))
        a_minor = np.zeros(12)
        for note in (9, 0, 4):
            a_minor[note] = 1.0
        a_minor /= np.linalg.norm(a_minor)
        check("an A minor triad scores A minor highest", int(np.argmax(templates @ a_minor)) == 21, ce.chord_name(int(np.argmax(templates @ a_minor))))

        print("\ntransitions")
        transitions = ce.build_transitions(stay=0.72)
        check("rows are a distribution", bool(np.allclose(transitions.sum(axis=1), 1.0)))
        check("staying is the likeliest move", bool(np.all(np.diag(transitions) >= transitions.max(axis=1) - 1e-9)))
        # C -> G (one step round the circle) must beat C -> F# (six steps).
        check("near keys beat far ones", transitions[0, 7] > transitions[0, 6], f"{transitions[0, 7]} vs {transitions[0, 6]}")

        print("\nnaming and transposition")
        check("index 0 is C", ce.chord_name(0) == "C")
        check("index 21 is Am", ce.chord_name(21) == "Am")
        check("no-chord is N", ce.chord_name(ce.N_CHORD) == "N")
        check("sharp spelling by default", ce.chord_name(10) == "A#")
        check("flat spelling on request", ce.chord_name(10, flats=True) == "Bb")
        check("Gb is spelled F# outside its own key", ce.chord_name(6, flats=True, key_root="G") == "F#")
        check("Gb stays Gb in Gb", ce.chord_name(6, flats=True, key_root="Gb") == "Gb")
        check("transposing up 2 moves C to D", ce.transpose_chord(0, 2) == 2)
        check("transposing keeps the quality", ce.chord_name(ce.transpose_chord(21, 2)) == "Bm")
        check("transposing wraps", ce.chord_name(ce.transpose_chord(11, 1)) == "C")
        check("no-chord never transposes", ce.transpose_chord(ce.N_CHORD, 5) == ce.N_CHORD)

        print("\nspelling follows the transposed key")
        flats, root = ce.spelling_after_shift("G minor", 0)
        check("G minor reads flat", flats and root == "G", f"{flats} {root}")
        flats, root = ce.spelling_after_shift("G minor", 1)
        check("G minor up one is G# minor, in sharps", (not flats) and root == "G#", f"{flats} {root}")
        flats, root = ce.spelling_after_shift("G minor", -3)
        check("G minor down three is E minor", (not flats) and root == "E", f"{flats} {root}")

        print("\nthe chart")
        chords = [
            {"label": "Bb", "index": 10, "bar": 0, "startSeconds": 0.0, "durationSeconds": 2.0, "confidence": 0.9, "lowConfidence": False},
            {"label": "F", "index": 5, "bar": 1, "startSeconds": 2.0, "durationSeconds": 2.0, "confidence": 0.8, "lowConfidence": False},
            {"label": "Gm", "index": 19, "bar": 3, "startSeconds": 6.0, "durationSeconds": 2.0, "confidence": 0.5, "lowConfidence": True},
            {"label": "N", "index": 24, "bar": 4, "startSeconds": 8.0, "durationSeconds": 1.0, "confidence": 0.9, "lowConfidence": False},
        ]
        chart = build_chart(chords)
        check("one row per four bars", len(chart) == 1, str(len(chart)))
        bars = chart[0]["bars"]
        check("four bars in the row", len(bars) == 4, str(len(bars)))
        check("bar 2 is held", bars[2]["held"] is True)
        check("bar 0 carries its chord", bars[0]["chords"][0]["label"] == "Bb")
        check("the row is stamped with a start time", chart[0]["startSeconds"] == 0.0)
        check("no-chord is left out of the chart", all(c["label"] != "N" for b in bars for c in b["chords"]))
        check("an empty song makes an empty chart", build_chart([]) == [])

        print("\nexport formats")
        analysis = {"chords": chords, "tempo": 83.4, "key": {"key": "G minor"}, "tuning": {"assumed": "E Standard", "cents": -7.0}}
        pro = to_chordpro({"title": "Test"}, analysis)
        check("ChordPro carries the title", "{title: Test}" in pro)
        check("ChordPro carries the key", "{key: G minor}" in pro)
        check("ChordPro carries the tuning", "{tuning: E Standard}" in pro)
        check("ChordPro brackets its chords", "[Bb]" in pro)
        check("ChordPro marks held bars", "%" in pro)
        text = to_plain_text({"title": "Test"}, analysis)
        check("text export carries the title", text.startswith("Test"))
        check("text export carries the chords", "Bb" in text)

        print("\ntuning is suggested, never claimed")
        events = [
            {"index": 10, "duration": 4.0},  # Bb
            {"index": 5, "duration": 4.0},   # F
            {"index": 19, "duration": 4.0},  # Gm
            {"index": 15, "duration": 4.0},  # Eb
        ]
        # A flat-key song with a guitar sitting two semitones "low" is exactly
        # the case that fooled the first version into claiming D Standard.
        suggestion = ce.tuning_suggestions(events, guitar_low_midi=38, bass_low_midi=27)
        check("standard tuning is assumed", suggestion["assumed"] == "E Standard")
        check("nothing is applied", suggestion["semitoneShift"] == 0, str(suggestion["semitoneShift"]))
        check("confidence stays low", suggestion["confidence"] <= 0.3, str(suggestion["confidence"]))
        check("alternatives are offered", len(suggestion["options"]) == 4)
        check("a capo is suggested", isinstance(suggestion["capoSuggestion"], int))
        bleed = ce.tuning_suggestions(events, guitar_low_midi=28, bass_low_midi=27)
        check("bleed under the bass is flagged", bleed["bleedSuspected"] is True)
        check("bleed still applies nothing", bleed["semitoneShift"] == 0)
        quiet = ce.tuning_suggestions(events, guitar_low_midi=None, bass_low_midi=None)
        check("a missing guitar stem is survivable", quiet["semitoneShift"] == 0)

        print("\nspeed detection")
        check("no reference means no verdict", ce.speed_ratio(200.0, None) is None)
        check("a matching duration is not altered", ce.speed_ratio(200.0, 200.0)["altered"] is False)
        sped = ce.speed_ratio(190.0, 200.0)
        check("a short upload reads as sped up", sped["altered"] is True)
        check("and yields a pitch correction", sped["cents"] > 0, str(sped["cents"]))

        print("\nheld bars keep a time")
        held_only = [
            {"label": "Bb", "index": 10, "bar": 0, "startSeconds": 4.0, "durationSeconds": 40.0, "confidence": 0.9, "lowConfidence": False},
        ]
        long_chart = build_chart(held_only + [{"label": "F", "index": 5, "bar": 9, "startSeconds": 44.0, "durationSeconds": 2.0, "confidence": 0.9, "lowConfidence": False}])
        check("a row of only held bars is not blank", long_chart[1]["startSeconds"] is not None)

        print("\nvideo titles into artist and track")
        from app import lyrics as ly

        check("dash split", ly.clean_title("Toto - Rosanna (Official HD Video)") == ("Toto", "Rosanna"))
        check("en dash and brackets", ly.clean_title("Artist – Song [Official Music Video]") == ("Artist", "Song"))
        check("featuring is dropped", ly.clean_title("A - B feat. C (Official Audio)") == ("A", "B"))
        check("no separator leaves the artist unknown", ly.clean_title("Just A Title") == (None, "Just A Title"))

        print("\nLRC parsing")
        parsed = ly.parse_lrc("[ar: X]\n[00:12.50] first line\n[00:22.00][01:05.40] repeated\n")
        check("metadata tags are dropped", all("ar:" not in row["text"] for row in parsed))
        check("timestamps become seconds", parsed[0]["startSeconds"] == 12.5, str(parsed[0]["startSeconds"]))
        check("a repeated line becomes two", sum(1 for row in parsed if row["text"] == "repeated") == 2)
        check("lines come back in time order", [r["startSeconds"] for r in parsed] == sorted(r["startSeconds"] for r in parsed))
        plain = ly.parse_plain("one\ntwo\n\n")
        check("plain lyrics claim no timing", all(row["startSeconds"] is None for row in plain))
        check("trailing blanks are trimmed", len(plain) == 2, str(len(plain)))
        check("pasted LRC is detected as synced", ly.from_pasted("[00:01.00] hi")["synced"] is True)
        check("pasted plain text is not", ly.from_pasted("hi there")["synced"] is False)

        print("\nplacing chords over words")
        lyric_lines = [
            {"index": 0, "startSeconds": 10.0, "text": "first line of words here"},
            {"index": 1, "startSeconds": 16.0, "text": "second line of words here"},
        ]
        song_chords = [
            {"label": "Bb", "startSeconds": 2.0, "confidence": 0.9, "lowConfidence": False},
            {"label": "F", "startSeconds": 10.1, "confidence": 0.9, "lowConfidence": False},
            {"label": "Gm", "startSeconds": 13.0, "confidence": 0.5, "lowConfidence": True},
            {"label": "Eb", "startSeconds": 16.2, "confidence": 0.9, "lowConfidence": False},
            {"label": "N", "startSeconds": 17.0, "confidence": 0.9, "lowConfidence": False},
            {"label": "Cm", "startSeconds": 90.0, "confidence": 0.9, "lowConfidence": False},
        ]
        placed = ly.place_chords([dict(l) for l in lyric_lines], song_chords, duration=120.0)
        sung = [row for row in placed if not row["instrumental"]]
        check("both lines survive", len(sung) == 2, str(len(sung)))
        check("a chord before the words becomes an intro row", placed[0]["instrumental"] is True)
        check("the first line gets its chords", [c["label"] for c in sung[0]["chords"]] == ["F", "Gm"])
        check("no-chord is never placed", all(c["label"] != "N" for row in placed for c in row["chords"]))
        check("offsets rise across a line", sung[0]["chords"][0]["charOffset"] < sung[0]["chords"][1]["charOffset"])
        check("a chord near the line start sits near the start", sung[0]["chords"][0]["charOffset"] <= 2)
        check("low confidence survives placement", sung[0]["chords"][1]["lowConfidence"] is True)
        # The last line must not stretch to the end of the song and swallow the outro.
        check("the last line does not run to the end", sung[-1]["endSeconds"] < 90.0, str(sung[-1]["endSeconds"]))
        check("the outro becomes its own row", any(
            row["instrumental"] and any(c["label"] == "Cm" for c in row["chords"]) for row in placed
        ))

        print("\nlong instrumental stretches stay readable")
        many = [{"label": "Bb", "startSeconds": float(t), "confidence": 0.9, "lowConfidence": False} for t in range(30, 70)]
        chunked = ly.place_chords([{"index": 0, "startSeconds": 5.0, "text": "a line"}], many, duration=120.0)
        check("no row carries an endless chord run", max(len(r["chords"]) for r in chunked) <= 8, str(max(len(r["chords"]) for r in chunked)))

        print("\nrendering chords over words")
        rendered = ly.render_text(sung)
        lines_out = rendered.split("\n")
        check("a chord line precedes its lyric", lines_out[1] == "first line of words here", lines_out[1])
        check("the chord line carries the chords", "F" in lines_out[0] and "Gm" in lines_out[0])
        check("chord labels never overlap", "FGm" not in lines_out[0] and "GmF" not in lines_out[0])

        print("\nlyrics endpoints exist and validate")
        paths = {getattr(route, "path", "") for route in app.routes}
        check("POST/DELETE lyrics route registered", "/api/chord-sheets/{sheet_id}/lyrics" in paths)
        empty = client.post("/api/chord-sheets/nope/lyrics", json={"source": "manual", "text": ""})
        check("an empty paste is refused", empty.status_code in (400, 404), str(empty.status_code))
        bad_source = client.post("/api/chord-sheets/nope/lyrics", json={"source": "telepathy"})
        check("an unknown source is refused", bad_source.status_code in (400, 404), str(bad_source.status_code))

    print("\nphase 9 smoke passed")


if __name__ == "__main__":
    main()
