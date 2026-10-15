import QtQuick
import QtQuick.Controls
import Quickshell
import Quickshell.Hyprland
import Quickshell.Io
import qs.Commons
import qs.Ui

BarWidget {
  id: root

  moduleName: "io.github.ltillegal.somafm-bar"

  property bool opened: false
  property bool copied: false

  property bool playerRunning: false
  property bool playerPaused: false
  property bool playerMuted: false
  readonly property bool playing: root.playerRunning && !root.playerPaused
  property color playingColor: "#2ecc71"
  property string streamUrl: ""
  readonly property string qualityText: {
    var url = root.streamUrl
    if (typeof url !== "string" || url === "") return ""
    var match = url.match(/[-_]([0-9]{1,4})[-_]([a-zA-Z0-9]+)(?:[?#]|$)/)
    return match ? match[1] + " kbps " + match[2].toUpperCase() : ""
  }
  property string playerTitle: ""
  property string stationName: "SomaFM"
  property int playerVolume: 70
  property int reportedVolume: 70
  property int pendingVolume: -1
  property bool statusReady: false
  property string pendingAction: ""
  property string pendingOutput: ""

  // Fun / glitch: raise the Omarchy screensaver and glitch the audio along with it.
  // Hidden: the panel only appears when revealed by Ctrl+click on the widget.
  property bool funRevealed: false
  property bool funGlitchOn: false
  property string funMode: "airplay"
  property string funDriver: "timer"
  property int funIntensity: 70
  property int funBpm: 0
  property bool funAnnounce: true
  property color funColor: "#ff4de1"

  property var audioOutputs: []
  property string audioOutput: ""
  property string outputsBuffer: ""
  property string statusBuffer: ""

  property var allStations: []
  property var favStations: []
  property string stationsBuffer: ""
  property string favsBuffer: ""
  property string searchText: ""
  property bool stationsLoaded: false
  property bool favsLoaded: false

  readonly property string playerPath: Qt.resolvedUrl("player").toString().replace(/^file:\/\//, "")
  readonly property string statusPath: Quickshell.env("XDG_RUNTIME_DIR") + "/somafm-bar/status.json"
  readonly property string funStatusPath: Quickshell.env("XDG_RUNTIME_DIR") + "/somafm-bar/fun.json"
  readonly property string dataHome: {
    var dir = Quickshell.env("XDG_DATA_HOME")
    return (dir && dir.length > 0) ? dir : Quickshell.env("HOME") + "/.local/share"
  }
  readonly property string funPrefsPath: dataHome + "/somafm-bar/fun-prefs.json"

  function singleLineText(value, limit) {
    return String(value || "").replace(/[\r\n\t]+/g, " ").slice(0, limit)
  }

  function safeTooltipText(value) {
    return root.singleLineText(value, 160).replace(/</g, "‹").replace(/>/g, "›")
  }

  function outputLabel(value) {
    var label = root.singleLineText(value, 80)
    return label.length > 30 ? label.slice(0, 29) + "…" : label
  }

  function applyPlayerState(raw) {
    try {
      if (typeof raw !== "string" || raw.length > 65536) return
      var state = JSON.parse(raw || "{}")
      root.playerRunning = state.running === true
      root.playerPaused = state.paused === true
      root.playerMuted = state.muted === true
      var nextVolume = Math.round(Number(state.volume === undefined ? 70 : state.volume))
      root.reportedVolume = isFinite(nextVolume)
        ? Math.max(0, Math.min(100, nextVolume)) : 70
      if (root.pendingVolume < 0) root.playerVolume = root.reportedVolume
      root.playerTitle = root.singleLineText(
        state.title || "", 160)
      var nextUrl = root.singleLineText(state.url || "", 200)
      if (nextUrl !== "") root.streamUrl = nextUrl
      root.audioOutput = root.singleLineText(state.output, 160)
      var station = root.singleLineText(state.station && state.station.name, 80)
      if (station !== "") root.stationName = station
    } catch (error) {
      return
    }
  }

  function applyFunState(raw) {
    try {
      if (typeof raw !== "string") return
      var state = JSON.parse(raw || "{}")
      root.funGlitchOn = state.on === true
    } catch (error) {
      return
    }
  }

  function applyFunPrefs(raw) {
    try {
      if (typeof raw !== "string") return
      var prefs = JSON.parse(raw || "{}")
      var mode = String(prefs.mode || "")
      if (mode === "airplay" || mode === "local" || mode === "both") root.funMode = mode
      var driver = String(prefs.driver || "")
      if (driver === "timer" || driver === "screensaver") root.funDriver = driver
      var intensity = Math.round(Number(prefs.intensity))
      if (isFinite(intensity)) root.funIntensity = Math.max(0, Math.min(100, intensity))
      var bpm = Math.round(Number(prefs.bpm))
      if (isFinite(bpm)) root.funBpm = Math.max(0, Math.min(180, bpm))
      if (typeof prefs.announce === "boolean") root.funAnnounce = prefs.announce
    } catch (error) {
      return
    }
  }

  function refreshStatus() {
    if (statusProcess.running) return
    statusProcess.command = [root.playerPath, "status"]
    statusProcess.running = true
  }

  function loadStations() {
    if (stationsProcess.running) return
    root.stationsBuffer = ""
    stationsProcess.command = [root.playerPath, "stations"]
    stationsProcess.running = true
  }

  function loadFavs() {
    if (favsProcess.running) return
    root.favsBuffer = ""
    favsProcess.command = [root.playerPath, "fav-list"]
    favsProcess.running = true
  }

  function runPlayerAction(action) {
    if (actionProcess.running || outputProcess.running) {
      root.pendingAction = action
      return
    }
    actionProcess.command = [root.playerPath, action]
    actionProcess.running = true
  }

  function runFunCommand(action) {
    if (funProcess.running) {
      funProcess.queued = action
      return
    }
    if (action === "start") {
      funProcess.command = [root.playerPath, "fun", "start",
        "--mode", root.funMode, "--driver", root.funDriver,
        "--intensity", String(root.funIntensity), "--bpm", String(root.funBpm),
        "--announce", root.funAnnounce ? "on" : "off"]
    } else if (action === "set") {
      funProcess.command = [root.playerPath, "fun", "set",
        "--mode", root.funMode, "--driver", root.funDriver,
        "--intensity", String(root.funIntensity), "--bpm", String(root.funBpm),
        "--announce", root.funAnnounce ? "on" : "off"]
    } else {
      funProcess.command = [root.playerPath, "fun", "stop"]
    }
    funProcess.running = true
  }

  function toggleFun() {
    root.runFunCommand(root.funGlitchOn ? "stop" : "start")
  }

  function updateFun() {
    root.runFunCommand(root.funGlitchOn ? "start" : "set")
  }

  function revealFun() {
    var win = root.QsWindow.window
    var focused = Hyprland.focusedMonitor
    if (win && win.screen && focused && focused.name && win.screen.name !== focused.name) return
    root.funRevealed = true
    root.open()
  }

  function pump() {
    if (actionProcess.running || outputProcess.running) return
    if (root.pendingVolume >= 0) { root.flushVolume(); return }
    if (root.pendingAction !== "") {
      var action = root.pendingAction
      root.pendingAction = ""
      actionProcess.command = [root.playerPath, action]
      actionProcess.running = true
      return
    }
    if (root.pendingOutput !== "") {
      var id = root.pendingOutput
      root.pendingOutput = ""
      outputProcess.command = [root.playerPath, "output", id]
      outputProcess.running = true
    }
  }

  function loadOutputs() {
    if (outputsProcess.running) return
    root.outputsBuffer = ""
    outputsProcess.command = [root.playerPath, "outputs"]
    outputsProcess.running = true
  }

  function selectOutput(id) {
    if (typeof id !== "string" || id === "") return
    if (id === root.audioOutput) return
    if (outputProcess.running || actionProcess.running) {
      root.pendingOutput = id
      return
    }
    outputProcess.command = [root.playerPath, "output", id]
    outputProcess.running = true
  }

  function changeVolume(delta) {
    var current = pendingVolume >= 0 ? pendingVolume : playerVolume
    pendingVolume = Math.max(0, Math.min(100, current + (delta > 0 ? 5 : -5)))
    playerVolume = pendingVolume
    flushVolume()
  }

  function flushVolume() {
    if (actionProcess.running || pendingVolume < 0) return
    actionProcess.submittedVolume = pendingVolume
    actionProcess.command = [playerPath, "volume", String(pendingVolume)]
    actionProcess.running = true
  }

  function open() {
    root.opened = true
    root.refreshStatus()
    root.loadOutputs()
    root.loadStations()
    root.loadFavs()
    root.searchText = ""
  }

  function close() {
    root.opened = false
    root.funRevealed = false
  }

  function isFavorite(url) {
    for (var i = 0; i < root.favStations.length; i++) {
      if (root.favStations[i].url === url) return true
    }
    return false
  }

  function toggleFavorite(station) {
    if (!station || typeof station.url !== "string") return
    if (favToggleProcess.running) return
    if (isFavorite(station.url)) {
      favToggleProcess.command = [root.playerPath, "fav-remove", station.url]
    } else {
      favToggleProcess.command = [root.playerPath, "fav-add", station.name, station.url]
    }
    favToggleProcess.running = true
  }

  function switchStation(station) {
    if (!station || typeof station.url !== "string") return
    if (switchProcess.running) return
    switchProcess.command = [root.playerPath, "switch", station.name, station.url]
    switchProcess.running = true
    Qt.callLater(root.refreshStatus)
  }

  function filteredStations() {
    var q = (root.searchText || "").toLowerCase()
    var list = root.allStations
    if (!q) return list.slice(0, 200)
    var res = []
    for (var i = 0; i < list.length && res.length < 200; i++) {
      var s = list[i]
      var t = ((s.name||"") + " " + (s.title||"") + " " + (s.description||"")).toLowerCase()
      if (t.indexOf(q) >= 0) res.push(s)
    }
    return res
  }
  function toggle() {
    if (root.opened) root.close()
    else root.open()
  }

  function copyTitle() {
    if (root.playerTitle === "") return
    Quickshell.execDetached(["wl-copy", root.playerTitle])
    root.copied = true
    closeTimer.restart()
  }

  implicitWidth: button.implicitWidth
  implicitHeight: button.implicitHeight

  FileView {
    path: root.statusReady ? root.statusPath : ""
    watchChanges: true
    atomicWrites: true
    printErrors: false
    onLoaded: root.applyPlayerState(text())
    onFileChanged: reload()
  }

  FileView {
    path: root.funStatusPath
    watchChanges: true
    atomicWrites: true
    printErrors: false
    onLoaded: root.applyFunState(text())
    onFileChanged: reload()
  }

  FileView {
    path: root.funPrefsPath
    watchChanges: true
    atomicWrites: true
    printErrors: false
    onLoaded: root.applyFunPrefs(text())
    onFileChanged: reload()
  }

  Process {
    id: statusProcess
    command: []
    stdout: SplitParser {
      onRead: function(line) { root.statusBuffer += line }
    }
    onExited: function(exitCode) {
      var buffer = root.statusBuffer
      root.statusBuffer = ""
      if (exitCode === 0) {
        root.statusReady = true
        root.applyPlayerState(buffer)
      }
    }
  }

  Process {
    id: funProcess
    command: []
    property string queued: ""
    onExited: function(exitCode) {
      root.refreshStatus()
      if (queued !== "") {
        var next = queued
        queued = ""
        Qt.callLater(function() { root.runFunCommand(next) })
      }
    }
  }

  Process {
    id: actionProcess
    property int submittedVolume: -1
    command: []
    onExited: function(exitCode) {
      if (exitCode === 0) root.statusReady = true
      if (submittedVolume >= 0) {
        root.statusReady = true
        if (exitCode === 0) {
          root.reportedVolume = submittedVolume
          if (root.pendingVolume === submittedVolume) {
            root.pendingVolume = -1
            root.playerVolume = submittedVolume
          }
        } else {
          if (root.pendingVolume === submittedVolume) {
            root.pendingVolume = -1
            root.playerVolume = root.reportedVolume
          }
        }
        submittedVolume = -1
      }
      Qt.callLater(root.pump)
    }
  }

  Process {
    id: outputsProcess
    command: []
    stdout: SplitParser {
      onRead: function(line) { root.outputsBuffer += line }
    }
    onExited: function(exitCode) {
      var buffer = root.outputsBuffer
      root.outputsBuffer = ""
      if (exitCode !== 0) return
      var list = []
      try {
        var parsed = JSON.parse(buffer || "{}")
        var items = parsed && parsed.outputs
        if (items && typeof items.length === "number") {
          for (var i = 0; i < items.length; i++) {
            var item = items[i]
            if (!item || typeof item.id !== "string" || item.id === "") continue
            list.push({
              id: item.id,
              label: root.singleLineText(item.label || item.id, 80)
            })
          }
        }
      } catch (error) {
        return
      }
      root.audioOutputs = list
    }
  }

  Process {
    id: outputProcess
    command: []
    onExited: function(exitCode) {
      if (exitCode === 0) root.loadOutputs()
      root.refreshStatus()
      Qt.callLater(root.pump)
    }
  }

  Process {
    id: stationsProcess
    command: []
    stdout: SplitParser {
      onRead: function(line) { root.stationsBuffer += line }
    }
    onExited: function(exitCode) {
      var buffer = root.stationsBuffer
      root.stationsBuffer = ""
      if (exitCode !== 0) return
      try {
        var parsed = JSON.parse(buffer || "[]")
        if (parsed && typeof parsed.length === "number") {
          var list = []
          for (var i = 0; i < parsed.length; i++) {
            var s = parsed[i]
            if (!s || typeof s.url !== "string") continue
            list.push({
              id: s.id || s.url,
              name: root.singleLineText(s.name || s.title || "Station", 120),
              url: s.url,
              title: root.singleLineText(s.title || s.name || "", 120),
              description: root.singleLineText(s.description || "", 200)
            })
          }
          root.allStations = list
          root.stationsLoaded = true
        }
      } catch (e) {}
    }
  }

  Process {
    id: favsProcess
    command: []
    stdout: SplitParser {
      onRead: function(line) { root.favsBuffer += line }
    }
    onExited: function(exitCode) {
      var buffer = root.favsBuffer
      root.favsBuffer = ""
      if (exitCode !== 0) return
      try {
        var parsed = JSON.parse(buffer || "[]")
        if (parsed && typeof parsed.length === "number") {
          var list = []
          for (var i = 0; i < parsed.length; i++) {
            var s = parsed[i]
            if (!s || typeof s.url !== "string") continue
            list.push({
              id: s.url,
              name: root.singleLineText(s.name || "Station", 120),
              url: s.url
            })
          }
          root.favStations = list
          root.favsLoaded = true
        }
      } catch (e) {}
    }
  }

  Process {
    id: switchProcess
    command: []
    onExited: function(exitCode) {
      root.refreshStatus()
      root.loadFavs()
    }
  }

  Process {
    id: favToggleProcess
    command: []
    onExited: function(exitCode) {
      root.loadFavs()
    }
  }

  Component.onCompleted: {
    root.refreshStatus()
    root.loadOutputs()
    root.loadStations()
    root.loadFavs()
  }

  Timer {
    id: closeTimer
    interval: 200
    onTriggered: {
      root.copied = false
      root.close()
    }
  }

  WidgetButton {
    id: button
    anchors.fill: parent
    bar: root.bar
    text: "\uf001"
    active: root.playing
    activeColor: root.playingColor
    tooltipText: root.playerRunning
      ? (root.playerPaused ? "Soma paused: " : "Soma playing: ")
        + root.safeTooltipText(root.playerTitle)
        + (root.qualityText !== "" ? "  ·  " + root.qualityText : "")
        + "  ·  " + root.playerVolume + "%"
      : root.stationName

    onPressed: function(mouseButton) {
      if (!root.bar) return
      if (mouseButton === Qt.RightButton) {
        root.runPlayerAction("stop")
        return
      }
      if (mouseButton === Qt.MiddleButton) {
        root.runPlayerAction(root.playerRunning ? "toggle" : "play")
        return
      }
      root.toggle()
    }

    onWheelMoved: function(delta) {
      root.changeVolume(delta)
    }
  }

  // Hidden Fun entry point. One handler wins per plugin id; each live widget
  // (one per monitor) gets the broadcast and only the focused screen reveals.
  //   omarchy-shell io.github.ltillegal.somafm-bar fun
  IpcHandler {
    target: "io.github.ltillegal.somafm-bar"

    function fun(): void {
      root.broadcast("revealFun")
    }
  }

  KeyboardPanel {
    id: popup
    anchorItem: root
    bar: root.bar
    owner: root
    open: root.opened
    focusTarget: keyCatcher
    contentWidth: popup.fittedContentWidth(Style.space(300))
    contentHeight: popup.fittedContentHeight(popupColumn.implicitHeight)

    PanelKeyCatcher {
      id: keyCatcher
      anchors.fill: parent
      onCloseRequested: root.close()

      Column {
        id: popupColumn
        anchors.fill: parent
        spacing: Style.spacing.controlGap

        Row {
          id: titleRow
          width: popupColumn.width
          spacing: Style.spacing.controlGap

          Text {
            width: titleRow.width - copyButton.width - titleRow.spacing
            text: root.playerTitle !== "" ? root.playerTitle : root.stationName
            textFormat: Text.PlainText
            color: Color.foreground
            font.family: Style.font.family
            font.pixelSize: Style.font.body
            font.bold: true
            elide: Text.ElideRight
            maximumLineCount: 2
            wrapMode: Text.WordWrap
          }

          PanelActionButton {
            id: copyButton
            iconText: root.copied ? "\uf00c" : "\uf0c5"
            tooltipText: root.copied ? "Copied" : "Copy title"
            enabled: root.playerTitle !== ""
            onClicked: root.copyTitle()
          }
        }

        Text {
          width: popupColumn.width
          text: root.playerRunning
            ? (root.playerPaused ? "Paused" : "Playing")
              + (root.qualityText !== "" ? "  ·  " + root.qualityText : "")
              + (root.playerMuted ? "  ·  muted" : "  ·  " + root.playerVolume + "%")
            : "Stopped — press Play to start"
          textFormat: Text.PlainText
          color: root.playing ? root.playingColor : Color.foreground
          opacity: 0.65
          font.family: Style.font.family
          font.pixelSize: Style.font.bodySmall
          elide: Text.ElideRight
        }

        Row {
          spacing: Style.spacing.controlGap

          Button {
            iconText: root.playing ? "\uf04c" : "\uf04b"
            text: root.playing ? "Pause" : "Play"
            active: root.playing
            foreground: root.playing ? root.playingColor : Color.foreground
            onClicked: root.runPlayerAction(root.playerRunning ? "toggle" : "play")
          }

          Button {
            iconText: "\uf04d"
            text: "Stop"
            onClicked: root.runPlayerAction("stop")
          }
        }

        PanelSlider {
          id: volumeSlider
          width: popupColumn.width
          bar: root.bar
          value: root.playerVolume
          minimum: 0
          maximum: 100
          step: 5
          integer: true
          onMoved: function(value) {
            root.pendingVolume = value
            root.playerVolume = value
            root.flushVolume()
          }
          onReleased: root.flushVolume()
          onRightClicked: root.runPlayerAction(root.playerRunning ? "toggle" : "play")
        }

        Column {
          id: funColumn
          width: popupColumn.width
          spacing: Style.spacing.controlGap

          Item {
            id: funBody
            width: funColumn.width
            implicitHeight: root.funRevealed ? funInner.implicitHeight : 0

            Column {
              id: funInner
              width: funBody.width
              spacing: Style.spacing.controlGap
              visible: root.funRevealed

              Button {
                id: funToggle
                width: funInner.width
                iconText: "\uf0d0"
                text: root.funGlitchOn ? "Glitch: on" : "Glitch: off"
                leftAlign: true
                active: root.funGlitchOn
                foreground: root.funColor
                accent: root.funColor
                onClicked: root.toggleFun()
              }

              Button {
                id: funAnnounceToggle
                width: funInner.width
                iconText: "\uf0f3"
                text: root.funAnnounce ? "Announce: on" : "Announce: off"
                leftAlign: true
                active: root.funAnnounce
                foreground: root.funColor
                accent: root.funColor
                onClicked: {
                  root.funAnnounce = !root.funAnnounce
                  root.updateFun()
                }
              }

              Row {
                width: funInner.width
                spacing: Style.spacing.controlGap

                Text {
                  width: parent.width - funModeRow.width - parent.spacing
                  text: "Mode"
                  textFormat: Text.PlainText
                  color: root.funColor
                  opacity: 0.7
                  font.family: Style.font.family
                  font.pixelSize: Style.font.bodySmall
                  anchors.verticalCenter: parent.verticalCenter
                }

                Row {
                  id: funModeRow
                  spacing: Style.spacing.controlGap
                  Button {
                    width: (funInner.width * 0.6 - 2 * Style.spacing.controlGap) / 3
                    text: "AirPlay"
                    accent: root.funColor
                    selected: root.funMode === "airplay"
                    onClicked: {
                      root.funMode = "airplay"
                      root.updateFun()
                    }
                  }
                  Button {
                    width: (funInner.width * 0.6 - 2 * Style.spacing.controlGap) / 3
                    text: "Local"
                    accent: root.funColor
                    selected: root.funMode === "local"
                    onClicked: {
                      root.funMode = "local"
                      root.updateFun()
                    }
                  }
                  Button {
                    width: (funInner.width * 0.6 - 2 * Style.spacing.controlGap) / 3
                    text: "Both"
                    accent: root.funColor
                    selected: root.funMode === "both"
                    onClicked: {
                      root.funMode = "both"
                      root.updateFun()
                    }
                  }
                }
              }

              Row {
                width: funInner.width
                spacing: Style.spacing.controlGap

                Text {
                  width: parent.width - funDriverRow.width - parent.spacing
                  text: "Driver"
                  textFormat: Text.PlainText
                  color: root.funColor
                  opacity: 0.7
                  font.family: Style.font.family
                  font.pixelSize: Style.font.bodySmall
                  anchors.verticalCenter: parent.verticalCenter
                }

                Row {
                  id: funDriverRow
                  spacing: Style.spacing.controlGap
                  Button {
                    width: (funInner.width * 0.6 - Style.spacing.controlGap) / 2
                    text: "Timer"
                    accent: root.funColor
                    selected: root.funDriver === "timer"
                    onClicked: {
                      root.funDriver = "timer"
                      root.updateFun()
                    }
                  }
                  Button {
                    width: (funInner.width * 0.6 - Style.spacing.controlGap) / 2
                    text: "Screensaver"
                    accent: root.funColor
                    selected: root.funDriver === "screensaver"
                    onClicked: {
                      root.funDriver = "screensaver"
                      root.updateFun()
                    }
                  }
                }
              }

              Text {
                width: funInner.width
                text: "Intensity  ·  " + root.funIntensity + "%"
                textFormat: Text.PlainText
                color: root.funColor
                opacity: 0.7
                font.family: Style.font.family
                font.pixelSize: Style.font.bodySmall
                elide: Text.ElideRight
              }

              PanelSlider {
                id: funIntensitySlider
                width: funInner.width
                bar: root.bar
                value: root.funIntensity
                minimum: 0
                maximum: 100
                step: 5
                integer: true
                fillColor: root.funColor
                knobColor: root.funColor
                onMoved: function(value) { root.funIntensity = value }
                onReleased: root.updateFun()
              }

              Text {
                width: funInner.width
                text: "Rhythm  ·  " + (root.funBpm === 0 ? "steady" : root.funBpm + " bpm")
                textFormat: Text.PlainText
                color: root.funColor
                opacity: 0.7
                font.family: Style.font.family
                font.pixelSize: Style.font.bodySmall
                elide: Text.ElideRight
              }

              PanelSlider {
                id: funBpmSlider
                width: funInner.width
                bar: root.bar
                value: root.funBpm
                minimum: 0
                maximum: 180
                step: 6
                integer: true
                fillColor: root.funColor
                knobColor: root.funColor
                onMoved: function(value) { root.funBpm = value }
                onReleased: root.updateFun()
              }

              Text {
                width: funInner.width
                text: "Glitch rides the screensaver and dies with it. Mode picks which output it plays on; Rhythm is the burst tempo (steady at 0 bpm)."
                textFormat: Text.PlainText
                color: root.funColor
                opacity: 0.5
                font.family: Style.font.family
                font.pixelSize: Style.font.bodySmall
                wrapMode: Text.WordWrap
              }
            }
          }
        }

        PanelSeparator {
          visible: root.funRevealed
            && (root.audioOutputs.length > 0 || root.stationsLoaded)
          foreground: root.funColor
          strength: 0.55
        }

        Column {
          id: outputColumn
          width: popupColumn.width
          spacing: Style.spacing.controlGap
          visible: root.audioOutputs.length > 0

          Text {
            width: outputColumn.width
            text: "Output"
            textFormat: Text.PlainText
            color: Color.foreground
            opacity: 0.65
            font.family: Style.font.family
            font.pixelSize: Style.font.bodySmall
            elide: Text.ElideRight
          }

          Repeater {
            model: root.audioOutputs
            delegate: Button {
              width: outputColumn.width
              text: root.outputLabel(modelData.label)
              leftAlign: true
              selected: modelData.id === root.audioOutput
              tooltipText: root.safeTooltipText(modelData.label)
              onClicked: root.selectOutput(modelData.id)
            }
          }
        }
        
        Column {
          id: stationsColumn
          width: popupColumn.width
          spacing: Style.spacing.controlGap
          visible: root.stationsLoaded

          Text {
            width: stationsColumn.width
            text: "Stations"
            textFormat: Text.PlainText
            color: Color.foreground
            opacity: 0.65
            font.family: Style.font.family
            font.pixelSize: Style.font.bodySmall
            elide: Text.ElideRight
          }

          TextField {
            width: stationsColumn.width
            placeholderText: "Search stations..."
            text: root.searchText
            onTextChanged: root.searchText = text
          }

          Column {
            width: stationsColumn.width
            spacing: Style.spacing.controlGap
            visible: root.favStations.length > 0

            Text {
              width: parent.width
              text: "Favorites"
              textFormat: Text.PlainText
              color: Color.foreground
              opacity: 0.5
              font.family: Style.font.family
              font.pixelSize: Style.font.bodySmall
              elide: Text.ElideRight
            }

            ScrollView {
              width: stationsColumn.width
              implicitHeight: Math.min(root.favStations.length * 40, 200)
              clip: true
              Flickable {
                anchors.fill: parent
                contentWidth: width
                contentHeight: favCol.height
                interactive: true
                flickableDirection: Flickable.VerticalFlick
                Column {
                  id: favCol
                  width: parent.width
                  spacing: Style.spacing.controlGap
                  Repeater {
                    model: root.favStations
                    delegate: Row {
                      width: parent.width
                      spacing: Style.spacing.controlGap
                      Button {
                        width: parent.width - favBtn.width - parent.spacing
                        text: root.singleLineText(modelData.name, 60)
                        leftAlign: true
                        onClicked: root.switchStation(modelData)
                      }
                      PanelActionButton {
                        id: favBtn
                        iconText: "\uf005"
                        tooltipText: "Remove from favorites"
                        onClicked: root.toggleFavorite(modelData)
                      }
                    }
                  }
                }
              }
            }
          }

          Column {
            width: stationsColumn.width
            spacing: Style.spacing.controlGap
            visible: root.filteredStations().length > 0

            Text {
              width: parent.width
              text: root.searchText === "" ? "All stations" : "Search results"
              textFormat: Text.PlainText
              color: Color.foreground
              opacity: 0.5
              font.family: Style.font.family
              font.pixelSize: Style.font.bodySmall
              elide: Text.ElideRight
            }

            ScrollView {
              width: stationsColumn.width
              implicitHeight: Math.min(root.filteredStations().length * 40, 240)
              clip: true
              Flickable {
                anchors.fill: parent
                contentWidth: width
                contentHeight: allCol.height
                interactive: true
                flickableDirection: Flickable.VerticalFlick
                Column {
                  id: allCol
                  width: parent.width
                  spacing: Style.spacing.controlGap
                  Repeater {
                    model: root.filteredStations()
                    delegate: Row {
                      width: parent.width
                      spacing: Style.spacing.controlGap
                      Button {
                        width: parent.width - favBtn2.width - parent.spacing
                        text: root.singleLineText(modelData.name, 60)
                        leftAlign: true
                        tooltipText: root.safeTooltipText(modelData.description)
                        onClicked: root.switchStation(modelData)
                      }
                      PanelActionButton {
                        id: favBtn2
                        iconText: root.isFavorite(modelData.url) ? "\uf005" : "\uf006"
                        tooltipText: root.isFavorite(modelData.url) ? "Remove from favorites" : "Add to favorites"
                        onClicked: root.toggleFavorite(modelData)
                      }
                    }
                  }
                }
              }
            }
          }
        }
      }
    }
  }
}
