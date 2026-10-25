#!/usr/bin/env python3
"""Record ICY radio streams into tagged, frame-aligned songs without re-encoding."""

import contextlib
from datetime import datetime
import fcntl
import json
import os
from pathlib import Path
import re
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import threading
import time
import unicodedata
from urllib.parse import urljoin, urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener


MAX_INTERVAL = 4 * 1024 * 1024
TAG_SIZE = 4096


def clean_text(value):
    return " ".join("".join(c if not unicodedata.category(c).startswith("C") else " "
                            for c in str(value)).split())[:512]


def filename(value, limit=160):
    value = re.sub(r'[/\\:*?"<>|]', "_", clean_text(value)).strip(" .")
    return value.encode("utf-8")[:limit].decode("utf-8", "ignore") or "Unknown track"


def synchsafe(value):
    return bytes((value >> shift) & 127 for shift in (21, 14, 7, 0))


def id3_tag(title, station):
    artist, separator, song = title.partition(" - ")
    fields = {"TIT2": song if separator else title or "Unknown track", "TALB": station}
    if separator:
        fields["TPE1"] = artist
    frames = b""
    for name, text in fields.items():
        data = b"\x03" + text.encode("utf-8")
        frames += name.encode("ascii") + synchsafe(len(data)) + b"\0\0" + data
    return b"ID3\x04\0\0" + synchsafe(TAG_SIZE - 10) + frames.ljust(TAG_SIZE - 10, b"\0")


def process_start(pid):
    try:
        # comm can contain spaces and parentheses; fields after its final ')' are stable.
        fields = Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()
        return fields[19] if fields[0] != "Z" else ""
    except (OSError, IndexError):
        return ""


def atomic_json(path, data):
    fd, temporary = tempfile.mkstemp(dir=path.parent, prefix=path.name + ".")
    try:
        with os.fdopen(fd, "w") as output:
            json.dump(data, output, ensure_ascii=False)
            output.write("\n")
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


def read_json(path):
    try:
        if path.stat().st_size <= 65536:
            data = json.loads(path.read_text())
            if isinstance(data, dict):
                return data
    except (OSError, ValueError):
        pass
    return {}


class Mpv:
    def __init__(self, path):
        self.socket = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.socket.settimeout(2)
        try:
            self.socket.connect(str(path))
        except OSError:
            self.socket.close()
            raise RuntimeError("Play a stream before recording.") from None
        self.reader = self.socket.makefile("rb")
        self.sequence = 0

    def close(self):
        self.socket.close()
        self.reader.close()

    def send(self, command):
        self.sequence += 1
        self.socket.sendall((json.dumps({"command": command, "request_id": self.sequence}) + "\n").encode())
        return self.sequence

    def receive(self):
        line = self.reader.readline(65537)
        if not line or len(line) > 65536:
            raise RuntimeError("Playback ended.")
        return json.loads(line)

    def get(self, name):
        request = self.send(["get_property", name])
        while True:
            response = self.receive()
            if response.get("request_id") == request:
                return response.get("data") if response.get("error") == "success" else None

    def playing_path(self):
        if self.get("idle-active") is not False or self.get("pause") is not False:
            raise RuntimeError("Play a stream before recording.")
        path = self.get("path")
        if not isinstance(path, str) or urlsplit(path).scheme not in ("http", "https"):
            raise RuntimeError("Recording requires an HTTP or HTTPS radio stream.")
        return path

    def watch(self, expected, stopped):
        try:
            for index, name in enumerate(("pause", "idle-active", "path")):
                self.send(["observe_property", index, name])
            # A blocking read is intentional: playback events wake this daemon thread.
            self.socket.settimeout(None)
            while not stopped.is_set():
                event = self.receive()
                name, value = event.get("name"), event.get("data")
                if (event.get("event") in ("shutdown", "end-file")
                        or (event.get("event") == "property-change" and (
                            (name in ("pause", "idle-active") and value is not False)
                            or (name == "path" and value != expected)))):
                    break
        except (OSError, ValueError, RuntimeError):
            pass
        if not stopped.is_set():
            os.kill(os.getpid(), signal.SIGUSR1)


