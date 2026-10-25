#!/usr/bin/env python3
"""Check station ordering, output names, and playback without audio or network."""

import json
from pathlib import Path
import subprocess
import unittest

import security


ROOT = Path(__file__).resolve().parents[1]


class PlayerBehaviorTests(unittest.TestCase):
    def setUp(self):
        security.CatalogSecurityTests.setUp(self)

    def action(self, *args):
        result = subprocess.run([str(ROOT / "player"), *args], env=self.env,
                                capture_output=True, text=True, timeout=15, check=True)
        self.assertEqual(result.stderr, "")
        return json.loads(result.stdout)

    def test_popularity_is_numeric_with_alphabetical_ties(self):
        channels = []
        for name, listeners in [("Zulu", "9"), ("Bravo", "120"),
                                ("Alpha", "120"), ("Missing", None)]:
            station = dict(security.CATALOG["channels"][0], id=name.lower(),
                           title=name, listeners=listeners,
                           playlists=[{"format": "mp3", "url": "https://example.test/" + name}])
            channels.append(station)
        self.env["SOMA_TEST_CATALOG"] = json.dumps({"channels": channels})
        stations = self.action("stations")
        self.assertEqual([s["name"] for s in stations], ["Alpha", "Bravo", "Zulu", "Missing"])
        self.assertEqual([s["listeners"] for s in stations], [120, 120, 9, 0])

    def test_output_labels_keep_distinguishing_ports(self):
        prefix = "500 Series Chipset Family On-Package High Definition Audio "
        names = ["HDMI 3", "HDMI 2", "HDMI 1", "Speaker", "Headphones"]
        sinks = [{"name": "hardware_" + str(i), "description": prefix + name,
                  "properties": {"node.nick": name}}
                 for i, name in enumerate(names)]
        self.env["SOMA_TEST_SINKS"] = json.dumps(sinks)
        pactl = self.bin / "pactl"
        pactl.write_text('#!/usr/bin/env python3\nimport os\nprint(os.environ["SOMA_TEST_SINKS"])\n')
        pactl.chmod(0o700)
        outputs = self.action("outputs")["outputs"]
        self.assertEqual([o["label"] for o in outputs], names)
        self.assertEqual(outputs[0]["description"], prefix + "HDMI 3")

    def prepare_fake_player(self):
        self.env["SOMA_TEST_MPV_ARGS"] = str(self.base / "mpv-args.json")
        self.env["SOMA_TEST_COMMANDS"] = str(self.base / "commands.jsonl")
        mpv = self.bin / "mpv"
        mpv.write_text('''#!/usr/bin/env python3
import json, os, socket, sys
from pathlib import Path

Path(os.environ["SOMA_TEST_MPV_ARGS"]).write_text(json.dumps(sys.argv[1:]))
path = next(a.split("=", 1)[1] for a in sys.argv[1:] if a.startswith("--input-ipc-server="))
state = {"pause": False, "idle-active": False, "media-title": "Test stream", "mute": False,
         "volume": 70, "audio-device": "auto"}
running = True
server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
server.bind(path)
server.listen()
try:
    while running:
        connection, _ = server.accept()
        with connection:
            connection.settimeout(0.03)
            buffer = b""
            while running:
                try:
                    part = connection.recv(65536)
                except socket.timeout:
                    break
                if not part:
                    break
                buffer += part
                while b"\\n" in buffer:
                    line, buffer = buffer.split(b"\\n", 1)
                    request = json.loads(line)
                    command = request["command"]
                    with open(os.environ["SOMA_TEST_COMMANDS"], "a") as log:
                        log.write(json.dumps(command) + "\\n")
                    response = {"error": "success", "request_id": request["request_id"]}
                    if command[0] == "get_property":
                        response["data"] = state.get(command[1])
                    elif command[0] == "set_property":
                        state[command[1]] = command[2]
                    elif command[0] == "loadfile":
                        state["idle-active"] = False
                        state["media-title"] = command[1]
                    elif command[0] == "quit":
                        running = False
                    connection.sendall((json.dumps(response) + "\\n").encode())
finally:
    server.close()
    Path(path).unlink(missing_ok=True)
''')
        mpv.chmod(0o700)
        self.addCleanup(self.stop_fake_player)

    def stop_fake_player(self):
        subprocess.run([str(ROOT / "player"), "stop"], env=self.env,
                       capture_output=True, timeout=10, check=True)

    def commands(self):
        return [json.loads(line) for line in (self.base / "commands.jsonl").read_text().splitlines()]

    def test_station_selection_starts_when_stopped(self):
        self.prepare_fake_player()
        selected = self.action("switch", "First", "https://example.test/first")
        self.assertTrue(selected["running"])
        self.assertFalse(selected["paused"])
        args = json.loads((self.base / "mpv-args.json").read_text())
        self.assertIn("https://example.test/first", args)

    def test_station_selection_replaces_a_playing_stream(self):
        self.prepare_fake_player()
        self.action("switch", "First", "https://example.test/first")
        selected = self.action("switch", "Second", "https://example.test/second")
        self.assertTrue(selected["running"])
        self.assertIn(["loadfile", "https://example.test/second", "replace"], self.commands())
        self.assertIn(["script-message", "somafm-station", "Second"], self.commands())

    def test_station_selection_resumes_when_paused(self):
        self.prepare_fake_player()
        self.action("switch", "First", "https://example.test/first")
        self.assertTrue(self.action("pause")["paused"])
        selected = self.action("switch", "Second", "https://example.test/second")
        self.assertFalse(selected["paused"])
        self.assertTrue(selected["running"])


if __name__ == "__main__":
    unittest.main()
