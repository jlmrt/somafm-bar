#!/usr/bin/env python3
"""Recording boundaries, storage limits, and playback-independent ICY recording."""

import http.server
import importlib.util
import json
import math
import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("recorder", ROOT / "recorder.py")
recorder = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(recorder)
MP3 = b"\xff\xfb\x90\0" + bytes(413)
AAC = b"\xff\xf1\x50\x80\x10\x1f\xfc" + bytes(121)


class SongTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="somafm-songs-")
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name)
        self.events = []
        self.songs = recorder.Songs(self.directory, "Station", "mp3", lambda **state: self.events.append(state), min_seconds=0)
        self.addCleanup(self.songs.discard)

    def test_skip_first_song_and_discard_last_incomplete_song(self):
        self.songs.feed(MP3 * 2)
        self.songs.metadata("Artist - Already playing")
        self.songs.feed(MP3 * 3)
        self.assertEqual(list(self.directory.iterdir()), [])
        self.songs.metadata("Artist - Complete")
        self.songs.feed(MP3 * 4)
        self.assertEqual(len(list(self.directory.glob("*.mp3"))), 1)  # private partial only
        self.songs.metadata("Artist - Incomplete")
        self.songs.feed(MP3 * 2)
        self.songs.discard()
        files = list(self.directory.iterdir())
        self.assertEqual(len(files), 1)
        self.assertIn("Artist - Complete", files[0].name)
        self.assertEqual(files[0].read_bytes()[recorder.TAG_SIZE:], MP3 * 4)

    def test_metadata_inside_a_frame_never_cuts_the_frame(self):
        self.songs.metadata("Initial")
        self.songs.metadata("Second")
        self.songs.feed(MP3[:100])
        self.songs.metadata("Third")
        self.songs.feed(MP3[100:] + MP3)
        self.songs.discard()
        files = list(self.directory.iterdir())
        self.assertEqual(len(files), 1)
        self.assertIn("Second", files[0].name)
        self.assertEqual(files[0].read_bytes()[recorder.TAG_SIZE:], MP3)

    def test_repeated_and_empty_metadata_do_not_split_songs(self):
        self.songs.metadata("Initial")
        self.songs.metadata("Second")
        self.songs.feed(MP3)
        for title in ("", "Second", "Second"):
            self.songs.metadata(title)
            self.songs.feed(MP3)
        self.songs.metadata("Third")
        self.songs.feed(MP3)
        self.songs.discard()
        self.assertEqual(next(self.directory.iterdir()).read_bytes()[recorder.TAG_SIZE:], MP3 * 4)

    def test_same_filename_is_never_overwritten(self):
        self.songs.metadata("Initial")
        for title in ("A", "B", "A", "B", "Final"):
            self.songs.metadata(title)
            self.songs.feed(MP3)
        self.songs.discard()
        files = list(self.directory.iterdir())
        self.assertEqual(len(files), 4)
        self.assertEqual(len({p.name for p in files}), 4)

    def test_aac_frames_are_saved_without_metadata_bytes(self):
        songs = recorder.Songs(self.directory, "Station", "aac", lambda **state: None, min_seconds=0)
        self.addCleanup(songs.discard)
        songs.metadata("First")
        songs.metadata("Second")
        songs.feed(AAC * 5)
        songs.metadata("Third")
        songs.feed(AAC)
        songs.discard()
        self.assertEqual(next(self.directory.iterdir()).read_bytes()[recorder.TAG_SIZE:], AAC * 5)

    def test_stream_titles_and_filenames_handle_unicode_and_untrusted_text(self):
        self.assertEqual(recorder.stream_title("StreamTitle='Björk - Jóga';".encode()), "Björk - Jóga")
        self.assertEqual(recorder.stream_title(b"StreamTitle='L\xe9a - Song';"), "Léa - Song")
        self.assertEqual(recorder.stream_title(b"StreamUrl='https://example.test';"), "")
        label = recorder.filename("../../A\x00/曲" * 100)
        self.assertNotIn("/", label)
        self.assertNotIn("\x00", label)
        self.assertLessEqual(len(label.encode()), 160)

    def test_announcements_are_skipped_without_creating_files(self):
        self.songs.metadata("Initial")
        for title in ("Big Url: - Groove Salad, Listener Supported", "SomaFM Begathon - Please keep us on the air",
                      "https://somafm.com/support/"):
            self.songs.metadata(title)
            self.songs.feed(MP3 * 1500)
            self.assertEqual(list(self.directory.iterdir()), [])
        self.songs.metadata("Artist - Music resumes")
        self.songs.feed(MP3 * 5)
        self.songs.metadata("Artist - Following")
        self.songs.feed(MP3)
        self.songs.discard()
        files = list(self.directory.iterdir())
        self.assertEqual(len(files), 1)
        self.assertIn("Music resumes", files[0].name)
        self.assertEqual(self.songs.saved, 1)
        self.assertFalse(recorder.is_announcement("Soma - Song"))
        self.assertFalse(recorder.is_announcement("Artist - SomaFM is great"))

    def test_short_clips_are_discarded_and_long_songs_kept_for_both_codecs(self):
        for codec, frame in (("mp3", MP3), ("aac", AAC)):
            with self.subTest(codec=codec):
                directory = self.directory / codec
                directory.mkdir()
                budget = recorder.Budget(directory, {})
                budget.check = lambda additional=0: None
                songs = recorder.Songs(directory, "Station", codec, lambda **state: None, budget)
                songs.metadata("Initial")
                songs.metadata("Artist - Short interlude")
                songs.feed(frame * math.floor(20 / recorder.frame_seconds(frame, codec)))
                songs.metadata("Artist - Whole song")
                songs.feed(frame * math.ceil(31 / recorder.frame_seconds(frame, codec)))
                songs.metadata("Artist - Following")
                songs.feed(frame)
                songs.discard()
                files = list(directory.iterdir())
                self.assertEqual(len(files), 1)
                self.assertIn("Whole song", files[0].name)
                self.assertEqual(budget.used, files[0].stat().st_size)
                self.assertEqual(songs.saved, 1)

    def test_audio_duration_is_independent_of_bitrate(self):
        low_rate = b"\xff\xfb\x10\0"
        self.assertNotEqual(recorder.frame_size(low_rate, "mp3"), recorder.frame_size(MP3, "mp3"))
        self.assertAlmostEqual(recorder.frame_seconds(low_rate, "mp3"), 1152 / 44100)
        self.assertAlmostEqual(recorder.frame_seconds(MP3, "mp3"), 1152 / 44100)
        self.assertAlmostEqual(recorder.frame_seconds(AAC, "aac"), 1024 / 44100)

    def test_quota_discards_partial_and_keeps_completed_songs(self):
        budget = recorder.Budget(self.directory, {})
        budget.check = lambda additional=0: (
            (_ for _ in ()).throw(recorder.StorageLimit("quota"))
            if budget.used + additional > recorder.TAG_SIZE * 2 + len(MP3) * 2 else None)
        self.songs.budget = budget
        self.songs.metadata("Initial")
        self.songs.metadata("Complete")
        self.songs.feed(MP3)
        self.songs.metadata("Partial")
        with self.assertRaises(recorder.StorageLimit):
            self.songs.feed(MP3 * 5)
        self.songs.discard()
        files = list(self.directory.iterdir())
        self.assertEqual(len(files), 1)
        self.assertIn("Complete", files[0].name)
        self.assertEqual(budget.used, files[0].stat().st_size)

    def test_budget_respects_quota_and_both_disk_reserves(self):
        budget = recorder.Budget(self.directory, {"recordingQuotaMiB": 1, "recordingReserveMiB": 2,
                                                 "recordingReservePercent": 5})
        with patch.object(recorder.shutil, "disk_usage", return_value=shutil._ntuple_diskusage(100_000_000, 0, 4_999_999)):
            with self.assertRaisesRegex(recorder.StorageLimit, "OS"):
                budget.check()
        with patch.object(recorder.shutil, "disk_usage", return_value=shutil._ntuple_diskusage(10_000_000, 0, 2_000_000)):
            with self.assertRaisesRegex(recorder.StorageLimit, "OS"):
                budget.check()
        with self.assertRaisesRegex(recorder.StorageLimit, "quota"):
            budget.check(1024 * 1024 + 1)

    def test_low_disk_during_song_keeps_only_completed_files(self):
        budget = recorder.Budget(self.directory, {})
        self.songs.budget = budget
        enough = shutil._ntuple_diskusage(100 * 1024**3, 0, 20 * 1024**3)
        full = shutil._ntuple_diskusage(100 * 1024**3, 0, 4 * 1024**3)
        with patch.object(recorder.shutil, "disk_usage", return_value=enough):
            self.songs.metadata("Initial")
            self.songs.metadata("Complete")
            self.songs.feed(MP3)
            self.songs.metadata("Interrupted")
            self.songs.feed(MP3)
        with patch.object(recorder.shutil, "disk_usage", return_value=full):
            with self.assertRaisesRegex(recorder.StorageLimit, "OS"):
                self.songs.feed(MP3)
        self.songs.discard()
        files = list(self.directory.iterdir())
        self.assertEqual(len(files), 1)
        self.assertIn("Complete", files[0].name)


