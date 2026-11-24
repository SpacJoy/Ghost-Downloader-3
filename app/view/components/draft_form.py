from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtGui import QColor, QTextOption
from PySide6.QtWidgets import QHBoxLayout, QVBoxLayout, QWidget
from qfluentwidgets import (
    BodyLabel, CaptionLabel, CheckBox, ComboBox, FluentIcon, IconWidget,
    LineEdit, Slider, ToolTipFilter, TransparentToolButton,
)

from app.config.cfg import cfg
from app.format import toReadableSize
from app.view.components.category_settings import toCategoryName
from app.view.components.editors import AutoSizingEdit, FolderPicker

if TYPE_CHECKING:
    from app.services.category_service import CategoryService


class UrlRow(QWidget):
    pasteRequested = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.edit = AutoSizingEdit(self, minimumVisibleLines=1)
        self.pasteButton = TransparentToolButton(FluentIcon.PASTE, self)

        self._initWidget()
        self._initLayout()
        self._bind()

    def _initWidget(self) -> None:
        self.edit.setPlaceholderText(self.tr("添加多个下载链接时，请确保每行只有一个下载链接"))
        self.edit.setWordWrapMode(QTextOption.WrapMode.NoWrap)
        self.pasteButton.setFixedSize(32, 32)
        self.pasteButton.setIconSize(QSize(16, 16))
        self.pasteButton.setToolTip(self.tr("从剪贴板粘贴链接"))
        self.pasteButton.installEventFilter(ToolTipFilter(self.pasteButton))

    def _initLayout(self) -> None:
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        layout.addWidget(self.edit, 1)
        layout.addWidget(self.pasteButton, 0, Qt.AlignmentFlag.AlignVCenter)

    def _bind(self) -> None:
        self.pasteButton.clicked.connect(self.pasteRequested)


