import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import QtQuick.Shapes
import QtQuick.Dialogs

ApplicationWindow {
    id: win
    width: 820
    height: 600
    minimumWidth: 560
    minimumHeight: 440
    visible: true
    title: "Conversor"
    color: t.bg
    palette.accent: t.accent
    palette.highlight: t.accent
    palette.highlightedText: t.accentText

    // ---- theme ------------------------------------------------------------------------
    QtObject {
        id: t
        readonly property bool dark: Application.styleHints.colorScheme === Qt.Dark
        readonly property color bg: dark ? "#1c1c1c" : "#f3f3f3"
        readonly property color surface: dark ? "#272727" : "#ffffff"
        readonly property color surfaceAlt: dark ? "#2f2f2f" : "#f7f7f7"
        readonly property color border: dark ? "#383838" : "#e3e3e3"
        readonly property color hover: dark ? "#333333" : "#f0f0f0"
        readonly property color text: dark ? "#f5f5f5" : "#1a1a1a"
        readonly property color subtext: dark ? "#a8a8a8" : "#6b6b6b"
        readonly property color accent: dark ? "#6b7ff5" : "#4459e0"
        readonly property color accentText: "#ffffff"
        readonly property color danger: dark ? "#ff8f8f" : "#c42b1c"
        readonly property color success: dark ? "#7fd47f" : "#107c10"
        readonly property string icons: Qt.fontFamilies().indexOf("Segoe Fluent Icons") >= 0
                                        ? "Segoe Fluent Icons" : "Segoe MDL2 Assets"
    }

    property var expanded: ({})  // options drawer open/closed per file kind
    readonly property var kindIcons: ({
        image: "\uE91B", pdf: "\uEA90", document: "\uE8A5", spreadsheet: "\uE9F9",
        presentation: "\uE8A1", video: "\uE714", audio: "\uE8D6", data: "\uE943", unknown: "\uE9CE"
    })
    property var compareItem: null

    // ---- reusable bits ----------------------------------------------------------------
    component Icon: Text {
        property string glyph
        text: glyph
        font.family: t.icons
        font.pixelSize: 16
        color: t.text
        verticalAlignment: Text.AlignVCenter
        horizontalAlignment: Text.AlignHCenter
    }

    component IconButton: ToolButton {
        property string glyph
        property string tip
        implicitWidth: 34
        implicitHeight: 34
        contentItem: Icon { glyph: parent.glyph; font.pixelSize: 15; color: parent.enabled ? t.text : t.subtext }
        ToolTip.visible: hovered && tip !== ""
        ToolTip.text: tip
        ToolTip.delay: 500
    }

    component Chip: Rectangle {
        id: chip
        property string label
        property bool selected
        property bool small: false
        signal clicked
        implicitWidth: chipText.implicitWidth + (small ? 20 : 28)
        implicitHeight: small ? 28 : 34
        radius: height / 2
        color: selected ? t.accent : (chipMouse.containsMouse ? t.hover : "transparent")
        border.color: selected ? t.accent : t.border
        border.width: 1
        Behavior on color { ColorAnimation { duration: 120 } }
        Text {
            id: chipText
            anchors.centerIn: parent
            text: chip.label
            color: chip.selected ? t.accentText : t.text
            font.pixelSize: chip.small ? 12 : 13
            font.weight: chip.selected ? Font.DemiBold : Font.Normal
        }
        MouseArea {
            id: chipMouse
            anchors.fill: parent
            hoverEnabled: true
            cursorShape: Qt.PointingHandCursor
            onClicked: chip.clicked()
        }
    }

    component SectionLabel: Text {
        color: t.subtext
        font.pixelSize: 12
        font.weight: Font.DemiBold
    }

    // ---- option editors (generated from the registry) ------------------------------------
    component OptionEditor: ColumnLayout {
        id: editor
        property var opt
        property string opId
        spacing: 6

        RowLayout {
            visible: editor.opt.type !== "toggle"
            Text { text: editor.opt.label; color: t.text; font.pixelSize: 13 }
            Item { Layout.fillWidth: true }
            Text {
                visible: editor.opt.type === "slider"
                text: Math.round(slider.value) + editor.opt.suffix
                color: t.subtext
                font.pixelSize: 13
            }
        }
        Slider {
            id: slider
            visible: editor.opt.type === "slider"
            Layout.fillWidth: true
            from: editor.opt.min; to: editor.opt.max; stepSize: editor.opt.step
            value: editor.opt.type === "slider" ? editor.opt.value : 0
            onPressedChanged: if (!pressed) backend.setOption(editor.opId, editor.opt.key, Math.round(value))
        }
        Flow {
            visible: editor.opt.type === "choice"
            Layout.fillWidth: true
            spacing: 6
            Repeater {
                model: editor.opt.type === "choice" ? editor.opt.choices : []
                Chip {
                    small: true
                    label: modelData
                    selected: editor.opt.value === modelData
                    onClicked: backend.setOption(editor.opId, editor.opt.key, modelData)
                }
            }
        }
        Flow {
            visible: editor.opt.type === "multi"
            Layout.fillWidth: true
            spacing: 6
            Repeater {
                model: editor.opt.type === "multi" ? editor.opt.choices : []
                Chip {
                    small: true
                    label: modelData + editor.opt.suffix
                    selected: editor.opt.value.indexOf(modelData) >= 0
                    onClicked: {
                        let v = editor.opt.value.slice()
                        const i = v.indexOf(modelData)
                        if (i >= 0) { if (v.length > 1) v.splice(i, 1) } else v.push(modelData)
                        v.sort((a, b) => a - b)
                        backend.setOption(editor.opId, editor.opt.key, v)
                    }
                }
            }
        }
        SpinBox {
            visible: editor.opt.type === "number"
            editable: true
            from: editor.opt.min; to: editor.opt.max
            stepSize: 10
            value: editor.opt.type === "number" ? editor.opt.value : 0
            onValueModified: backend.setOption(editor.opId, editor.opt.key, value)
        }
        TextField {
            visible: editor.opt.type === "text"
            Layout.preferredWidth: 220
            text: editor.opt.type === "text" ? editor.opt.value : ""
            onEditingFinished: backend.setOption(editor.opId, editor.opt.key, text)
        }
        TextField {
            visible: editor.opt.type === "password"
            Layout.fillWidth: true
            echoMode: TextInput.Password
            placeholderText: "Not saved anywhere; forgotten when you close the app"
            text: editor.opt.type === "password" ? editor.opt.value : ""
            onEditingFinished: backend.setOption(editor.opId, editor.opt.key, text)
        }
        Switch {
            visible: editor.opt.type === "toggle"
            text: editor.opt.label
            checked: editor.opt.type === "toggle" ? editor.opt.value : false
            onToggled: backend.setOption(editor.opId, editor.opt.key, checked)
        }
    }

    // ---- one row per file ------------------------------------------------------------
    component FileRow: Rectangle {
        id: row
        required property var model
        Layout.fillWidth: true
        implicitHeight: 58
        radius: 6
        color: rowMouse.containsMouse ? t.surfaceAlt : "transparent"

        MouseArea { id: rowMouse; anchors.fill: parent; hoverEnabled: true; acceptedButtons: Qt.NoButton }

        RowLayout {
            anchors.fill: parent
            anchors.leftMargin: 8
            anchors.rightMargin: 6
            spacing: 12

            Rectangle {
                implicitWidth: 40; implicitHeight: 40
                radius: 6
                color: t.surfaceAlt
                border.color: t.border
                clip: true
                Image {
                    anchors.fill: parent
                    anchors.margins: 1
                    source: row.model.thumb
                    fillMode: Image.PreserveAspectCrop
                    asynchronous: true
                    visible: row.model.thumb !== ""
                }
                Icon {
                    anchors.centerIn: parent
                    visible: row.model.thumb === ""
                    glyph: win.kindIcons[row.model.kind] || win.kindIcons.unknown
                    color: t.subtext
                }
            }

            ColumnLayout {
                Layout.fillWidth: true
                spacing: 3
                Text {
                    Layout.fillWidth: true
                    text: row.model.name
                    color: t.text
                    font.pixelSize: 13
                    elide: Text.ElideMiddle
                }
                Text {
                    Layout.fillWidth: true
                    elide: Text.ElideRight
                    font.pixelSize: 12
                    color: row.model.status === "error" ? t.danger
                         : row.model.status === "done" ? t.success : t.subtext
                    text: {
                        switch (row.model.status) {
                        case "queued": return "Waiting…"
                        case "running": return "Working… " + Math.round(row.model.progress * 100) + "%"
                        case "ready": return row.model.message !== "" ? row.model.message
                                           : row.model.fmt.toUpperCase() + " · Ready"
                        default: return row.model.message
                        }
                    }
                }
                ProgressBar {
                    Layout.fillWidth: true
                    visible: row.model.status === "running" || row.model.status === "queued"
                    indeterminate: row.model.status === "queued"
                    value: row.model.progress
                    implicitHeight: 3
                }
            }

            IconButton {
                visible: row.model.status === "done" && row.model.after !== ""
                glyph: ""; tip: "Compare before / after"
                onClicked: { win.compareItem = { before: row.model.before, after: row.model.after,
                                                 output: row.model.output }; comparePopup.open() }
            }
            IconButton {
                visible: row.model.status === "done"
                glyph: ""; tip: "Open"
                onClicked: backend.openFile(row.model.output)
            }
            IconButton {
                visible: row.model.status === "done"
                glyph: ""; tip: "Show in folder"
                onClicked: backend.showInFolder(row.model.output)
            }
            IconButton {
                visible: row.model.status !== "running" && row.model.status !== "queued"
                glyph: ""; tip: "Remove from list"
                onClicked: backend.removeFile(row.model.uid)
            }
        }
    }

    // ---- one card per kind of file ---------------------------------------------------
    component GroupCard: Rectangle {
        id: card
        property var group
        readonly property int shownTargets: 4
        readonly property bool optionsOpen: !!win.expanded[group.kind]
        Layout.fillWidth: true
        implicitHeight: cardCol.implicitHeight + 32
        radius: 10
        color: t.surface
        border.color: t.border

        ColumnLayout {
            id: cardCol
            anchors.fill: parent
            anchors.margins: 16
            spacing: 10

            RowLayout {
                spacing: 10
                Icon { glyph: win.kindIcons[card.group.kind] || win.kindIcons.unknown; color: t.accent; font.pixelSize: 18 }
                Text { text: card.group.label; color: t.text; font.pixelSize: 15; font.weight: Font.DemiBold }
                Item { Layout.fillWidth: true }
            }

            Text {
                visible: !card.group.supported
                text: "These files can't be converted."
                color: t.subtext
                font.pixelSize: 13
                wrapMode: Text.Wrap
                Layout.fillWidth: true
            }

            SectionLabel { visible: card.group.supported; text: "CONVERT TO" }
            Flow {
                visible: card.group.supported
                Layout.fillWidth: true
                spacing: 8
                Repeater {
                    model: card.group.targets.slice(0, card.shownTargets)
                    Chip {
                        label: modelData.label
                        enabled: !backend.busy
                        selected: card.group.op === card.group.convertOp && card.group.target === modelData.id
                        onClicked: backend.choose(card.group.kind, card.group.convertOp, modelData.id)
                    }
                }
                Chip {
                    id: moreChip
                    readonly property var rest: card.group.targets.slice(card.shownTargets)
                    readonly property var picked: rest.find(x => card.group.op === card.group.convertOp
                                                                 && x.id === card.group.target)
                    visible: rest.length > 0
                    label: picked ? picked.label + "  ▾" : "More  ▾"
                    selected: !!picked
                    onClicked: moreMenu.popup(moreChip, 0, moreChip.height + 4)
                    Menu {
                        id: moreMenu
                        Repeater {
                            model: moreChip.rest
                            MenuItem {
                                text: modelData.label
                                onTriggered: backend.choose(card.group.kind, card.group.convertOp, modelData.id)
                            }
                        }
                    }
                }
            }

            SectionLabel { visible: card.group.tools.length > 0; text: "TOOLS"; Layout.topMargin: 4 }
            Flow {
                visible: card.group.tools.length > 0
                Layout.fillWidth: true
                spacing: 8
                Repeater {
                    model: card.group.tools
                    Chip {
                        label: modelData.label
                        selected: card.group.op === modelData.id
                        onClicked: backend.choose(card.group.kind, modelData.id, "")
                    }
                }
            }

            RowLayout {
                visible: card.group.supported && (card.group.options.length > 0 || card.group.hint !== "")
                Layout.fillWidth: true
                Text {
                    text: card.group.hint
                    color: t.subtext
                    font.pixelSize: 12
                    Layout.fillWidth: true
                    elide: Text.ElideRight
                }
                Button {
                    visible: card.group.options.length > 0
                    flat: true
                    text: (card.optionsOpen ? "Hide options" : "Options") + "  " + (card.optionsOpen ? "▴" : "▾")
                    onClicked: {
                        let e = Object.assign({}, win.expanded)
                        e[card.group.kind] = !card.optionsOpen
                        win.expanded = e
                    }
                }
            }

            Rectangle {
                visible: card.optionsOpen && card.group.options.length > 0
                Layout.fillWidth: true
                implicitHeight: optCol.implicitHeight + 24
                radius: 8
                color: t.surfaceAlt
                ColumnLayout {
                    id: optCol
                    anchors.fill: parent
                    anchors.margins: 12
                    spacing: 12
                    Repeater {
                        model: card.group.options
                        OptionEditor { Layout.fillWidth: true; opt: modelData; opId: card.group.op }
                    }
                }
            }

            Rectangle { Layout.fillWidth: true; implicitHeight: 1; color: t.border; Layout.topMargin: 4 }

            ColumnLayout {
                Layout.fillWidth: true
                spacing: 0
                Repeater {
                    model: backend.files
                    FileRow { visible: model.kind === card.group.kind }
                }
            }
        }
    }

    // ---- layout ----------------------------------------------------------------------
    ColumnLayout {
        anchors.fill: parent
        spacing: 0

        // header
        RowLayout {
            Layout.fillWidth: true
            Layout.preferredHeight: 52
            Layout.leftMargin: 20
            Layout.rightMargin: 10
            Image { source: "icon.png"; sourceSize: Qt.size(44, 44); Layout.preferredWidth: 22; Layout.preferredHeight: 22 }
            Text { text: "Conversor"; color: t.text; font.pixelSize: 14; font.weight: Font.DemiBold; Layout.leftMargin: 4 }
            Item { Layout.fillWidth: true }
            IconButton {
                visible: backend.fileCount > 0 && !backend.busy
                glyph: ""; tip: "Clear list"
                onClicked: backend.clear()
            }
            IconButton { glyph: ""; tip: "Settings"; onClicked: settingsDrawer.open() }
        }

        // empty state: just a drop zone
        Item {
            visible: backend.fileCount === 0
            Layout.fillWidth: true
            Layout.fillHeight: true

            Item {
                id: zone
                anchors.centerIn: parent
                anchors.verticalCenterOffset: -20
                width: Math.min(parent.width - 64, 560)
                height: Math.min(parent.height - 64, 320)

                Rectangle {
                    anchors.fill: parent
                    radius: 16
                    color: zoneMouse.containsMouse || dropArea.containsDrag ? t.surface : "transparent"
                    Behavior on color { ColorAnimation { duration: 150 } }
                }
                Shape {
                    anchors.fill: parent
                    ShapePath {
                        strokeColor: dropArea.containsDrag ? t.accent : t.border
                        strokeWidth: 2
                        strokeStyle: ShapePath.DashLine
                        dashPattern: [5, 4]
                        fillColor: "transparent"
                        PathRectangle { x: 1; y: 1; width: zone.width - 2; height: zone.height - 2; radius: 16 }
                    }
                }
                ColumnLayout {
                    anchors.centerIn: parent
                    spacing: 10
                    Rectangle {
                        Layout.alignment: Qt.AlignHCenter
                        implicitWidth: 64; implicitHeight: 64; radius: 32
                        color: Qt.alpha(t.accent, 0.12)
                        Icon { anchors.centerIn: parent; glyph: ""; color: t.accent; font.pixelSize: 26 }
                    }
                    Text {
                        Layout.alignment: Qt.AlignHCenter
                        text: "Drop files here"
                        color: t.text
                        font.pixelSize: 20
                        font.weight: Font.DemiBold
                    }
                    Text {
                        Layout.alignment: Qt.AlignHCenter
                        text: "or click to browse"
                        color: t.subtext
                        font.pixelSize: 13
                    }
                    Text {
                        Layout.alignment: Qt.AlignHCenter
                        Layout.topMargin: 14
                        text: "Images · PDF · Office · Video · Audio · CSV · JSON"
                        color: t.subtext
                        font.pixelSize: 11
                        font.letterSpacing: 0.5
                    }
                }
                MouseArea {
                    id: zoneMouse
                    anchors.fill: parent
                    hoverEnabled: true
                    cursorShape: Qt.PointingHandCursor
                    onClicked: openDialog.open()
                }
            }

            Text {
                anchors.bottom: parent.bottom
                anchors.bottomMargin: 18
                anchors.horizontalCenter: parent.horizontalCenter
                text: "🔒  Everything happens on this PC. Nothing is uploaded."
                color: t.subtext
                font.pixelSize: 12
            }
        }

        // working state: groups + file rows
        ScrollView {
            id: scroller
            visible: backend.fileCount > 0
            Layout.fillWidth: true
            Layout.fillHeight: true
            contentWidth: availableWidth
            ColumnLayout {
                width: scroller.availableWidth
                spacing: 14
                Item { implicitHeight: 2 }
                Repeater {
                    model: backend.groups
                    GroupCard {
                        group: modelData
                        Layout.leftMargin: 20
                        Layout.rightMargin: 20
                    }
                }
                Item { implicitHeight: 8 }
            }
        }

        // footer
        Rectangle {
            visible: backend.fileCount > 0 || backend.download.model !== ""
            Layout.fillWidth: true
            implicitHeight: 64
            color: t.surface
            Rectangle { anchors.top: parent.top; width: parent.width; height: 1; color: t.border }

            RowLayout {
                anchors.fill: parent
                anchors.leftMargin: 20
                anchors.rightMargin: 16
                spacing: 10

                ColumnLayout {
                    visible: backend.download.model !== ""
                    Layout.fillWidth: true
                    spacing: 4
                    Text {
                        text: "Downloading AI model… " + Math.round(backend.download.progress * 100) + "%"
                        color: t.text; font.pixelSize: 12
                    }
                    ProgressBar { Layout.fillWidth: true; value: backend.download.progress }
                }
                Button {
                    visible: backend.download.model !== ""
                    text: "Cancel"
                    onClicked: backend.cancelDownload()
                }

                Text {
                    visible: backend.download.model === ""
                    text: backend.outputLabel + "  ·  change"
                    color: t.subtext
                    font.pixelSize: 12
                    Layout.fillWidth: true
                    elide: Text.ElideRight
                    MouseArea { anchors.fill: parent; cursorShape: Qt.PointingHandCursor; onClicked: settingsDrawer.open() }
                }
                Button {
                    visible: backend.download.model === "" && backend.fileCount > 0
                    enabled: !backend.busy
                    text: "Add files"
                    onClicked: openDialog.open()
                }
                Button {
                    visible: backend.download.model === "" && backend.fileCount > 0
                    highlighted: true
                    enabled: backend.busy || backend.pendingCount > 0
                    text: backend.busy ? "Cancel"
                        : backend.pendingCount > 0 ? "Convert " + backend.pendingCount + (backend.pendingCount === 1 ? " file" : " files")
                        : "All done"
                    onClicked: backend.busy ? backend.cancel() : backend.start()
                }
            }
        }
    }

    // ---- drag & drop anywhere ----------------------------------------------------------
    DropArea {
        id: dropArea
        anchors.fill: parent
        onEntered: (drag) => { if (drag.hasUrls) drag.accept(Qt.CopyAction) }
        onDropped: (drop) => { if (drop.hasUrls) { backend.addUrls(drop.urls); drop.accept(Qt.CopyAction) } }
    }
    Rectangle {
        anchors.fill: parent
        visible: dropArea.containsDrag && backend.fileCount > 0
        color: Qt.alpha(t.bg, 0.85)
        border.color: t.accent
        border.width: 2
        Text { anchors.centerIn: parent; text: "Drop to add"; color: t.accent; font.pixelSize: 20; font.weight: Font.DemiBold }
    }

    FileDialog {
        id: openDialog
        title: "Choose files"
        fileMode: FileDialog.OpenFiles
        onAccepted: backend.addUrls(selectedFiles)
    }
    FolderDialog {
        id: folderDialog
        title: "Save converted files to"
        onAccepted: backend.setOutputFolder(selectedFolder)
    }

    // ---- AI model download prompt --------------------------------------------------------
    Dialog {
        id: modelDialog
        property string modelId
        property string modelLabel
        property int sizeMb
        anchors.centerIn: parent
        width: Math.min(440, win.width - 40)
        modal: true
        title: "Download the AI model?"
        standardButtons: Dialog.Ok | Dialog.Cancel
        Component.onCompleted: standardButton(Dialog.Ok).text = "Download (" + sizeMb + " MB)"
        onSizeMbChanged: if (standardButton(Dialog.Ok)) standardButton(Dialog.Ok).text = "Download (" + sizeMb + " MB)"
        contentItem: Text {
            text: modelDialog.modelLabel + "\n\nThis is a one-time download. The model is checked against a "
                  + "known fingerprint (SHA-256) and stored on this PC, so after this everything runs offline."
            wrapMode: Text.Wrap
            color: t.text
            font.pixelSize: 13
        }
        onAccepted: backend.downloadModel(modelId)
        onRejected: backend.declineDownload()
    }

    // ---- before / after comparison ---------------------------------------------------------
    Popup {
        id: comparePopup
        objectName: "comparePopup"
        anchors.centerIn: parent
        width: win.width - 48
        height: win.height - 48
        modal: true
        padding: 0
        background: Rectangle { color: t.surface; radius: 12; border.color: t.border }

        ColumnLayout {
            anchors.fill: parent
            spacing: 0
            RowLayout {
                Layout.fillWidth: true
                Layout.margins: 12
                Text { text: "Drag to compare"; color: t.subtext; font.pixelSize: 12; Layout.leftMargin: 6 }
                Item { Layout.fillWidth: true }
                Button { text: "Open"; onClicked: backend.openFile(win.compareItem ? win.compareItem.output : "") }
                IconButton { glyph: ""; tip: "Close"; onClicked: comparePopup.close() }
            }
            Item {
                id: stage
                Layout.fillWidth: true
                Layout.fillHeight: true
                Layout.margins: 12
                Layout.topMargin: 0
                clip: true
                property real split: width / 2

                Canvas {
                    anchors.fill: parent
                    onPaint: {
                        const ctx = getContext("2d"), s = 12
                        for (let y = 0; y < height; y += s)
                            for (let x = 0; x < width; x += s) {
                                ctx.fillStyle = ((x / s + y / s) % 2 === 0) ? (t.dark ? "#3a3a3a" : "#ffffff")
                                                                           : (t.dark ? "#2c2c2c" : "#e6e6e6")
                                ctx.fillRect(x, y, s, s)
                            }
                    }
                    onWidthChanged: requestPaint()
                    onHeightChanged: requestPaint()
                }
                Image {
                    anchors.fill: parent
                    source: win.compareItem ? win.compareItem.before : ""
                    fillMode: Image.PreserveAspectFit
                    cache: false
                }
                Item {
                    width: stage.split
                    height: parent.height
                    clip: true
                    Canvas {
                        width: stage.width; height: stage.height
                        onPaint: {
                            const ctx = getContext("2d"), s = 12
                            for (let y = 0; y < height; y += s)
                                for (let x = 0; x < width; x += s) {
                                    ctx.fillStyle = ((x / s + y / s) % 2 === 0) ? (t.dark ? "#3a3a3a" : "#ffffff")
                                                                               : (t.dark ? "#2c2c2c" : "#e6e6e6")
                                    ctx.fillRect(x, y, s, s)
                                }
                        }
                    }
                    Image {
                        width: stage.width; height: stage.height
                        source: win.compareItem ? win.compareItem.after : ""
                        fillMode: Image.PreserveAspectFit
                        cache: false
                    }
                }
                Rectangle { x: stage.split - 1; width: 2; height: parent.height; color: t.accent }
                Rectangle {
                    x: stage.split - 16; y: parent.height / 2 - 16
                    width: 32; height: 32; radius: 16
                    color: t.accent
                    Icon { anchors.centerIn: parent; glyph: ""; color: t.accentText; font.pixelSize: 13 }
                }
                Text { x: 10; y: 10; text: "Result"; color: t.text; font.pixelSize: 12; font.weight: Font.DemiBold }
                Text { anchors.right: parent.right; anchors.rightMargin: 10; y: 10; text: "Original"; color: t.text; font.pixelSize: 12; font.weight: Font.DemiBold }
                MouseArea {
                    anchors.fill: parent
                    cursorShape: Qt.SplitHCursor
                    onPressed: (m) => stage.split = Math.max(0, Math.min(stage.width, m.x))
                    onPositionChanged: (m) => stage.split = Math.max(0, Math.min(stage.width, m.x))
                }
            }
        }
    }

    // ---- settings --------------------------------------------------------------------
    Drawer {
        id: settingsDrawer
        objectName: "settingsDrawer"
        edge: Qt.RightEdge
        width: Math.min(380, win.width - 40)
        height: win.height
        background: Rectangle { color: t.surface; Rectangle { width: 1; height: parent.height; color: t.border } }

        ScrollView {
            id: settingsScroll
            anchors.fill: parent
            contentWidth: availableWidth
            ColumnLayout {
                width: settingsScroll.availableWidth
                spacing: 18
                Item { implicitHeight: 4 }
                RowLayout {
                    Layout.leftMargin: 22; Layout.rightMargin: 12
                    Text { text: "Settings"; color: t.text; font.pixelSize: 20; font.weight: Font.DemiBold }
                    Item { Layout.fillWidth: true }
                    IconButton { glyph: ""; onClicked: settingsDrawer.close() }
                }

                ColumnLayout {
                    Layout.leftMargin: 22; Layout.rightMargin: 22
                    spacing: 6
                    SectionLabel { text: "SAVE CONVERTED FILES" }
                    RadioButton {
                        text: "Next to the original file"
                        checked: backend.settings.outputMode === "beside"
                        onClicked: backend.setSetting("outputMode", "beside")
                    }
                    RadioButton {
                        text: backend.settings.outputFolder !== "" ? "In " + backend.settings.outputFolder : "In a folder I choose"
                        checked: backend.settings.outputMode === "folder"
                        onClicked: backend.settings.outputFolder !== "" ? backend.setSetting("outputMode", "folder") : folderDialog.open()
                    }
                    Button { text: "Choose folder…"; Layout.leftMargin: 28; onClicked: folderDialog.open() }
                    Text {
                        text: "Originals are never changed or overwritten."
                        color: t.subtext; font.pixelSize: 12; Layout.topMargin: 2
                    }
                }

                ColumnLayout {
                    Layout.leftMargin: 22; Layout.rightMargin: 22
                    spacing: 8
                    SectionLabel { text: "APPEARANCE" }
                    Row {
                        spacing: 6
                        Repeater {
                            model: [["system", "System"], ["light", "Light"], ["dark", "Dark"]]
                            Chip {
                                small: true
                                label: modelData[1]
                                selected: backend.settings.theme === modelData[0]
                                onClicked: backend.setSetting("theme", modelData[0])
                            }
                        }
                    }
                }

                ColumnLayout {
                    Layout.leftMargin: 22; Layout.rightMargin: 22
                    spacing: 6
                    SectionLabel { text: "AI TOOLS" }
                    Switch {
                        text: "Use the graphics card (much faster)"
                        checked: backend.settings.gpu
                        onToggled: backend.setSetting("gpu", checked)
                    }
                    Repeater {
                        model: backend.models
                        RowLayout {
                            Layout.fillWidth: true
                            Layout.topMargin: 4
                            ColumnLayout {
                                Layout.fillWidth: true
                                spacing: 2
                                Text { text: modelData.label; color: t.text; font.pixelSize: 13; wrapMode: Text.Wrap; Layout.fillWidth: true }
                                Text {
                                    text: modelData.sizeText + (modelData.installed ? " · Installed" : " · Not downloaded")
                                    color: modelData.installed ? t.success : t.subtext
                                    font.pixelSize: 12
                                }
                            }
                            Button {
                                text: modelData.installed ? "Delete" : "Download"
                                enabled: backend.download.model === "" && !backend.busy
                                onClicked: modelData.installed ? backend.deleteModel(modelData.id) : backend.downloadModel(modelData.id)
                            }
                        }
                    }
                }

                Rectangle {
                    Layout.leftMargin: 22; Layout.rightMargin: 22; Layout.topMargin: 6
                    Layout.fillWidth: true
                    implicitHeight: privacy.implicitHeight + 24
                    radius: 8
                    color: t.surfaceAlt
                    Text {
                        id: privacy
                        anchors.fill: parent
                        anchors.margins: 12
                        wrapMode: Text.Wrap
                        color: t.subtext
                        font.pixelSize: 12
                        text: "Conversor works offline. Your files never leave this PC and there is no tracking. "
                              + "The only internet access is downloading AI models you approve, each verified with SHA-256. "
                              + "Every file is processed in an isolated, memory-limited worker process."
                    }
                }
                Item { implicitHeight: 12 }
            }
        }
    }

    // ---- toast -------------------------------------------------------------------------
    Rectangle {
        id: toast
        property alias text: toastText.text
        anchors.horizontalCenter: parent.horizontalCenter
        y: parent.height - height - 84
        width: toastText.implicitWidth + 32
        height: 38
        radius: 19
        color: t.dark ? "#f0f0f0" : "#262626"
        opacity: 0
        visible: opacity > 0
        Behavior on opacity { NumberAnimation { duration: 180 } }
        Text { id: toastText; anchors.centerIn: parent; color: t.dark ? "#1a1a1a" : "#ffffff"; font.pixelSize: 13 }
        Timer { id: toastTimer; interval: 3200; onTriggered: toast.opacity = 0 }
    }

    Connections {
        target: backend
        function onToast(message) { toast.text = message; toast.opacity = 1; toastTimer.restart() }
        function onOptionsRequested(kind) {
            let e = Object.assign({}, win.expanded)
            e[kind] = true
            win.expanded = e
        }
        function onModelNeeded(id, label, sizeMb) {
            modelDialog.modelId = id
            modelDialog.modelLabel = label
            modelDialog.sizeMb = sizeMb
            modelDialog.open()
        }
    }
}