class WebRedirect(HTTPRedirectHandler):
    def redirect_request(self, request, response, code, message, headers, newurl):
        if urlsplit(newurl).scheme not in ("http", "https"):
            raise RuntimeError("The stream redirected to an unsupported URL.")
        return super().redirect_request(request, response, code, message, headers, newurl)


def open_stream(url):
    opener = build_opener(WebRedirect())
    for _ in range(5):
        if urlsplit(url).scheme not in ("http", "https"):
            raise RuntimeError("Unsupported stream URL.")
        response = opener.open(Request(url, headers={"Icy-MetaData": "1", "User-Agent": "SomaFM-Bar/1.11"}), timeout=5)
        content_type = response.headers.get_content_type()
        suffix = urlsplit(response.geturl()).path.lower()
        if (content_type in ("audio/x-scpls", "audio/x-mpegurl", "audio/mpegurl", "application/x-mpegurl")
                or suffix.endswith((".pls", ".m3u", ".m3u8"))):
            with response:
                body = response.read(262145)
            if len(body) > 262144:
                raise RuntimeError("The stream playlist is too large.")
            links = []
            for line in body.decode("utf-8-sig", "replace").splitlines():
                line = line.strip()
                if re.match(r"(?i)^file\d+=", line):
                    line = line.split("=", 1)[1].strip()
                elif not line or line.startswith(("#", "[")) or "=" in line.split("/", 1)[0]:
                    continue
                candidate = urljoin(response.geturl(), line)
                if urlsplit(candidate).scheme in ("http", "https"):
                    links.append(candidate)
            if not links:
                raise RuntimeError("The playlist has no HTTP audio stream.")
            url = links[0]
            continue
        try:
            interval = int(response.headers.get("icy-metaint", "0"))
            if not 0 < interval <= MAX_INTERVAL:
                raise RuntimeError("This stream does not provide usable song metadata.")
            if content_type in ("audio/aac", "audio/aacp"):
                codec = "aac"
            elif content_type in ("audio/mpeg", "audio/mp3"):
                codec = "mp3"
            elif content_type == "application/octet-stream":
                codec = "aac" if "aac" in suffix else "mp3"
            else:
                raise RuntimeError("Recording supports MP3 and AAC streams.")
            return response, interval, codec
        except BaseException:
            response.close()
            raise
    raise RuntimeError("The stream has too many nested playlists.")


def stream_title(metadata):
    match = re.search(rb"(?:^|;)\s*StreamTitle='(.*?)';", metadata, re.DOTALL | re.IGNORECASE)
    if not match:
        return ""
    raw = match.group(1)
    try:
        return clean_text(raw.decode("utf-8"))
    except UnicodeDecodeError:
        return clean_text(raw.decode("cp1252", "replace"))


def frame_size(data, codec):
    if data[0] != 255:
        return 0
    if codec == "aac":
        if (data[1] & 0xF6) != 0xF0 or ((data[2] >> 2) & 15) >= 13:
            return 0
        size = ((data[3] & 3) << 11) | (data[4] << 3) | (data[5] >> 5)
        return size if size >= (7 if data[1] & 1 else 9) else 0
    if data[1] & 0xE0 != 0xE0:
        return 0
    version, layer = (data[1] >> 3) & 3, (data[1] >> 1) & 3
    rate, sample = data[2] >> 4, (data[2] >> 2) & 3
    if version == 1 or layer != 1 or rate in (0, 15) or sample == 3:
        return 0  # MP3 = MPEG layer III; reject reserved/free-format headers.
    rates = ([0, 32, 40, 48, 56, 64, 80, 96, 112, 128, 160, 192, 224, 256, 320]
             if version == 3 else [0, 8, 16, 24, 32, 40, 48, 56, 64, 80, 96, 112, 128, 144, 160])
    sample_rate = [44100, 48000, 32000][sample] // {3: 1, 2: 2, 0: 4}[version]
    return (144000 if version == 3 else 72000) * rates[rate] // sample_rate + ((data[2] >> 1) & 1)


