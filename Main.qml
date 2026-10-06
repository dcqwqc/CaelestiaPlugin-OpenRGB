import QtQuick
import Quickshell.Io
import qs.services

Item {
    id: root
    visible: false
    readonly property string helper: Qt.resolvedUrl("scripts/openrgb-control").toString().replace("file://", "")
    readonly property color accent: Colours.palette.m3primary

    function apply(): void {
        if (!applyProc.running) {
            applyProc.command = [root.helper, "apply"];
            applyProc.running = true;
        } else {
            applyDebounce.restart();
        }
    }

    Component.onCompleted: applyDebounce.restart()

    onAccentChanged: applyDebounce.restart()

    Timer {
        id: applyDebounce
        interval: 180
        repeat: false
        onTriggered: root.apply()
    }

    Process { id: applyProc }
}
