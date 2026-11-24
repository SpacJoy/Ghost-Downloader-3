from __future__ import annotations

import sys
from collections import deque
from pathlib import Path
from typing import TYPE_CHECKING

from PySide6.QtCore import QCoreApplication, QFileInfo, QPointF, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QLinearGradient, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import (
    QFileIconProvider, QGridLayout, QHBoxLayout, QLabel, QSizePolicy, QStackedWidget, QVBoxLayout, QWidget,
)
from qfluentwidgets import (
    BodyLabel, CaptionLabel, ComboBox, FluentIcon, LineEdit, StrongBodyLabel, ToolButton,
    TransparentToolButton, isDarkTheme,
)
from qfluentwidgets.common.font import setFont

from app.format import toReadableSize
from app.models.task import SpecialFileSize, TaskStatus
from app.platform.desktop import openFile, revealInFolder, startFileDrag
from app.platform.desktop_notification import (
    FILE_ICON_SIZE, ICON_SPACING, PADDING, SPACING, Popup,
)
from app.services.plan import Plan, PlanAction

# 图三/图四是完整的任务窗口而不是角标提示，比默认 364 宽一档才放得下三选项卡和完整文件名
POPUP_WIDTH = 440
HEADER_HEIGHT = 32
HEADER_TEXT_WIDTH = POPUP_WIDTH - 2 * PADDING - 16 - ICON_SPACING - 2 * 32 - 2 * SPACING
TAB_HEIGHT = 28
TAB_RADIUS = 5
TAB_GAP = 16
TAB_ICON_SIZE = 16
TAB_ICON_GAP = 4
TAB_PADDING_LEFT = 10
TAB_PADDING_RIGHT = 12
TAB_TEXT = QColor(168, 168, 169), QColor(120, 120, 124)
TAB_TEXT_CURRENT = QColor(214, 214, 214), QColor(38, 38, 40)
TAB_FILL = QColor(42, 43, 47), QColor(0, 0, 0, 14)
CONTENT_HEIGHT = 152
INFO_LABEL_WIDTH = 123
INFO_VALUE_WIDTH = POPUP_WIDTH - PADDING - INFO_LABEL_WIDTH - PADDING
BUTTON_PADDING = 13
BUTTON_ICON_SIZE = 14
BUTTON_ICON_GAP = 4
BAR_HEIGHT = 14
CORNER = 6
FOOTER_TOP = 8
FOOTER_BOTTOM = 12
FOOTER_SPACING = 8
BUTTON_HEIGHT = 27
BUTTON_RADIUS = 3
BUTTON_FILL = QColor(42, 43, 47), QColor(253, 253, 253)
BUTTON_BORDER = QColor(60, 61, 64), QColor(198, 198, 203)
BUTTON_TEXT = QColor(214, 214, 214), QColor(32, 32, 34)
FOOTER_FILL = QColor(36, 37, 41), QColor(0, 0, 0, 0)
FOOTER_LINE = QColor(58, 58, 61), QColor(0, 0, 0, 20)
SPEED_SAMPLE_COUNT = 60
CHECK_MARK_SIZE = 26
DONE_GREEN = QColor("#0f7b0f"), QColor("#6ccb5f")
SUB_TEXT_COLOR = QColor(0, 0, 0, 155), QColor(255, 255, 255, 155)


def toRemainingText(seconds: int) -> str:
    if seconds < 60:
        return QCoreApplication.translate("TaskPopup", "{0} 秒").format(seconds)
    minutes, secs = divmod(seconds, 60)
    if seconds < 3600:
        if secs:
            return QCoreApplication.translate("TaskPopup", "{0} 分 {1} 秒").format(minutes, secs)
        return QCoreApplication.translate("TaskPopup", "{0} 分").format(minutes)
    hours, minutes = divmod(minutes, 60)
    if minutes:
        return QCoreApplication.translate("TaskPopup", "{0} 小时 {1} 分").format(hours, minutes)
    return QCoreApplication.translate("TaskPopup", "{0} 小时").format(hours)


def toStatusText(task: Task) -> str:
    if task.status == TaskStatus.RUNNING:
        return QCoreApplication.translate("TaskPopup", "正在下载")
    if task.status == TaskStatus.PAUSED:
        return QCoreApplication.translate("TaskPopup", "已暂停")
    if task.status == TaskStatus.COMPLETED:
        return QCoreApplication.translate("TaskPopup", "已完成")
    if task.status == TaskStatus.FAILED:
        return QCoreApplication.translate("TaskPopup", "已失败")
    return QCoreApplication.translate("TaskPopup", "等待中")


def _pick(pair, isDark: bool) -> QColor:
    return pair[0] if isDark else pair[1]


class HLine(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(1)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor(255, 255, 255, 12) if isDarkTheme() else QColor(0, 0, 0, 16))