class Songs:
    def __init__(self, directory, station, codec, report, budget=None):
        self.directory, self.station, self.codec, self.report = directory, station, codec, report
        self.buffer = bytearray()
        self.offset = 0
        self.markers = []
        self.title = ""
        self.file = None
        self.path = None
        self.saved = 0
        self.frames = 0
        self.skipped = 0
        self.started = ""
        self.capture = False
        self.budget = budget
        self.file_bytes = 0

    def write(self, data):
        if self.budget:
            self.budget.account(len(data))
        self.file.write(data)
        self.file_bytes += len(data)

    def metadata(self, title):
        if not title:
            return
        # The first title is already in progress. Wait for the next song's start.
        if not self.title and not self.markers:
            self.title = title
            self.report(title=title, waiting=True, starting=False)
        elif title != (self.markers[-1][1] if self.markers else self.title):
            self.markers.append((self.offset + len(self.buffer), title))

    def feed(self, data):
        self.buffer.extend(data)
        position = 0
        while len(self.buffer) - position >= 7:
            size = frame_size(self.buffer[position:position + 7], self.codec)
            if not size:
                position += 1
                self.skipped += 1
                if self.skipped > 1024 * 1024:
                    raise RuntimeError("The stream contains unsupported or damaged audio.")
                continue
            if len(self.buffer) - position < size:
                break
            while self.markers and self.markers[0][0] <= self.offset + position:
                _, title = self.markers.pop(0)
                if title != self.title:
                    self.finish()
                    self.title = title
                    self.capture = True
            if not self.capture:
                position += size
                continue
            if self.file is None:
                self.started = datetime.now().strftime("%Y-%m-%d %H%M%S")
                self.file = tempfile.NamedTemporaryFile(mode="w+b", prefix=".recording-", suffix=".part." + self.codec,
                                                       dir=self.directory, delete=False)
                self.path = Path(self.file.name)
                self.write(id3_tag(self.title, self.station))
                self.report(starting=False, waiting=False, title=self.title, file=str(self.path))
            self.write(self.buffer[position:position + size])
            self.frames += 1
            position += size
        del self.buffer[:position]
        self.offset += position

    def finish(self):
        if self.file is None:
            return
        self.file.flush()
        os.fsync(self.file.fileno())
        self.file.close()
        self.file = None
        stem = self.started + " - " + filename(self.title)
        for number in range(1, 10000):
            suffix = "" if number == 1 else f" ({number})"
            target = self.directory / (stem + suffix + "." + self.codec)
            try:
                # Hard-link publication is atomic and never overwrites another recording.
                os.link(self.path, target)
                break
            except FileExistsError:
                continue
        else:
            raise RuntimeError("Too many recordings with the same filename.")
        self.path.unlink()
        self.file_bytes = 0
        self.saved += 1
        self.report(file=str(target), saved=self.saved)

    def discard(self):
        if self.file:
            # Closing may fail when another process filled the disk; still unlink it.
            with contextlib.suppress(OSError):
                self.file.close()
            self.file = None
        if self.path:
            self.path.unlink(missing_ok=True)
        if self.budget:
            self.budget.used -= self.file_bytes
        self.file_bytes = 0


class PlaybackChanged(BaseException):
    pass


class StorageLimit(RuntimeError):
    pass


class Budget:
    def __init__(self, directory, config):
        def setting(key, default):
            value = config.get(key)
            return value if isinstance(value, (int, float)) and not isinstance(value, bool) and value > 0 else default

        self.directory = directory
        self.quota = int(setting("recordingQuotaMiB", 20480) * 1024 * 1024)
        self.reserve = int(setting("recordingReserveMiB", 5120) * 1024 * 1024)
        self.percent = min(100, setting("recordingReservePercent", 5))
        self.used = 0

    def check(self, additional=0):
        if self.used + additional > self.quota:
            raise StorageLimit("Recording stopped: the session quota was reached.")
        disk = shutil.disk_usage(self.directory)
        reserve = max(self.reserve, int(disk.total * self.percent / 100))
        if disk.free - additional <= reserve:
            raise StorageLimit("Recording stopped to keep disk space free for the OS.")

    def account(self, additional):
        self.check(additional)
        self.used += additional


