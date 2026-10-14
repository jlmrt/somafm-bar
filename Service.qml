import QtQuick
import Quickshell
import Quickshell.Hyprland
import Quickshell.Io

// Watches for the Omarchy screensaver window and plays a short glitch burst on
// the SomaFM stream, so the machine slipping into its screensaver (or the Fun
// hotkey raising it) announces itself instead of going silently black.
//
// This lives in the shell, not the bar widget: the widget is instantiated once
// per monitor and can be hidden, while the service must keep watching for the
// whole session.
Item {
  id: root

  property var shell: null

  // Resolved next to this file; the shell strips `__sourceDir` from the manifest
  // it hands third-party plugins, so we cannot lean on that.
  readonly property string playerPath: Qt.resolvedUrl("player").toString().replace(/^file:\/\//, "")
  readonly property string screensaverClass: "org.omarchy.screensaver"

  function eventParts(event, count) {
    try {
      if (event && event.parse) return event.parse(count)
    } catch (error) {}
    return String(event && event.data ? event.data : "").split(",")
  }

  function handleEvent(event) {
    if (!root.playerPath) return
    if (String(event && event.name ? event.name : "") !== "openwindow") return
    var parts = root.eventParts(event, 4)
    if (String(parts[2] || "") !== root.screensaverClass) return
    if (burstProcess.running) return
    burstProcess.running = true
  }

  Connections {
    target: Hyprland
    function onRawEvent(event) { root.handleEvent(event) }
  }

  Process {
    id: burstProcess
    command: [root.playerPath, "fun", "burst"]
  }
}