class BoltIcon:
    """速度选项卡的闪电图标，qfluentwidgets 没有对应的 FluentIcon"""

    def render(self, painter: QPainter, rect: QRectF, fill: str = "#ffffff") -> None:
        pen = QPen(QColor(fill), 1.4)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        points = ((0.58, 0.08), (0.22, 0.54), (0.47, 0.54), (0.40, 0.92), (0.78, 0.44), (0.52, 0.44), (0.58, 0.08))
        painter.drawPolyline([QPointF(rect.left() + x * rect.width(), rect.top() + y * rect.height())
                              for x, y in points])


class MinimizeButton(TransparentToolButton):
    """FluentIcon.MINIMIZE 是带箭头的方框，参考图用的是简单一横"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._icon = None  # 不画图标，只画自己的一横
        self.setFixedSize(32, 32)
        policy = self.sizePolicy()
        policy.setRetainSizeWhenHidden(True)
        self.setSizePolicy(policy)
        self.hide()

    def paintEvent(self, event):
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(QPen(QColor(255, 255, 255) if isDarkTheme() else QColor(0, 0, 0), 1))
        center = self.rect().center()
        painter.drawLine(QPointF(center.x() - 5, center.y()), QPointF(center.x() + 5, center.y()))


class TabItem:
    def __init__(self, routeKey: str, text: str, icon):
        self.routeKey = routeKey
        self.text = text
        self.icon = icon
        self.rect = QRectF()


class TabBar(QWidget):
    currentChanged = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._items: list[TabItem] = []
        self._current: str | None = None
        self._hoverIndex = -1
        self.setFixedHeight(TAB_HEIGHT)
        self.setMouseTracking(True)

    def addItem(self, routeKey: str, text: str, icon) -> None:
        self._items.append(TabItem(routeKey, text, icon))
        self.updateGeometry()
        self.update()

    def setCurrentItem(self, routeKey: str) -> None:
        if self._current == routeKey:
            return
        self._current = routeKey
        self.update()
        self.currentChanged.emit(routeKey)

    def currentRouteKey(self) -> str | None:
        return self._current

    def _itemWidth(self, item: TabItem) -> float:
        textWidth = self.fontMetrics().horizontalAdvance(item.text)
        return TAB_PADDING_LEFT + TAB_ICON_SIZE + TAB_ICON_GAP + textWidth + TAB_PADDING_RIGHT

    def _relayout(self) -> None:
        x, y = 0.0, 0.0
        for item in self._items:
            width = self._itemWidth(item)
            item.rect = QRectF(x, y, width, self.height())
            x += width + TAB_GAP

    def sizeHint(self):
        self._relayout()
        width = sum(self._itemWidth(item) for item in self._items) + TAB_GAP * max(0, len(self._items) - 1)
        size = super().sizeHint()
        size.setWidth(int(width))
        size.setHeight(TAB_HEIGHT)
        return size

    def _indexAt(self, x: float) -> int:
        for index, item in enumerate(self._items):
            if item.rect.contains(x, item.rect.center().y()):
                return index
        return -1

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            index = self._indexAt(event.position().x())
            if index >= 0:
                self.setCurrentItem(self._items[index].routeKey)
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        index = self._indexAt(event.position().x())
        if index != self._hoverIndex:
            self._hoverIndex = index
            self.update()
        super().mouseMoveEvent(event)

    def leaveEvent(self, event):
        self._hoverIndex = -1
        self.update()
        super().leaveEvent(event)

    def paintEvent(self, event):
        isDark = isDarkTheme()
        self._relayout()
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        for index, item in enumerate(self._items):
            isCurrent = item.routeKey == self._current
            if isCurrent:
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(_pick(TAB_FILL, isDark))
                painter.drawRoundedRect(item.rect, TAB_RADIUS, TAB_RADIUS)
            color = _pick(TAB_TEXT_CURRENT if isCurrent else TAB_TEXT, isDark)
            iconRect = QRectF(item.rect.left() + TAB_PADDING_LEFT, item.rect.top() + (TAB_HEIGHT - TAB_ICON_SIZE) / 2,
                              TAB_ICON_SIZE, TAB_ICON_SIZE)
            item.icon.render(painter, iconRect, fill=color.name())
            painter.setPen(color)
            textRect = QRectF(iconRect.right() + TAB_ICON_GAP, item.rect.top(),
                              item.rect.right() - iconRect.right() - TAB_ICON_GAP - TAB_PADDING_RIGHT, TAB_HEIGHT)
            painter.drawText(textRect, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, item.text)


class GradientProgressBar(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._value = 0.0
        self._isPaused = False
        self._isIndeterminate = False
        self._offset = 0.0
        self._timer = QTimer(self)
        self._timer.setInterval(16)
        self._timer.timeout.connect(self._onTick)
        self.setFixedHeight(BAR_HEIGHT)

    def setValue(self, value: float) -> None:
        self._value = max(0.0, min(100.0, value))
        self.update()

    def setPaused(self, isPaused: bool) -> None:
        if self._isPaused != isPaused:
            self._isPaused = isPaused
            self.update()

    def setIndeterminate(self, isIndeterminate: bool) -> None:
        if self._isIndeterminate == isIndeterminate:
            return
        self._isIndeterminate = isIndeterminate
        if isIndeterminate:
            self._timer.start()
        else:
            self._timer.stop()
        self.update()

    def _onTick(self) -> None:
        self._offset = (self._offset + 0.008) % 1.0
        self.update()

    def paintEvent(self, event):
        width, height = self.width(), self.height()
        radius = height / 2
        track = QRectF(0, 0, width, height)

        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(63, 63, 67) if isDarkTheme() else QColor(0, 0, 0, 22))
        painter.drawRoundedRect(track, radius, radius)

        if self._isIndeterminate:
            span = width * 0.35
            fillRect = QRectF(self._offset * (width + span) - span, 0, span, height)
        else:
            fillRect = QRectF(0, 0, width * self._value / 100, height)
        fillRect = fillRect.intersected(track)
        if fillRect.width() <= 0:
            return

        gradient = QLinearGradient(0, 0, width, 0)
        if self._isPaused:
            gradient.setColorAt(0.0, QColor(140, 140, 140))
            gradient.setColorAt(1.0, QColor(170, 170, 170))
        else:
            gradient.setColorAt(0.0, QColor(72, 144, 192))
            gradient.setColorAt(0.5, QColor(122, 122, 220))
            gradient.setColorAt(1.0, QColor(181, 94, 253))

        clip = QPainterPath()
        clip.addRoundedRect(track, radius, radius)
        painter.setClipPath(clip)
        painter.setBrush(gradient)
        painter.drawRect(fillRect)
        painter.setClipping(False)


class FooterButton(QWidget):
    clicked = Signal()

    def __init__(self, icon, parent=None, text: str = "", isIconOnly: bool = False):
        super().__init__(parent)
        self._icon = icon
        self._text = text
        self._isIconOnly = isIconOnly
        self._isHovered = False
        self._isPressed = False
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedHeight(BUTTON_HEIGHT)
        if isIconOnly:
            self.setFixedWidth(BUTTON_HEIGHT)

    def setText(self, text: str) -> None:
        if self._text != text:
            self._text = text
            self.updateGeometry()
            self.update()

    def text(self) -> str:
        return self._text

    def setIcon(self, icon) -> None:
        self._icon = icon
        self.update()

    def sizeHint(self):
        size = super().sizeHint()
        size.setHeight(BUTTON_HEIGHT)
        if self._isIconOnly:
            size.setWidth(BUTTON_HEIGHT)
            return size
        width = BUTTON_PADDING * 2
        if self._icon is not None:
            width += BUTTON_ICON_SIZE + BUTTON_ICON_GAP
        if self._text:
            width += self.fontMetrics().horizontalAdvance(self._text)
        size.setWidth(width)
        return size

    def enterEvent(self, event):
        self._isHovered = True
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event):
        self._isHovered = False
        self._isPressed = False
        self.update()
        super().leaveEvent(event)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._isPressed = True
            self.update()

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and self._isPressed:
            self._isPressed = False
            self.update()
            if self.rect().contains(event.position().toPoint()):
                self.clicked.emit()

    def paintEvent(self, event):
        isDark = isDarkTheme()
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        fill = _pick(BUTTON_FILL, isDark)
        if not self.isEnabled():
            fill = QColor(fill.red(), fill.green(), fill.blue(), 90)
        elif self._isPressed:
            fill = fill.darker(115)
        elif self._isHovered:
            fill = fill.lighter(115) if isDark else fill.darker(104)
        painter.setPen(QPen(_pick(BUTTON_BORDER, isDark), 1))
        painter.setBrush(fill)
        painter.drawRoundedRect(rect, BUTTON_RADIUS, BUTTON_RADIUS)

        color = _pick(BUTTON_TEXT, isDark)
        if not self.isEnabled():
            color = QColor(color.red(), color.green(), color.blue(), 110)
        contentWidth = rect.width() - BUTTON_PADDING * 2
        if self._isIconOnly:
            if self._icon is not None:
                size = BUTTON_ICON_SIZE + 2
                self._icon.render(painter, QRectF(rect.center().x() - size / 2, rect.center().y() - size / 2, size, size),
                                  fill=color.name())
            return

        x = rect.left() + BUTTON_PADDING
        if self._icon is not None:
            iconRect = QRectF(x, rect.center().y() - BUTTON_ICON_SIZE / 2, BUTTON_ICON_SIZE, BUTTON_ICON_SIZE)
            self._icon.render(painter, iconRect, fill=color.name())
            x = iconRect.right() + BUTTON_ICON_GAP
        painter.setPen(color)
        painter.drawText(QRectF(x, rect.top(), rect.right() - x, rect.height()),
                         Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, self._text)


class Footer(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, False)

    def paintEvent(self, event):
        isDark = isDarkTheme()
        painter = QPainter(self)
        painter.fillRect(self.rect(), _pick(FOOTER_FILL, isDark))
        painter.fillRect(0, 0, self.width(), 1, _pick(FOOTER_LINE, isDark))


def _toNiceScale(value: float) -> float:
    magnitude = 1
    while value >= magnitude * 10:
        magnitude *= 10
    for step in (1, 2, 5, 10):
        if value <= magnitude * step:
            return float(magnitude * step)
    return float(magnitude * 10)


class SpeedChart(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._samples = deque(maxlen=SPEED_SAMPLE_COUNT)
        self.setMinimumHeight(64)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

    def addSample(self, speed: int) -> None:
        self._samples.append(max(0, speed))
        self.update()

    def peak(self) -> int:
        return max(self._samples, default=0)

    def clear(self) -> None:
        self._samples.clear()
        self.update()

    def paintEvent(self, event):
        width, height = self.width(), self.height()
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(255, 255, 255, 18) if isDarkTheme() else QColor(0, 0, 0, 14))
        painter.drawRoundedRect(QRectF(0, 0, width, height), CORNER, CORNER)

        if len(self._samples) < 2:
            return
        # 峰值取整到 1/2/5 台阶再留 15% 余量，否则速度平稳时曲线会贴死顶边
        peak = _toNiceScale(max(max(self._samples), 1) * 1.15)
        step = width / (SPEED_SAMPLE_COUNT - 1)
        # 最新的采样贴右边，历史往左长
        offset = width - (len(self._samples) - 1) * step
        points = [
            QPointF(offset + index * step, height - 6 - sample / peak * (height - 12))
            for index, sample in enumerate(self._samples)
        ]

        area = QPainterPath(QPointF(points[0].x(), height))
        for point in points:
            area.lineTo(point)
        area.lineTo(points[-1].x(), height)
        area.closeSubpath()

        gradient = QLinearGradient(0, 0, 0, height)
        gradient.setColorAt(0.0, QColor(56, 132, 255, 110))
        gradient.setColorAt(1.0, QColor(56, 132, 255, 0))
        painter.setBrush(gradient)
        painter.drawPath(area)

        painter.setPen(QPen(QColor(86, 156, 255), 2, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        for start, end in zip(points, points[1:]):
            painter.drawLine(start, end)




class TaskPopup(Popup):
    hasTaskbarButton = True

    def __init__(self, task: Task, taskService: TaskService, speedChanged: Signal, plan: Plan | None = None):
        super().__init__()
        self._task = task
        self._taskService = taskService
        self._speedChanged = speedChanged
        self._plan = plan
        self._planActions: list[PlanAction | None] = []
        self._isUpdatingPlan = False
        self._ownsPlan = False
        self._isExpanded = True
        self.popupId = f"task:{task.taskId}"
        self._initWidget()
        self._initLayout()
        self._bind()
        self._syncPlan()
        self.refresh()

    def _initWidget(self) -> None:
        self.setWindowIcon(QFileIconProvider().icon(QFileInfo(self._task.outputPath)))
        super()._initWidget()
        self.setWindowTitle(self._task.name)
        if sys.platform == "win32":
            from app.config.constants import DESKTOP_ID
            from app.platform.taskbar import setWindowAppId
            setWindowAppId(int(self.winId()), f"{DESKTOP_ID}.{self._task.taskId.replace('_', '-')}")
        self.setFixedWidth(POPUP_WIDTH)
        self.minimizeButton = MinimizeButton(self)
        self.headerButtons.insert(0, self.minimizeButton)

        self.tabBar = TabBar(self)
        setFont(self.tabBar, 12)
        self.tabBar.addItem("info", self.tr("信息"), FluentIcon.INFO)
        self.tabBar.addItem("speed", self.tr("速度"), BoltIcon())
        self.tabBar.addItem("plan", self.tr("完成后"), FluentIcon.FLAG)
        self.tabBar.setCurrentItem("info")

        self.stack = QStackedWidget(self)
        self.stack.addWidget(self._buildInfoPage())
        self.stack.addWidget(self._buildSpeedPage())
        self.stack.addWidget(self._buildPlanPage())

        self.progressBar = GradientProgressBar(self)
        if self._task.fileSize in {SpecialFileSize.UNKNOWN, SpecialFileSize.NOT_SUPPORTED}:
            self.progressBar.setIndeterminate(True)

        self.expandButton = FooterButton(FluentIcon.ARROW_DOWN, self, isIconOnly=True)
        self.expandButton.setToolTip(self.tr("收起详情"))
        self.toggleButton = FooterButton(None, self)
        self.cancelButton = FooterButton(None, self, text=self.tr("取消"))

    def _buildInfoPage(self) -> QWidget:
        page = QWidget(self)
        grid = QGridLayout(page)
        grid.setContentsMargins(PADDING, 10, PADDING, 0)
        grid.setHorizontalSpacing(0)
        grid.setVerticalSpacing(2)
        grid.setColumnStretch(1, 1)

        self.infoValues: dict[str, QLabel] = {}
        rows = (
            ("name", self.tr("名称：")),
            ("status", self.tr("状态：")),
            ("size", self.tr("大小：")),
            ("received", self.tr("已下载：")),
            ("speed", self.tr("速度：")),
            ("remaining", self.tr("剩余时间：")),
            ("resumable", self.tr("断点续传：")),
        )
        for row, (key, title) in enumerate(rows):
            caption = CaptionLabel(title, page)
            caption.setTextColor(*SUB_TEXT_COLOR)
            caption.setFixedWidth(INFO_LABEL_WIDTH)
            value = BodyLabel(page)
            # 参考图里标签和值同一字号，BodyLabel 默认 14px 会把长文件名挤到省略
            setFont(value, 12)
            value.setTextInteractionFlags(Qt.TextInteractionFlag.NoTextInteraction)
            grid.addWidget(caption, row, 0)
            grid.addWidget(value, row, 1)
            self.infoValues[key] = value
        grid.setRowStretch(len(rows), 1)
        return page

    def _buildSpeedPage(self) -> QWidget:
        page = QWidget(self)
        layout = QVBoxLayout(page)
        layout.setContentsMargins(PADDING, 4, PADDING // 2, 0)
        layout.setSpacing(SPACING)

        self.chart = SpeedChart(page)
        layout.addWidget(self.chart, 1)
        self.peakLabel = CaptionLabel(page)
        self.peakLabel.setTextColor(*SUB_TEXT_COLOR)
        layout.addWidget(self.peakLabel)
        return page

    def _buildPlanPage(self) -> QWidget:
        page = QWidget(self)
        layout = QVBoxLayout(page)
        layout.setContentsMargins(PADDING, 4, PADDING // 2, 0)
        layout.setSpacing(SPACING)

        hint = CaptionLabel(self.tr("所有任务完成后执行"), page)
        hint.setTextColor(*SUB_TEXT_COLOR)
        layout.addWidget(hint)

        self.planCombo = ComboBox(page)
        for text, action in (
            (self.tr("无"), None),
            (self.tr("关机"), PlanAction.SHUTDOWN),
            (self.tr("重启"), PlanAction.RESTART),
            (self.tr("睡眠"), PlanAction.SLEEP),
            (self.tr("打开文件"), PlanAction.OPEN_FILE),
        ):
            self.planCombo.addItem(text)
            self._planActions.append(action)
        layout.addWidget(self.planCombo)

        self.planPathRow = QWidget(page)
        pathLayout = QHBoxLayout(self.planPathRow)
        pathLayout.setContentsMargins(0, 0, 0, 0)
        pathLayout.setSpacing(SPACING)
        self.planPathEdit = LineEdit(self.planPathRow)
        self.planPathEdit.setPlaceholderText(self.tr("选择要打开的文件"))
        self.planPathEdit.setClearButtonEnabled(True)
        browseButton = ToolButton(FluentIcon.FOLDER, self.planPathRow)
        browseButton.setToolTip(self.tr("选择文件"))
        browseButton.setFixedSize(32, 32)
        pathLayout.addWidget(self.planPathEdit, 1)
        pathLayout.addWidget(browseButton)
        self.planPathRow.setVisible(False)
        layout.addWidget(self.planPathRow)
        layout.addStretch(1)
        return page

    def _initLayout(self) -> None:
        super()._initLayout()
        # 选项卡和分隔线要贴到窗口左右边缘，所以顶层不留边距，改成各区块自己留
        self.vBoxLayout.setContentsMargins(0, 0, 0, 0)
        self.vBoxLayout.setSpacing(0)
        self.headerLayout.setContentsMargins(PADDING, 1, PADDING // 2, 0)

        self.tabRow = QWidget(self)
        tabLayout = QHBoxLayout(self.tabRow)
        tabLayout.setContentsMargins(2, 0, 2, 0)
        tabLayout.setSpacing(0)
        tabLayout.addWidget(self.tabBar, 0, Qt.AlignmentFlag.AlignLeft)
        tabLayout.addStretch(1)
        self.tabLine = HLine(self)
        self.vBoxLayout.addWidget(self.tabRow)
        self.vBoxLayout.addWidget(self.tabLine)
        self.stack.setFixedHeight(CONTENT_HEIGHT)
        self.vBoxLayout.addWidget(self.stack)

        self.footer = Footer(self)
        footerLayout = QVBoxLayout(self.footer)
        footerLayout.setContentsMargins(PADDING, FOOTER_TOP, PADDING, FOOTER_BOTTOM)
        footerLayout.setSpacing(FOOTER_SPACING)
        footerLayout.addWidget(self.progressBar)
        buttons = QHBoxLayout()
        buttons.setContentsMargins(0, 0, 0, 0)
        buttons.setSpacing(SPACING)
        buttons.addWidget(self.expandButton)
        buttons.addStretch(1)
        buttons.addWidget(self.toggleButton)
        buttons.addWidget(self.cancelButton)
        footerLayout.addLayout(buttons)
        self.vBoxLayout.addWidget(self.footer)
        self.adjustSize()

    def _bind(self) -> None:
        super()._bind()
        self.minimizeButton.clicked.connect(self._onMinimizeClicked)
        self.expandButton.clicked.connect(self._onExpandClicked)
        self.toggleButton.clicked.connect(self._onToggleClicked)
        self.cancelButton.clicked.connect(lambda: self._taskService.delete(self._task, shouldDeleteFiles=True))
        self.tabBar.currentChanged.connect(self._onTabChanged)
        self.planCombo.currentIndexChanged.connect(self._onPlanChanged)
        self.planPathEdit.textChanged.connect(self._onPlanPathChanged)
        self._bindPlanBrowse()
        self._speedChanged.connect(self.refresh, owner=self)
        self._taskService.taskPaused.connect(self._onTaskPaused, owner=self)
        self._taskService.taskStarted.connect(self._onTaskStarted, owner=self)

    def _bindPlanBrowse(self) -> None:
        browseButton = self.planPathRow.findChild(ToolButton)
        if browseButton is not None:
            browseButton.clicked.connect(self._onPlanBrowse)

    def _onPlanBrowse(self) -> None:
        from PySide6.QtWidgets import QFileDialog
        path, _ = QFileDialog.getOpenFileName(self, self.tr("选择文件"))
        if path:
            self.planPathEdit.setText(path)

    def refresh(self, _speed: int | None = None) -> None:
        task = self._task
        progress, speed, received = task.currentSnapshot()
        self._updateHeader(progress)

        hasSize = task.fileSize > 0
        remaining = int((task.fileSize - received) / speed) if hasSize and speed > 0 else -1
        nameLabel = self.infoValues["name"]
        nameLabel.setText(nameLabel.fontMetrics().elidedText(
            task.name, Qt.TextElideMode.ElideMiddle, INFO_VALUE_WIDTH))
        nameLabel.setToolTip(task.name)
        self.infoValues["status"].setText(toStatusText(task))
        self.infoValues["size"].setText(toReadableSize(task.fileSize) if hasSize else self.tr("未知"))
        self.infoValues["received"].setText(
            f"{toReadableSize(received)} ({int(progress)}%)" if hasSize else toReadableSize(received))
        self.infoValues["speed"].setText(f"{toReadableSize(speed)}/s" if speed > 0 else "-")
        self.infoValues["remaining"].setText(self.tr("剩余 {0}").format(toRemainingText(remaining))
                                            if remaining >= 0 else "-")
        isResumable = any(getattr(step, "canUseRangeRequests", False) for step in task.steps)
        self.infoValues["resumable"].setText(self.tr("是") if isResumable else self.tr("否"))
        self.infoValues["resumable"].setTextColor(*(DONE_GREEN if isResumable else SUB_TEXT_COLOR))

        # 一直采样，切到速度页时才有历史曲线
        self.chart.addSample(speed)
        self.peakLabel.setText(self.tr("当前 {0}/s，峰值 {1}/s").format(
            toReadableSize(speed), toReadableSize(self.chart.peak())))

        if not self.progressBar._isIndeterminate:
            self.progressBar.setValue(progress)
        isPaused = task.status == TaskStatus.PAUSED
        self.progressBar.setPaused(isPaused)
        self.toggleButton.setText(self.tr("继续") if isPaused else self.tr("暂停"))
        self.toggleButton.setEnabled(isPaused or task.canPause)

        if sys.platform == "win32":
            from app.platform.taskbar import setWindowsProgress
            isKnown = not self.progressBar._isIndeterminate
            setWindowsProgress(int(self.winId()), task.status, progress if isKnown else None)

    def _updateHeader(self, progress: float) -> None:
        text = f"{int(progress)}% {self._task.name}"
        self.appNameLabel.setText(self.appNameLabel.fontMetrics().elidedText(
            text, Qt.TextElideMode.ElideMiddle, HEADER_TEXT_WIDTH))
        self.appNameLabel.setToolTip(text)

    def _onTabChanged(self, routeKey: str) -> None:
        self.stack.setCurrentIndex({"info": 0, "speed": 1, "plan": 2}.get(routeKey, 0))
        self.refresh()

    def _onExpandClicked(self) -> None:
        self._isExpanded = not self._isExpanded
        self.tabRow.setVisible(self._isExpanded)
        self.tabLine.setVisible(self._isExpanded)
        self.stack.setVisible(self._isExpanded)
        self.expandButton.setIcon(FluentIcon.ARROW_DOWN if self._isExpanded else FluentIcon.UP)
        self.expandButton.setToolTip(self.tr("收起详情") if self._isExpanded else self.tr("展开详情"))
        self._fitHeight()
        self.layoutChanged.emit()

    def _fitHeight(self) -> None:
        # adjustSize 在窗口已显示后不会缩回去，得让布局先重算再显式 resize
        self.layout().activate()
        self.resize(POPUP_WIDTH, self.sizeHint().height())

    def _syncPlan(self) -> None:
        plan = self._plan
        if plan is None or plan.action is None:
            return
        index = self._planActions.index(plan.action)
        self._isUpdatingPlan = True
        self.planCombo.setCurrentIndex(index)
        self.planPathEdit.setText(plan.filePath)
        self.planPathRow.setVisible(plan.action == PlanAction.OPEN_FILE)
        self._isUpdatingPlan = False
        self._ownsPlan = True

    def _onPlanChanged(self, index: int) -> None:
        if self._isUpdatingPlan:
            return
        action = self._planActions[index]
        self.planPathRow.setVisible(action == PlanAction.OPEN_FILE)
        self._fitHeight()
        self.layoutChanged.emit()
        self._applyPlan(action)

    def _onPlanPathChanged(self, _text: str) -> None:
        if not self._isUpdatingPlan and self._planActions[self.planCombo.currentIndex()] == PlanAction.OPEN_FILE:
            self._applyPlan(PlanAction.OPEN_FILE)

    def _applyPlan(self, action: PlanAction | None) -> None:
        if self._plan is None:
            return
        filePath = self.planPathEdit.text().strip()
        # 打开文件没选路径时不能落计划，否则全局任务完成会直接关机
        if action is None or (action == PlanAction.OPEN_FILE and not filePath):
            if self._ownsPlan:
                # 撤计划要静默，不能让回弹把刚选中的「打开文件」也清掉
                self._ownsPlan = False
                wasUpdating = self._isUpdatingPlan
                self._isUpdatingPlan = True
                try:
                    self._plan.clear()
                finally:
                    self._isUpdatingPlan = wasUpdating
            return
        self._ownsPlan = True
        self._plan.set(action, filePath, onCleared=self._onPlanCleared)

    def _onPlanCleared(self) -> None:
        self._ownsPlan = False
        if self._isUpdatingPlan:
            return  # 调用方正自己操作界面，别抢着复位
        try:
            self._isUpdatingPlan = True
            self.planCombo.setCurrentIndex(0)
            self.planPathEdit.clear()
            self.planPathRow.setVisible(False)
        except RuntimeError:
            pass  # 弹窗已被销毁，计划照样清掉就够
        finally:
            self._isUpdatingPlan = False

    def _onTaskPaused(self, task: Task) -> None:
        if task.taskId == self._task.taskId:
            self.refresh()

    def _onTaskStarted(self, task: Task) -> None:
        if task.taskId == self._task.taskId:
            self.chart.clear()
            self.refresh()

    def _onMinimizeClicked(self) -> None:
        self.showMinimized()

    def _onToggleClicked(self) -> None:
        if self._task.status == TaskStatus.PAUSED:
            self._taskService.start(self._task)
        else:
            self._taskService.pause(self._task)
        self.refresh()


class CheckMark(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(CHECK_MARK_SIZE, CHECK_MARK_SIZE)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        pen = QPen(DONE_GREEN[1] if isDarkTheme() else DONE_GREEN[0], 3)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        painter.setPen(pen)
        width, height = self.width(), self.height()
        painter.drawPolyline([
            QPointF(width * 0.18, height * 0.52),
            QPointF(width * 0.42, height * 0.76),
            QPointF(width * 0.84, height * 0.24),
        ])


class TaskCompletedPopup(Popup):
    hasTaskbarButton = True

    def __init__(self, task: Task):
        super().__init__()
        self._task = task
        self.hasSound = True
        self.popupId = f"task:{task.taskId}"
        self._initWidget()
        self._initLayout()
        self._bind()

    def _initWidget(self) -> None:
        self.setWindowIcon(QFileIconProvider().icon(QFileInfo(self._task.outputPath)))
        super()._initWidget()
        self.setWindowTitle(self._task.name)
        if sys.platform == "win32":
            from app.config.constants import DESKTOP_ID
            from app.platform.taskbar import setWindowAppId
            setWindowAppId(int(self.winId()), f"{DESKTOP_ID}.{self._task.taskId.replace('_', '-')}")
        self.setFixedWidth(POPUP_WIDTH)
        self.minimizeButton = MinimizeButton(self)
        self.headerButtons.insert(0, self.minimizeButton)
        self.appNameLabel.setText(self.appNameLabel.fontMetrics().elidedText(
            self._task.name, Qt.TextElideMode.ElideMiddle, HEADER_TEXT_WIDTH))
        self.appNameLabel.setToolTip(self._task.name)

        self.iconLabel = QLabel(self)
        self.iconLabel.setPixmap(self._toPixmap(
            QFileIconProvider().icon(QFileInfo(self._task.outputPath)).pixmap(FILE_ICON_SIZE, FILE_ICON_SIZE),
            FILE_ICON_SIZE))
        self.titleLabel = StrongBodyLabel(self.tr("下载已完成"), self)
        self.titleLabel.setTextColor(*DONE_GREEN)
        setFont(self.titleLabel, 20)
        self.sizeLabel = BodyLabel(self)
        self.sizeLabel.setText(toReadableSize(self._task.fileSize))
        self.nameLabel = BodyLabel(self)
        self.nameLabel.setText(self.nameLabel.fontMetrics().elidedText(
            self._task.name, Qt.TextElideMode.ElideMiddle,
            POPUP_WIDTH - 2 * PADDING - FILE_ICON_SIZE - ICON_SPACING))
        self.nameLabel.setToolTip(self._task.name)

        self.openButton = FooterButton(None, self, text=self.tr("打开"))
        self.revealButton = FooterButton(None, self, text=self.tr("打开文件夹"))
        self.dragButton = FooterButton(FluentIcon.MOVE, self, isIconOnly=True)
        self.dragButton.setToolTip(self.tr("拖拽文件"))
        self.closeButton2 = FooterButton(None, self, text=self.tr("关闭"))

    def _initLayout(self) -> None:
        super()._initLayout()
        self.vBoxLayout.setContentsMargins(0, 0, 0, 0)
        self.vBoxLayout.setSpacing(0)
        self.headerLayout.setContentsMargins(PADDING, 1, PADDING // 2, 0)

        body = QWidget(self)
        grid = QGridLayout(body)
        grid.setContentsMargins(PADDING, 8, PADDING, 20)
        grid.setHorizontalSpacing(ICON_SPACING)
        grid.setVerticalSpacing(2)
        grid.setColumnStretch(1, 1)

        titleRow = QHBoxLayout()
        titleRow.setContentsMargins(0, 0, 0, 0)
        titleRow.setSpacing(SPACING)
        titleRow.addWidget(CheckMark(self), 0, Qt.AlignmentFlag.AlignVCenter)
        titleRow.addWidget(self.titleLabel, 0, Qt.AlignmentFlag.AlignVCenter)
        titleRow.addStretch(1)

        grid.addWidget(self.iconLabel, 0, 0, 2, 1, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
        grid.addLayout(titleRow, 0, 1)
        grid.addWidget(self.sizeLabel, 1, 0, Qt.AlignmentFlag.AlignLeft)
        grid.addWidget(self.nameLabel, 1, 1)
        self.vBoxLayout.addWidget(body, 1)

        self.footer = Footer(self)
        footerLayout = QHBoxLayout(self.footer)
        footerLayout.setContentsMargins(PADDING, FOOTER_TOP, PADDING, FOOTER_BOTTOM)
        footerLayout.setSpacing(SPACING)
        footerLayout.addWidget(self.openButton)
        footerLayout.addWidget(self.revealButton)
        footerLayout.addWidget(self.dragButton)
        footerLayout.addStretch(1)
        footerLayout.addWidget(self.closeButton2)
        self.vBoxLayout.addWidget(self.footer)
        self.adjustSize()

    def _bind(self) -> None:
        super()._bind()
        self.minimizeButton.clicked.connect(self.showMinimized)
        self.openButton.clicked.connect(lambda: self._activate(openFile))
        self.revealButton.clicked.connect(lambda: self._activate(revealInFolder))
        self.closeButton2.clicked.connect(lambda: self.exit(isDismissed=False))
        self.dragButton.clicked.connect(lambda: startFileDrag([Path(self._task.outputPath)], self))
        self.clicked.connect(lambda: self._activate(openFile))

    def _activate(self, action) -> None:
        path = self._task.outputPath
        self.exit(isDismissed=False)
        QTimer.singleShot(0, lambda: action(path))