class StreamHandler(http.server.BaseHTTPRequestHandler):
    def log_message(self, *_args):
        pass

    def do_GET(self):
        if self.path == "/station.pls":
            self.send_response(200)
            self.send_header("Content-Type", "audio/x-scpls")
            self.end_headers()
            self.wfile.write(b"[playlist]\nFile1=/stream\nNumberOfEntries=1\n")
            return
        self.send_response(200)
        self.send_header("Content-Type", "audio/aac" if self.server.codec == "aac" else "audio/mpeg")
        if self.path != "/no-metadata":
            self.send_header("icy-metaint", "1024")
        self.end_headers()
        offset = 0
        audio = self.server.audio
        try:
            while not self.server.stopped.is_set():
                block = (audio * 2)[offset:offset + 1024]
                offset = (offset + 1024) % len(audio)
                self.wfile.write(block)
                title = ("StreamTitle='" + self.server.title + "';").encode()
                self.wfile.write(bytes([(len(title) + 15) // 16]) + title.ljust((len(title) + 15) // 16 * 16, b"\0"))
                self.wfile.flush()
                time.sleep(0.04)
        except (BrokenPipeError, ConnectionResetError):
            pass


@unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"), "Audio tools required for recording integration")
class RecordingIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.audio = {}
        for codec, arguments in (("mp3", ["-c:a", "libmp3lame", "-reservoir", "0", "-write_xing", "0", "-id3v2_version", "0"]),
                                 ("aac", ["-c:a", "aac"])):
            cls.audio[codec] = subprocess.check_output([
                "ffmpeg", "-v", "error", "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=44100",
                "-t", "0.5", *arguments, "-b:a", "128k", "-f", "adts" if codec == "aac" else "mp3", "pipe:1"])

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="somafm-recording-")
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.runtime = self.base / "runtime/somafm-bar"
        self.runtime.mkdir(parents=True)
        self.music = self.base / "Music library"
        self.bin = self.base / "bin"
        self.bin.mkdir()
        xdg = self.bin / "xdg-user-dir"
        xdg.write_text('#!/bin/sh\nprintf "%s\\n" "$SOMA_TEST_MUSIC"\n')
        xdg.chmod(0o700)
        self.env = {**os.environ, "XDG_RUNTIME_DIR": str(self.runtime.parent),
                    "XDG_DATA_HOME": str(self.base / "data"), "SOMA_TEST_MUSIC": str(self.music),
                    "PATH": str(self.bin) + os.pathsep + os.environ["PATH"]}
        self.script = self.base / "recorder.py"
        shutil.copy2(ROOT / "recorder.py", self.script)
        for name in ("player", "player-status.lua"):
            shutil.copy2(ROOT / name, self.base / name)
        self.config = {"station": "Test station", "recordingQuotaMiB": 20, "recordingMinSongSeconds": 0,
                       "recordingReserveMiB": 16, "recordingReservePercent": 1}
        self.stream = http.server.ThreadingHTTPServer(("127.0.0.1", 0), StreamHandler)
        self.stream.audio, self.stream.codec = self.audio["mp3"], "mp3"
        self.stream.title = "Artist - Initial"
        self.stream.stopped = threading.Event()
        self.url = f"http://127.0.0.1:{self.stream.server_port}/stream"
        self.config["url"] = self.url
        self.save_config()
        threading.Thread(target=self.stream.serve_forever, daemon=True).start()
        self.addCleanup(self.stream.server_close)
        self.addCleanup(self.stream.shutdown)
        self.addCleanup(self.stream.stopped.set)
        self.addCleanup(lambda: self.command("stop"))

    def save_config(self):
        (self.base / "config.json").write_text(json.dumps(self.config))

    def command(self, *arguments, expected=0):
        result = subprocess.run([sys.executable, str(self.script), *arguments], env=self.env,
                                capture_output=True, text=True, timeout=12)
        self.assertEqual(result.returncode, expected, result.stderr + result.stdout)
        self.assertEqual(result.stderr, "")
        return json.loads(result.stdout)

    def player_action(self, *arguments):
        result = subprocess.run([str(self.base / "player"), *arguments], env=self.env,
                                capture_output=True, text=True, timeout=15)
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        self.assertEqual(result.stderr, "")
        return json.loads(result.stdout)

    def state(self):
        return recorder.read_json(self.runtime / "recording.json")

    def wait_for(self, predicate):
        deadline = time.monotonic() + 6
        while time.monotonic() < deadline:
            if predicate():
                return
            time.sleep(0.02)
        self.fail("Timed out; recorder state: " + repr(self.state()))

    def start(self):
        self.assertTrue(self.player_action("record", "start")["active"])
        self.wait_for(lambda: self.state().get("waiting") and not self.state().get("starting"))

    def next_song(self, title):
        self.stream.title = title
        self.wait_for(lambda: self.state().get("title") == title and not self.state().get("waiting"))

    def completed(self):
        return [p for p in self.music.rglob("*") if p.is_file() and not p.name.startswith(".")]

    def test_real_mp3_files_tags_and_no_incomplete_songs(self):
        self.start()
        self.assertEqual(self.completed(), [])
        self.next_song("Björk - Jóga")
        time.sleep(0.2)
        self.next_song("Artist - Incomplete")
        self.wait_for(lambda: len(self.completed()) == 1)
        self.assertFalse(self.command("stop")["active"])
        self.assertEqual(len(self.completed()), 1)
        self.assertEqual(list(self.music.rglob(".recording-*")), [])
        song = self.completed()[0]
        info = json.loads(subprocess.check_output(["ffprobe", "-v", "error", "-show_entries", "format_tags:stream=codec_name", "-of", "json", str(song)]))
        self.assertEqual(info["format"]["tags"]["title"], "Jóga")
        self.assertEqual(info["format"]["tags"]["artist"], "Björk")
        self.assertEqual(info["format"]["tags"]["album"], "Test station")
        self.assertEqual(info["format"]["tags"]["genre"], "SomaFM")
        self.assertEqual(info["streams"][0]["codec_name"], "mp3")
        self.assertEqual(self.state()["saved"], 1)
        subprocess.run(["ffmpeg", "-v", "error", "-i", str(song), "-f", "null", "-"], capture_output=True, check=True)

    def test_record_without_player_and_follow_station_changes(self):
        self.assertFalse((self.runtime / "mpvd.sock").exists())
        self.start()
        self.assertFalse(self.player_action("status")["running"])
        self.assertFalse((self.runtime / "mpvd.sock").exists())
        self.next_song("Artist - Whole")
        self.next_song("Artist - Next")
        self.wait_for(lambda: len(self.completed()) == 1)
        override = self.base / "data/somafm-bar/override.json"
        override.parent.mkdir(parents=True, exist_ok=True)
        old_partial = Path(self.state()["file"])
        override.write_text(json.dumps({"name": "Other station", "url": self.url + "?other"}))
        self.wait_for(lambda: self.state().get("directory", "").endswith("Other station") and not self.state().get("starting"))
        self.assertTrue(self.state()["active"])
        self.assertFalse(old_partial.exists())
        self.assertEqual(list(self.music.rglob(".recording-*")), [])
        self.assertFalse((self.runtime / "mpvd.sock").exists())
        self.next_song("Artist - Other station song")
        self.next_song("Artist - Following")
        self.wait_for(lambda: len(self.completed()) == 2)
        self.assertEqual(self.state()["saved"], 2)

    def test_announcements_and_short_clips_are_filtered_in_a_live_stream(self):
        self.config["recordingMinSongSeconds"] = 0.4
        self.save_config()
        self.start()
        self.next_song("Artist - Tiny interlude")
        self.stream.title = "Big Url: - You're listening to Groove Salad"
        self.wait_for(lambda: self.state().get("waiting") and self.state().get("title", "").startswith("Big Url:"))
        self.assertEqual(self.completed(), [])
        self.assertEqual(list(self.music.rglob(".recording-*")), [])
        self.next_song("Artist - Full song")
        time.sleep(0.5)
        self.next_song("Artist - Following")
        self.wait_for(lambda: len(self.completed()) == 1)
        self.assertIn("Full song", self.completed()[0].name)
        self.assertEqual(self.state()["saved"], 1)

    def test_reload_preserves_saved_songs_and_session_quota_usage(self):
        self.start()
        self.next_song("Artist - Completed")
        time.sleep(0.2)
        self.next_song("Artist - In progress")
        self.wait_for(lambda: len(self.completed()) == 1)
        saved_bytes = self.completed()[0].stat().st_size
        old_pid = recorder.read_json(self.runtime / "recorder.pid")["pid"]
        state = self.player_action("record", "reload")
        self.assertTrue(state["active"])
        self.assertEqual(state["saved"], 1)
        self.assertEqual(state["bytes"], saved_bytes)
        self.assertNotEqual(recorder.read_json(self.runtime / "recorder.pid")["pid"], old_pid)
        self.wait_for(lambda: not self.state().get("starting"))
        self.assertEqual(list(self.music.rglob(".recording-*")), [])
        self.next_song("Artist - After update")
        self.next_song("Artist - Following")
        self.wait_for(lambda: len(self.completed()) == 2)
        self.assertEqual(self.state()["saved"], 2)

    def test_quota_stops_automatically_and_discards_incomplete_song(self):
        self.config["recordingQuotaMiB"] = 0.03
        self.save_config()
        self.start()
        self.next_song("Artist - Too large")
        self.wait_for(lambda: not self.state().get("active"))
        self.assertIn("quota", self.state()["error"])
        self.assertEqual(list(self.music.rglob(".recording-*")), [])
        self.assertEqual(self.completed(), [])

    def test_low_disk_space_rejects_silent_recording(self):
        self.config["recordingReserveMiB"] = 10**12
        self.save_config()
        self.assertIn("OS", self.command("start", self.url, "Station", expected=4)["error"])
        self.assertFalse(self.state()["active"])

    def test_playlist_resolution_and_aac_files(self):
        self.stream.audio, self.stream.codec = self.audio["aac"], "aac"
        self.config["url"] = self.url.replace("/stream", "/station.pls")
        self.save_config()
        self.start()
        self.next_song("Artist - AAC")
        time.sleep(0.2)
        self.next_song("Artist - Following")
        self.command("stop")
        self.assertEqual(len(self.completed()), 1)
        song = self.completed()[0]
        self.assertEqual(song.suffix, ".aac")
        codec = subprocess.check_output(["ffprobe", "-v", "error", "-show_entries", "stream=codec_name", "-of", "csv=p=0", str(song)], text=True).strip()
        self.assertEqual(codec, "aac")
        tags = json.loads(subprocess.check_output(["ffprobe", "-v", "error", "-show_entries", "format_tags", "-of", "json", str(song)]))["format"]["tags"]
        self.assertEqual(tags["genre"], "SomaFM")

    def test_no_metadata_reports_error_without_saving_audio(self):
        self.config["url"] = self.url.replace("/stream", "/no-metadata")
        self.save_config()
        self.player_action("record", "start")
        self.wait_for(lambda: not self.state().get("active"))
        self.assertIn("metadata", self.state()["error"])
        self.assertEqual(self.completed(), [])

    def test_crash_recovery_discards_unfinished_song_and_start_is_idempotent(self):
        self.start()
        first_pid = recorder.read_json(self.runtime / "recorder.pid")["pid"]
        self.player_action("record", "start")
        self.assertEqual(recorder.read_json(self.runtime / "recorder.pid")["pid"], first_pid)
        self.next_song("Artist - Interrupted")
        os.kill(first_pid, signal.SIGKILL)
        self.wait_for(lambda: not recorder.process_start(first_pid))
        state = self.command("status")
        self.assertFalse(state["active"])
        self.assertEqual(list(self.music.rglob(".recording-*")), [])
        self.assertEqual(self.completed(), [])

    @unittest.skipUnless(shutil.which("mpv"), "mpv required")
    def test_recording_continues_through_real_playback_pause_and_stop(self):
        real_mpv = shutil.which("mpv")
        launcher = self.bin / "mpv"
        launcher.write_text("#!/usr/bin/env python3\nimport os, sys\nos.execv(" + repr(real_mpv)
                            + ", ['mpv', '--no-config', '--load-scripts=no', '--ao=null', *sys.argv[1:]])\n")
        launcher.chmod(0o700)
        self.addCleanup(lambda: self.player_action("stop"))
        self.assertTrue(self.player_action("play")["running"])
        self.start()
        self.next_song("Artist - Whole")
        time.sleep(0.2)
        partial = Path(self.state()["file"])
        self.assertTrue(self.player_action("pause")["paused"])
        self.assertTrue(self.state()["active"])
        self.assertEqual(self.state()["file"], str(partial))
        self.assertTrue(self.player_action("play")["running"])
        self.player_action("volume", "0")
        self.assertFalse(self.player_action("stop")["running"])
        self.assertTrue(self.state()["active"])
        self.assertEqual(self.state()["file"], str(partial))
        self.assertTrue(partial.exists())
        self.next_song("Artist - Following")
        self.wait_for(lambda: len(self.completed()) == 1)
        self.assertIn("Artist - Whole", self.completed()[0].name)
        self.assertFalse((self.runtime / "mpvd.sock").exists())
        self.assertFalse(self.player_action("record", "stop")["active"])
        self.assertEqual(list(self.music.rglob(".recording-*")), [])


if __name__ == "__main__":
    unittest.main()
