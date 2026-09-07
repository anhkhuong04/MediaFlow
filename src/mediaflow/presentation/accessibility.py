"""Small, Qt-only accessibility helpers shared by presentation screens."""

from __future__ import annotations

from PySide6.QtWidgets import QAbstractButton, QComboBox, QLineEdit, QSpinBox, QWidget


def label_control(label: QWidget, control: QWidget, *, description: str | None = None) -> None:
    """Give labelled controls an explicit relationship and useful accessible text."""

    set_buddy = getattr(label, "setBuddy", None)
    if callable(set_buddy):
        set_buddy(control)
    if not control.accessibleName():
        control.setAccessibleName(_control_name(control))
    if description and not control.accessibleDescription():
        control.setAccessibleDescription(description)


def complete_control_accessibility(root: QWidget) -> None:
    """Fill safe names for controls whose visible label is their only current affordance."""

    controls = (
        *root.findChildren(QAbstractButton),
        *root.findChildren(QComboBox),
        *root.findChildren(QLineEdit),
        *root.findChildren(QSpinBox),
    )
    for control in controls:
        if not control.accessibleName():
            control.setAccessibleName(_control_name(control))
        if not control.accessibleDescription():
            control.setAccessibleDescription(control.accessibleName())


def _control_name(control: QWidget) -> str:
    if isinstance(control, QLineEdit):
        return control.placeholderText() or control.objectName()
    if isinstance(control, (QAbstractButton, QComboBox, QSpinBox)):
        text = getattr(control, "text", None)
        if callable(text) and text():
            return str(text())
        current_text = getattr(control, "currentText", None)
        if callable(current_text) and current_text():
            return str(current_text())
    return control.objectName() or control.metaObject().className()
