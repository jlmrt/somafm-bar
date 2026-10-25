import QtQuick
import qs.Commons
import qs.Ui

Button {
  id: root

  property string label: ""

  implicitHeight: labelText.implicitHeight + verticalPadding * 2
    + _reservedBorderTop + _reservedBorderBottom
  clip: true
  focusable: true
  Accessible.role: Accessible.Button
  Accessible.name: label

  Text {
    id: labelText
    x: root._reservedContentLeftInset
    width: Math.max(0, root.width - x - root.horizontalPadding - root._reservedBorderRight)
    anchors.verticalCenter: parent.verticalCenter
    text: root.label
    textFormat: Text.PlainText
    elide: Text.ElideRight
    color: root.selected ? root._selectedColor : root.foreground
    font.family: root.fontFamily
    font.pixelSize: root.fontSize
    font.bold: root.selected
  }
}