class RecordingStopped(BaseException):
    pass


class Recorder:
    def __init__(self):
        self.runtime = Path(os.environ["XDG_RUNTIME_DIR"]) / "somafm-bar"
        self.runtime.mkdir(mode=0o700, parents=True, exist_ok=True)
        self.state_path = self.runtime / "recording.json"
        self.pid_path = self.runtime / "recorder.pid"
        self.state = read_json(self.state_path)

    @contextlib.contextmanager
    def lock(self):
        with (self.runtime / "recorder.lock").open("a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            yield

    def tracked_pid(self):
        data = read_json(self.pid_path)
        pid, start = data.get("pid"), data.get("start")
        if isinstance(pid, int) and pid > 1 and start and process_start(pid) == start:
            return pid
        return None

    def report(self, **changes):
        self.state.update(changes)
        atomic_json(self.state_path, self.state)

    def status(self):
        self.state = read_json(self.state_path)
        if self.state.get("active") and not self.tracked_pid():
            partial = Path(self.state.get("file") or ".")
            directory = Path(self.state.get("directory") or ".")
            if (partial.parent == directory and partial.name.startswith(".recording-")
                    and partial.name.endswith((".part.mp3", ".part.aac"))):
                partial.unlink(missing_ok=True)
            self.report(active=False, starting=False, paused=False, waiting=False, file="",
                        error="Recording was interrupted. The unfinished song was discarded.")
        return {"active": False, "starting": False, "error": "", **self.state}

    def start(self, station):
        if self.tracked_pid():
            return self.status()
        with contextlib.closing(Mpv(self.runtime / "mpvd.sock")) as mpv:
            mpv.playing_path()
        music = ""
        if shutil.which("xdg-user-dir"):
            result = subprocess.run(["xdg-user-dir", "MUSIC"], capture_output=True, text=True, timeout=3)
            if result.returncode == 0:
                music = result.stdout.strip()
        music = Path(music) if music and Path(music).is_absolute() else Path.home() / "Music"
        directory = music / "SomaFM"
        directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        Budget(directory, read_json(Path(__file__).with_name("config.json"))).check(TAG_SIZE)
        self.state = {"active": True, "starting": True, "directory": str(directory), "file": "",
                      "title": "", "saved": 0, "waiting": True, "paused": False, "error": ""}
        # The worker takes recorder.lock before writing; publish its PID and initial state first.
        child = subprocess.Popen([sys.executable, str(Path(__file__).resolve()), "_run", station,
                                  str(directory)], stdin=subprocess.DEVNULL,
                                 stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                 start_new_session=True, close_fds=True)
        try:
            atomic_json(self.pid_path, {"pid": child.pid, "start": process_start(child.pid)})
            self.report()
        except BaseException:
            child.terminate()
            raise
        return self.state

    def stop(self):
        pid = self.tracked_pid()
        if pid:
            with contextlib.suppress(ProcessLookupError):
                os.kill(pid, signal.SIGTERM)
            deadline = time.monotonic() + 7
            while self.tracked_pid() == pid and time.monotonic() < deadline:
                time.sleep(0.05)
            if self.tracked_pid() == pid:
                raise RuntimeError("Recording is still finishing. Try Stop recording again.")
        return self.status()

    def run(self, station, directory):
        config = read_json(Path(__file__).with_name("config.json"))
        budget = Budget(Path(directory), config)
        songs = None
        error = ""

        def stop(_signal, _frame):
            raise RecordingStopped()

        def playback_changed(_signal, _frame):
            raise PlaybackChanged()

        signal.signal(signal.SIGTERM, stop)
        signal.signal(signal.SIGINT, stop)
        signal.signal(signal.SIGUSR1, signal.SIG_IGN)
        try:
            with self.lock():
                self.state = read_json(self.state_path)
            while True:
                budget.check(TAG_SIZE)
                mpv = None
                try:
                    mpv = Mpv(self.runtime / "mpvd.sock")
                    expected = mpv.playing_path()
                except (OSError, RuntimeError):
                    if mpv:
                        mpv.close()
                    self.report(starting=False, paused=True, waiting=True, title="", file="")
                    time.sleep(0.5)
                    continue
                data_root = Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local/share")
                override = read_json(data_root / "somafm-bar/override.json")
                name = clean_text(override.get("name") or config.get("station") or station)
                destination = Path(directory) / filename(name, 100)
                destination.mkdir(mode=0o700, exist_ok=True)
                self.report(directory=str(destination), paused=False, starting=True, waiting=True, title="", error="")
                response, songs = None, None
                stopped = threading.Event()
                signal.signal(signal.SIGUSR1, playback_changed)
                try:
                    threading.Thread(target=mpv.watch, args=(expected, stopped), daemon=True).start()
                    response, interval, codec = open_stream(expected)
                    # Count retained files, with the current song included until discarded.
                    def report(**changes):
                        if "saved" in changes:
                            changes["saved"] = self.state.get("saved", 0) + 1
                        self.report(**changes, bytes=budget.used)

                    songs = Songs(destination, name, codec, report, budget)
                    while True:
                        remaining = interval
                        while remaining:
                            budget.check(min(remaining, 65536) + TAG_SIZE)
                            audio = response.read(min(remaining, 65536))
                            if not audio:
                                raise OSError("The stream disconnected. Waiting to reconnect.")
                            songs.feed(audio)
                            remaining -= len(audio)
                        length = response.read(1)
                        if not length:
                            raise OSError("The stream disconnected. Waiting to reconnect.")
                        length = length[0] * 16
                        metadata = b""
                        while len(metadata) < length:
                            part = response.read(length - len(metadata))
                            if not part:
                                raise OSError("The stream disconnected. Waiting to reconnect.")
                            metadata += part
                        songs.metadata(stream_title(metadata.rstrip(b"\0")))
                except PlaybackChanged:
                    pass
                except OSError as failure:
                    self.report(error=clean_text(failure), paused=True, starting=False)
                    time.sleep(2)
                finally:
                    signal.signal(signal.SIGUSR1, signal.SIG_IGN)
                    stopped.set()
                    if response:
                        response.close()
                    with contextlib.suppress(OSError):
                        mpv.socket.shutdown(socket.SHUT_RDWR)
                    mpv.close()
                    if songs:
                        songs.discard()
                time.sleep(0.1)
        except RecordingStopped:
            pass
        except (OSError, ValueError, RuntimeError) as failure:
            error = clean_text(failure)
        finally:
            signal.signal(signal.SIGTERM, signal.SIG_IGN)
            signal.signal(signal.SIGINT, signal.SIG_IGN)
            signal.signal(signal.SIGUSR1, signal.SIG_IGN)
            self.report(active=False, starting=False, paused=False, waiting=False, file="", error=error, bytes=budget.used)


def main():
    os.umask(0o077)
    recorder = Recorder()
    action = sys.argv[1] if len(sys.argv) > 1 else "status"
    if action == "_run" and len(sys.argv) == 4:
        recorder.run(*sys.argv[2:])
        return 0
    with recorder.lock():
        try:
            if action == "start" and len(sys.argv) == 3:
                state = recorder.start(clean_text(sys.argv[2]))
            elif action == "stop":
                state = recorder.stop()
            elif action == "status":
                state = recorder.status()
            else:
                raise RuntimeError("Use record start, stop, or status.")
        except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as failure:
            if not recorder.tracked_pid():
                recorder.report(active=False, starting=False, error=clean_text(failure))
            print(json.dumps({**recorder.status(), "error": clean_text(failure)}))
            return 4
    print(json.dumps(state, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
