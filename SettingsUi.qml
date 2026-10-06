pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Layouts
import QtQuick.Controls
import Quickshell.Io
import Caelestia.Config
import qs.components
import qs.components.controls
import qs.modules.nexus.common
import qs.services

ColumnLayout {
    id: root

    property var settings: null
    property string reason: "unknown"
    property var devices: []
    property var profiles: []
    property string mode: "accent"
    property string customColour: "cba6f7"
    property int brightness: 100
    property string profile: ""
    property var pending: null
    readonly property string helper: Qt.resolvedUrl("scripts/openrgb-control").toString().replace("file://", "")
    readonly property bool available: reason === "ok"
    readonly property int enabledDeviceCount: devices.filter(d => d.enabled).length
    readonly property int brightnessDeviceCount: devices.filter(d => d.enabled && d.supportsBrightness).length
    readonly property bool anyBrightness: brightnessDeviceCount > 0

    Layout.fillWidth: true
    spacing: Tokens.spacing.extraSmall

    readonly property string unavailableText: {
        switch (reason) {
        case "not_installed": return qsTr("OpenRGB is not installed");
        case "sdk_missing": return qsTr("OpenRGB Python SDK is not installed");
        case "server_unavailable": return qsTr("OpenRGB SDK server is not responding");
        case "no_devices": return qsTr("No compatible RGB controllers found");
        case "error": return qsTr("OpenRGB returned an error");
        default: return qsTr("Checking OpenRGB…");
        }
    }

    function ingest(raw): void {
        try {
            const data = JSON.parse(raw);
            root.reason = data.reason ?? "error";
            root.devices = data.devices ?? [];
            root.profiles = data.profiles ?? [];
            const state = data.state ?? {};
            root.mode = state.mode ?? "accent";
            root.customColour = state.customColor ?? "cba6f7";
            root.brightness = state.brightness ?? 100;
            root.profile = state.profile ?? "";
        } catch (e) {
            root.reason = "error";
        }
    }

    function run(args): void {
        if (proc.running) {
            root.pending = args;
            return;
        }
        proc.command = [root.helper].concat(args);
        proc.running = true;
    }

    function refresh(): void { root.run(["status"]); }

    Process {
        id: proc
        stdout: StdioCollector { onStreamFinished: root.ingest(text) }
        onExited: {
            if (root.pending) {
                const next = root.pending;
                root.pending = null;
                root.run(next);
            }
        }
    }

    Timer {
        interval: 5000
        repeat: true
        running: root.visible
        onTriggered: root.refresh()
    }

    Timer {
        id: colourDebounce
        interval: 160
        onTriggered: root.run(["set-color", root.customColour])
    }

    Timer {
        id: brightnessDebounce
        interval: 160
        onTriggered: root.run(["set-brightness", String(root.brightness)])
    }

    Component.onCompleted: root.refresh()

    SectionHeader { first: true; text: qsTr("OpenRGB lighting") }

    StyledText {
        Layout.fillWidth: true
        text: qsTr("Hardware lighting is optional and independent from the Color plugin. Accent mode follows Caelestia's rendered primary colour.")
        color: Colours.palette.m3outline
        font: Tokens.font.body.medium
        wrapMode: Text.Wrap
    }

    SectionContainer {
        visible: !root.available
        ColumnLayout {
            Layout.fillWidth: true
            spacing: Tokens.spacing.small
            MaterialIcon {
                Layout.alignment: Qt.AlignHCenter
                text: "lightbulb"
                color: Colours.palette.m3onSurfaceVariant
                fontStyle: Tokens.font.icon.extraLarge
            }
            StyledText {
                Layout.alignment: Qt.AlignHCenter
                text: root.unavailableText
                color: Colours.palette.m3onSurfaceVariant
                font: Tokens.font.body.large
            }
            IconTextButton {
                Layout.alignment: Qt.AlignHCenter
                icon: "refresh"
                text: qsTr("Check again")
                type: IconTextButton.Tonal
                onClicked: root.refresh()
            }
        }
    }

    SectionContainer {
        visible: root.available
        ColumnLayout {
            Layout.fillWidth: true
            spacing: Tokens.spacing.medium

            StyledText { text: qsTr("Source"); font: Tokens.font.body.small; color: Colours.palette.m3outline }

            StyledRadioButton {
                text: qsTr("System accent")
                checked: root.mode === "accent"
                onClicked: { root.mode = "accent"; root.run(["set-mode", "accent"]); }
            }
            StyledRadioButton {
                text: qsTr("Custom colour")
                checked: root.mode === "custom"
                onClicked: { root.mode = "custom"; root.run(["set-mode", "custom"]); }
            }
            StyledRadioButton {
                text: qsTr("OpenRGB profile")
                checked: root.mode === "profile"
                enabled: root.profiles.length > 0
                onClicked: { root.mode = "profile"; root.run(["set-mode", "profile"]); }
            }
            StyledRadioButton {
                text: qsTr("Off")
                checked: root.mode === "off"
                onClicked: { root.mode = "off"; root.run(["set-mode", "off"]); }
            }
        }
    }

    StyledRect {
        visible: root.available && root.mode === "custom"
        Layout.fillWidth: true
        implicitHeight: customRow.implicitHeight + Tokens.padding.medium * 2
        radius: Tokens.rounding.large
        color: Colours.tPalette.m3surfaceContainer
        RowLayout {
            id: customRow
            anchors.fill: parent
            anchors.margins: Tokens.padding.medium
            spacing: Tokens.spacing.medium
            StyledRect {
                implicitWidth: 34; implicitHeight: 34
                radius: Tokens.rounding.medium
                color: "#" + root.customColour
                border.width: 1; border.color: Colours.palette.m3outlineVariant
            }
            StyledInputField {
                Layout.fillWidth: true
                text: "#" + root.customColour.toUpperCase()
                validator: RegularExpressionValidator { regularExpression: /^#?[0-9a-fA-F]{0,6}$/ }
                onTextEdited: t => {
                    const clean = String(t).replace("#", "");
                    if (/^[0-9a-fA-F]{6}$/.test(clean)) {
                        root.customColour = clean.toLowerCase();
                        colourDebounce.restart();
                    }
                }
            }
        }
    }

    SliderRow {
        Layout.fillWidth: true
        visible: root.available && root.anyBrightness && (root.mode === "accent" || root.mode === "custom")
        label: qsTr("Brightness")
        from: 0
        to: 100
        value: root.brightness
        valueLabel: Math.round(value) + "%"
        onMoved: v => { root.brightness = Math.round(v); brightnessDebounce.restart(); }
    }

    StyledText {
        Layout.fillWidth: true
        visible: root.available && root.anyBrightness && root.brightnessDeviceCount < root.enabledDeviceCount
        text: qsTr("Brightness is supported by %1 of %2 enabled controllers.").arg(root.brightnessDeviceCount).arg(root.enabledDeviceCount)
        color: Colours.palette.m3outline
        font: Tokens.font.label.small
        wrapMode: Text.Wrap
    }

    SectionHeader { visible: root.available && root.mode === "profile"; text: qsTr("Profiles") }

    Repeater {
        model: root.available && root.mode === "profile" ? root.profiles : []
        delegate: ToggleRow {
            required property string modelData
            Layout.fillWidth: true
            text: modelData
            checked: root.profile === modelData
            onToggled: checked => {
                if (checked) { root.profile = modelData; root.run(["set-profile", modelData]); }
            }
        }
    }

    SectionHeader { visible: root.available; text: qsTr("Devices") }

    Repeater {
        model: root.available ? root.devices : []
        delegate: ToggleRow {
            required property int index
            required property var modelData
            Layout.fillWidth: true
            first: index === 0
            last: index === root.devices.length - 1
            text: modelData.name
            subtext: modelData.supportsColour ? modelData.type : qsTr("%1 · no controllable colour").arg(modelData.type)
            enabled: modelData.supportsColour
            checked: modelData.enabled
            onToggled: checked => root.run(["set-device", modelData.key, checked ? "on" : "off"])
        }
    }
}