class CategoryRow(QWidget):
    changed = Signal()

    def __init__(self, categoryService: CategoryService, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._categoryService = categoryService
        self.checkBox = CheckBox(self)
        self.combo = ComboBox(self)
        self.addButton = TransparentToolButton(FluentIcon.ADD, self)

        self._initWidget()
        self._initLayout()
        self._bind()

    def _initWidget(self) -> None:
        self.checkBox.setText(self.tr("分类到"))
        self.combo.setMinimumWidth(200)
        self.combo.setEnabled(False)
        self.addButton.setFixedSize(32, 32)
        self.addButton.setIconSize(QSize(16, 16))
        self.addButton.setToolTip(self.tr("新建分类"))
        self.addButton.installEventFilter(ToolTipFilter(self.addButton))
        self.refreshCategories()
        self.applyDefault()

    def _initLayout(self) -> None:
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        layout.addWidget(self.checkBox)
        layout.addWidget(self.combo, 1)
        layout.addWidget(self.addButton)

    def _bind(self) -> None:
        self.checkBox.toggled.connect(self._onToggled)
        self.combo.currentIndexChanged.connect(self._onIndexChanged)
        self.addButton.clicked.connect(self._onAddClicked)
        self._categoryService.categoriesChanged.connect(self.refreshCategories, owner=self)

    def refreshCategories(self) -> None:
        current = self.combo.currentData()
        self.combo.blockSignals(True)
        self.combo.clear()
        self.combo.addItem(self.tr("自动"), userData=None)
        for category in self._categoryService.categories():
            self.combo.addItem(
                toCategoryName(category),
                icon=getattr(FluentIcon, category.icon, FluentIcon.TAG),
                userData=category.categoryId,
            )
        index = self.combo.findData(current)
        self.combo.setCurrentIndex(max(0, index))
        self.combo.blockSignals(False)

    def options(self) -> dict:
        if not self.checkBox.isChecked():
            return {"category": None}
        return {"category": self.combo.currentData()}

    def applyDefault(self) -> None:
        isEnabled = cfg.isCategoryEnabled.value
        self.checkBox.blockSignals(True)
        self.checkBox.setChecked(isEnabled)
        self.checkBox.blockSignals(False)
        self.combo.setEnabled(isEnabled)

    def reset(self) -> None:
        self.combo.blockSignals(True)
        self.combo.setCurrentIndex(0)
        self.combo.blockSignals(False)
        self.applyDefault()
        self.refreshCategories()

    def _onToggled(self, checked: bool) -> None:
        self.combo.setEnabled(checked)
        self.changed.emit()

    def _onIndexChanged(self, index: int) -> None:
        if self.checkBox.isChecked():
            self.changed.emit()

    def _onAddClicked(self) -> None:
        from app.view.dialogs.category_edit import CategoryEditDialog

        dialog = CategoryEditDialog(self.window())
        accepted = dialog.exec() == CategoryEditDialog.DialogCode.Accepted
        category = dialog.category() if accepted else None
        dialog.deleteLater()
        if category is None:
            return
        self._categoryService.addCategory(category)
        self.refreshCategories()
        self.checkBox.setChecked(True)
        self.combo.setCurrentIndex(max(0, self.combo.findData(category.categoryId)))


class MetaColumn(QWidget):

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.sizeLabel = BodyLabel("--", self)
        self.resumeLabel = CaptionLabel("", self)

        self._initWidget()
        self._initLayout()

    def _initWidget(self) -> None:
        self.sizeLabel.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.resumeLabel.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.resumeLabel.hide()

    def _initLayout(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self.sizeLabel)
        layout.addWidget(self.resumeLabel)

    def setMeta(self, size: int, canResume: bool | None) -> None:
        self.sizeLabel.setText(toReadableSize(size) if size > 0 else "--")
        if canResume is None:
            self.resumeLabel.hide()
            return
        if canResume:
            self.resumeLabel.setText(self.tr("支持续传"))
            self.resumeLabel.setTextColor(QColor(16, 124, 16), QColor(108, 203, 95))
        else:
            self.resumeLabel.setText(self.tr("不支持续传"))
            self.resumeLabel.setTextColor(QColor(150, 150, 150), QColor(160, 160, 160))
        self.resumeLabel.show()


class PathRow(QWidget):
    settingsRequested = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.folderPicker = FolderPicker(lambda: cfg.downloadFolder.value, self.tr("默认"), self)
        self.resetButton = TransparentToolButton(FluentIcon.SYNC, self)
        self.settingsButton = TransparentToolButton(FluentIcon.SETTING, self)

        self._initWidget()
        self._initLayout()
        self._bind()

    def _initWidget(self) -> None:
        self.folderPicker.setPath(cfg.downloadFolder.value)
        for button, text in (
            (self.resetButton, self.tr("恢复默认下载路径")),
            (self.settingsButton, self.tr("下载设置")),
        ):
            button.setFixedSize(32, 32)
            button.setIconSize(QSize(16, 16))
            button.setToolTip(text)
            button.installEventFilter(ToolTipFilter(button))

    def _initLayout(self) -> None:
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        layout.addWidget(self.folderPicker, 1)
        layout.addWidget(self.resetButton)
        layout.addWidget(self.settingsButton)

    def _bind(self) -> None:
        self.resetButton.clicked.connect(self.reset)
        self.settingsButton.clicked.connect(self.settingsRequested)

    def path(self) -> str:
        return self.folderPicker.path()

    def setPath(self, path: str) -> None:
        self.folderPicker.setPath(path)

    def options(self) -> dict:
        return {"outputFolder": Path(self.path() or cfg.downloadFolder.value)}

    def reset(self) -> None:
        self.folderPicker.setPath(cfg.downloadFolder.value)


class SubworkerRow(QWidget):

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.iconLabel = IconWidget(FluentIcon.CLOUD, self)
        self.titleLabel = BodyLabel(self.tr("预分配线程数"), self)
        self.valueLabel = CaptionLabel(str(cfg.preBlockNum.value), self)
        self.slider = Slider(Qt.Orientation.Horizontal, self)

        self._initWidget()
        self._initLayout()
        self._bind()

    def _initWidget(self) -> None:
        self.iconLabel.setFixedSize(16, 16)
        self.slider.setRange(*cfg.preBlockNum.range)
        self.slider.setSingleStep(1)
        self.slider.setValue(cfg.preBlockNum.value)
        self.slider.setMinimumWidth(180)

    def _initLayout(self) -> None:
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        layout.addWidget(self.iconLabel)
        layout.addWidget(self.titleLabel)
        layout.addStretch(1)
        layout.addWidget(self.valueLabel)
        layout.addWidget(self.slider, 2)

    def _bind(self) -> None:
        self.slider.valueChanged.connect(self._onValueChanged)

    def options(self) -> dict:
        return {"subworkerCount": self.slider.value()}

    def reset(self) -> None:
        self.slider.setValue(cfg.preBlockNum.value)

    def _onValueChanged(self, value: int) -> None:
        self.valueLabel.setText(str(value))


class NameRow(QWidget):
    changed = Signal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.edit = LineEdit(self)

        self._initWidget()
        self._initLayout()
        self._bind()

    def _initWidget(self) -> None:
        self.edit.setPlaceholderText(self.tr("文件名，留空则从链接自动推断"))
        self.edit.setClearButtonEnabled(True)

    def _initLayout(self) -> None:
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self.edit)

    def _bind(self) -> None:
        self.edit.editingFinished.connect(self._onEditingFinished)

    def name(self) -> str:
        return self.edit.text().strip()

    def setName(self, name: str) -> None:
        if self.edit.text() != name:
            self.edit.setText(name)

    def _onEditingFinished(self) -> None:
        self.changed.emit(self.name())
