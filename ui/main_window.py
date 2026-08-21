"""WindowMaster 主窗口界面。"""

import ctypes
from ctypes import wintypes
from typing import Any

from PySide6.QtCore import QTimer, Qt
from PySide6.QtGui import QAction, QCloseEvent, QKeySequence
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QKeySequenceEdit,
    QMainWindow,
    QMessageBox,
    QMenu,
    QPushButton,
    QSlider,
    QStyle,
    QSystemTrayIcon,
    QTabBar,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from core.application_service import ApplicationService
from core.hotkeys import WM_HOTKEY, unregister_hotkeys
from core.models import (
    HotkeySetting,
    MonitorSignature,
    OperationResult,
    RestorePlan,
    WindowInfo,
)


WM_DISPLAYCHANGE = 0x007E


class MainWindow(QMainWindow):
    """提供窗口管理和布局操作的主界面。"""

    def __init__(self) -> None:
        """初始化界面、刷新定时器和全局快捷键。"""
        super().__init__()
        self.service = ApplicationService()
        self.windows: list[WindowInfo] = []
        self.hotkey_hwnd = 0
        self._quitting = False
        self._cleanup_finished = False
        self._tray_notice_shown = False
        self._tray_enabled = False
        self._display_signature: MonitorSignature = ()
        self._pending_display_profiles: tuple[str, ...] = ()
        self.tray_icon: QSystemTrayIcon | None = None
        self.tray_profile_menu: QMenu | None = None
        self.setWindowTitle("WindowMaster")
        self.resize(860, 620)
        self._build_ui()
        self.opacity_timer = QTimer(self)
        self.opacity_timer.setSingleShot(True)
        self.opacity_timer.setInterval(16)
        self.opacity_timer.timeout.connect(self.preview_opacity)
        self._connect_signals()
        self._setup_tray()
        self._setup_display_change_detection()
        self.refresh_windows()
        self.refresh_profiles()
        self.refresh_timer = QTimer(self)
        self.refresh_timer.timeout.connect(self.refresh_windows)
        self.refresh_timer.start(2000)
        self.hotkey_hwnd = int(self.winId())
        hotkey_result = self.service.register_configured_hotkeys(self.hotkey_hwnd)
        if not hotkey_result.success:
            self.show_status(hotkey_result.message, error=True)
        application = QApplication.instance()
        if application is not None:
            application.aboutToQuit.connect(self._cleanup)

    def _build_ui(self) -> None:
        """创建主窗口中的控件和布局。"""
        root = QWidget(self)
        layout = QVBoxLayout(root)

        self.navigation_tabs = QTabBar()
        self.navigation_tabs.addTab("窗口管理")
        self.navigation_tabs.addTab("快捷键设置")
        self.navigation_tabs.addTab("设置")
        self.navigation_tabs.setExpanding(False)
        layout.addWidget(self.navigation_tabs)

        toolbar = QHBoxLayout()
        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText("按程序名或窗口标题搜索")
        self.refresh_button = QPushButton("刷新")
        toolbar.addWidget(QLabel("窗口："))
        toolbar.addWidget(self.search_edit, 1)
        toolbar.addWidget(self.refresh_button)
        layout.addLayout(toolbar)

        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(["程序", "标题", "PID", "置顶", "显示器"])
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.horizontalHeader().setSectionResizeMode(1, self.table.horizontalHeader().ResizeMode.Stretch)
        layout.addWidget(self.table, 1)

        operations = QGroupBox("窗口操作")
        operation_layout = QGridLayout(operations)
        self.opacity_label = QLabel("不透明度：100%")
        self.opacity_slider = QSlider(Qt.Orientation.Horizontal)
        self.opacity_slider.setRange(30, 100)
        self.opacity_slider.setValue(100)
        self.opacity_slider.setTracking(True)
        self.topmost_button = QPushButton("切换置顶")
        self.left_button = QPushButton("左半屏")
        self.right_button = QPushButton("右半屏")
        self.maximize_button = QPushButton("最大化")
        self.minimize_all_button = QPushButton("最小化全部程序")
        operation_layout.addWidget(self.opacity_label, 0, 0)
        operation_layout.addWidget(self.opacity_slider, 0, 1, 1, 3)
        operation_layout.addWidget(self.topmost_button, 1, 0)
        operation_layout.addWidget(self.left_button, 1, 1)
        operation_layout.addWidget(self.right_button, 1, 2)
        operation_layout.addWidget(self.maximize_button, 1, 3)
        operation_layout.addWidget(self.minimize_all_button, 2, 0, 1, 4)
        layout.addWidget(operations)

        profiles = QGroupBox("命名布局")
        profile_layout = QHBoxLayout(profiles)
        self.profile_combo = QComboBox()
        self.profile_combo.setEditable(True)
        self.profile_combo.setPlaceholderText("输入或选择布局名称")
        self.save_profile_button = QPushButton("保存/覆盖")
        self.restore_profile_button = QPushButton("恢复")
        self.delete_profile_button = QPushButton("删除")
        profile_layout.addWidget(self.profile_combo, 1)
        profile_layout.addWidget(self.save_profile_button)
        profile_layout.addWidget(self.restore_profile_button)
        profile_layout.addWidget(self.delete_profile_button)
        layout.addWidget(profiles)

        self.setCentralWidget(root)
        self.statusBar().showMessage("就绪")
        self._set_operation_enabled(False)

    def _connect_signals(self) -> None:
        """连接全部用户交互信号。"""
        self.refresh_button.clicked.connect(self.refresh_windows)
        self.search_edit.textChanged.connect(self.apply_filter)
        self.table.itemSelectionChanged.connect(self._selection_changed)
        self.table.cellDoubleClicked.connect(self.activate_row_window)
        self.opacity_slider.valueChanged.connect(self._opacity_value_changed)
        self.opacity_slider.sliderReleased.connect(self.commit_opacity)
        self.topmost_button.clicked.connect(self.toggle_selected_topmost)
        self.left_button.clicked.connect(lambda: self.split_selected("left"))
        self.right_button.clicked.connect(lambda: self.split_selected("right"))
        self.maximize_button.clicked.connect(self.maximize_selected)
        self.save_profile_button.clicked.connect(self.save_current_profile)
        self.restore_profile_button.clicked.connect(self.restore_current_profile)
        self.delete_profile_button.clicked.connect(self.delete_current_profile)
        self.minimize_all_button.clicked.connect(self.minimize_all_programs)
        self.navigation_tabs.currentChanged.connect(self._navigation_tab_changed)

    def _navigation_tab_changed(self, index: int) -> None:
        """
        将顶部标签作为窗口管理、快捷键设置和常规设置入口。

        Args:
            index (int): 当前标签索引。
        """
        if index == 0:
            return
        try:
            if index == 1:
                self.open_hotkey_settings()
            elif index == 2:
                self.open_settings()
        finally:
            self.navigation_tabs.blockSignals(True)
            self.navigation_tabs.setCurrentIndex(0)
            self.navigation_tabs.blockSignals(False)

    def _setup_tray(self) -> None:
        """创建系统托盘图标、菜单并应用已保存的偏好设置。"""
        if QSystemTrayIcon.isSystemTrayAvailable():
            icon = self.windowIcon()
            if icon.isNull():
                icon = self.style().standardIcon(QStyle.StandardPixmap.SP_ComputerIcon)
                self.setWindowIcon(icon)
            self.tray_icon = QSystemTrayIcon(icon, self)
            self.tray_icon.setToolTip("WindowMaster")
            menu = QMenu(self)
            show_action = QAction("显示主窗口", self)
            show_action.triggered.connect(self.show_from_tray)
            refresh_action = QAction("刷新窗口列表", self)
            refresh_action.triggered.connect(self.refresh_from_tray)
            settings_action = QAction("设置", self)
            settings_action.triggered.connect(self.open_settings)
            self.tray_profile_menu = QMenu("恢复布局", menu)
            self.tray_profile_menu.aboutToShow.connect(self._refresh_tray_profiles)
            quit_action = QAction("退出 WindowMaster", self)
            quit_action.triggered.connect(self.quit_application)
            menu.addAction(show_action)
            menu.addAction(refresh_action)
            menu.addAction(settings_action)
            menu.addSeparator()
            menu.addMenu(self.tray_profile_menu)
            menu.addSeparator()
            menu.addAction(quit_action)
            self.tray_icon.setContextMenu(menu)
            self.tray_icon.activated.connect(self._tray_activated)
            self.tray_icon.messageClicked.connect(self._tray_message_clicked)

        result = self.service.get_tray_enabled()
        if not result.success:
            self.show_status(result.message, error=True)
            return
        enabled = bool(result.payload) and self.tray_icon is not None
        if result.payload and self.tray_icon is None:
            self.service.set_tray_enabled(False)
            return
        self._apply_tray_enabled(enabled)

    def _setup_display_change_detection(self) -> None:
        """初始化显示器拓扑快照和变化防抖定时器。"""
        self.display_change_timer = QTimer(self)
        self.display_change_timer.setSingleShot(True)
        self.display_change_timer.timeout.connect(self._handle_stable_display_change)
        result = self.service.get_display_change_state()
        if not result.success or result.payload is None:
            self.display_change_timer.setInterval(1200)
            self.show_status(result.message, error=True)
            return
        self._display_signature = result.payload.monitor_signature
        self.display_change_timer.setInterval(result.payload.debounce_ms)

    def _schedule_display_change_check(self) -> None:
        """重新启动防抖计时，等待显示器配置稳定。"""
        self.display_change_timer.start()

    def _handle_stable_display_change(self) -> None:
        """显示器配置稳定后更新拓扑，并通过托盘给出恢复提示。"""
        result = self.service.get_display_change_state()
        if not result.success or result.payload is None:
            self.show_status(result.message, error=True)
            return
        state = result.payload
        self.display_change_timer.setInterval(state.debounce_ms)
        if state.monitor_signature == self._display_signature:
            return
        self._display_signature = state.monitor_signature
        self._pending_display_profiles = state.matching_profiles

        if len(state.matching_profiles) == 1:
            name = state.matching_profiles[0]
            message = f"发现匹配布局“{name}”，点击预览并恢复。"
        elif state.matching_profiles:
            message = (
                f"发现 {len(state.matching_profiles)} 个匹配布局，"
                "点击打开 WindowMaster 进行选择。"
            )
        else:
            message = "没有找到匹配布局，点击打开 WindowMaster。"

        self.show_status(f"显示器配置已变化：{message}")
        if (
            self.tray_icon is not None
            and self._tray_enabled
            and self.tray_icon.isVisible()
        ):
            self.tray_icon.showMessage(
                "检测到显示器变化",
                message,
                QSystemTrayIcon.MessageIcon.Information,
                6000,
            )

    def _tray_message_clicked(self) -> None:
        """响应托盘通知点击，打开选择界面或进入唯一布局的恢复确认。"""
        profiles = self._pending_display_profiles
        self._pending_display_profiles = ()
        if len(profiles) == 1:
            self.restore_profile_from_tray(profiles[0])
            return
        if not self.isVisible():
            self.show_from_tray()
        selected = profiles[0] if profiles else ""
        self.refresh_profiles(selected)
        if profiles:
            self.show_status("请选择要恢复的匹配布局，然后点击“恢复”")

    def _apply_tray_enabled(self, enabled: bool) -> None:
        """
        将系统托盘启用状态应用到 Qt 生命周期和托盘图标。

        Args:
            enabled (bool): 是否启用系统托盘。
        """
        application = QApplication.instance()
        if application is not None:
            application.setQuitOnLastWindowClosed(not enabled)
        self._tray_enabled = enabled
        if self.tray_icon is not None:
            self.tray_icon.setVisible(enabled)

    def _set_tray_enabled(self, enabled: bool) -> bool:
        """
        保存并应用系统托盘设置。

        Args:
            enabled (bool): 是否启用系统托盘。

        Returns:
            bool: 设置成功时返回 True。
        """
        if enabled and self.tray_icon is None:
            self.show_status("当前系统不支持系统托盘", error=True)
            return False
        result = self.service.set_tray_enabled(enabled)
        if not result.success:
            self.show_status(result.message, error=True)
            return False
        self._apply_tray_enabled(enabled)
        self.show_status(result.message)
        return True

    def open_settings(self) -> None:
        """打开设置对话框，并在用户确认后保存系统托盘开关。"""
        if not self.isVisible():
            self.show_from_tray()
        dialog = QDialog(self)
        dialog.setWindowTitle("WindowMaster 设置")
        dialog.setModal(True)
        dialog.resize(380, 140)
        layout = QVBoxLayout(dialog)
        tray_checkbox = QCheckBox("关闭时隐藏到系统托盘", dialog)
        tray_checkbox.setChecked(self._tray_enabled)
        if self.tray_icon is None:
            tray_checkbox.setChecked(False)
            tray_checkbox.setEnabled(False)
            tray_checkbox.setToolTip("当前系统不支持系统托盘")
        layout.addWidget(tray_checkbox)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel,
            parent=dialog,
        )
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        enabled = tray_checkbox.isChecked()
        if enabled != self._tray_enabled:
            self._set_tray_enabled(enabled)

    def open_hotkey_settings(self) -> None:
        """打开快捷键设置窗口，并在校验成功后立即重新注册快捷键。"""
        result = self.service.get_hotkey_settings()
        if not result.success or result.payload is None:
            self.show_status(result.message, error=True)
            return
        dialog = QDialog(self)
        dialog.setWindowTitle("快捷键设置")
        dialog.setModal(True)
        dialog.resize(520, 260)
        layout = QVBoxLayout(dialog)
        form = QFormLayout()
        editors: dict[str, tuple[QCheckBox, QKeySequenceEdit]] = {}
        for setting in result.payload:
            row = QWidget(dialog)
            row_layout = QHBoxLayout(row)
            row_layout.setContentsMargins(0, 0, 0, 0)
            enabled_checkbox = QCheckBox("启用", row)
            enabled_checkbox.setChecked(setting.enabled)
            editor = QKeySequenceEdit(row)
            editor.setMaximumSequenceLength(1)
            editor.setKeySequence(QKeySequence(setting.shortcut))
            editor.setEnabled(setting.enabled)
            enabled_checkbox.toggled.connect(editor.setEnabled)
            row_layout.addWidget(enabled_checkbox)
            row_layout.addWidget(editor, 1)
            form.addRow(f"{setting.label}：", row)
            editors[setting.action] = (enabled_checkbox, editor)
        layout.addLayout(form)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save
            | QDialogButtonBox.StandardButton.Cancel,
            parent=dialog,
        )
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)

        while dialog.exec() == QDialog.DialogCode.Accepted:
            settings = tuple(
                HotkeySetting(
                    action=setting.action,
                    label=setting.label,
                    shortcut=editors[setting.action][1]
                    .keySequence()
                    .toString(QKeySequence.SequenceFormat.PortableText),
                    enabled=editors[setting.action][0].isChecked(),
                )
                for setting in result.payload
            )
            update_result = self.service.update_hotkey_settings(
                self.hotkey_hwnd, settings
            )
            if update_result.success:
                self.show_status(update_result.message)
                return
            QMessageBox.warning(dialog, "快捷键设置无效", update_result.message)

    def _tray_activated(self, reason: QSystemTrayIcon.ActivationReason) -> None:
        """
        双击托盘图标时显示主窗口。

        Args:
            reason (QSystemTrayIcon.ActivationReason): 托盘激活原因。
        """
        if reason == QSystemTrayIcon.ActivationReason.DoubleClick:
            self.show_from_tray()

    def show_from_tray(self) -> None:
        """从系统托盘恢复并激活主窗口。"""
        self._pending_display_profiles = ()
        self.showNormal()
        self.raise_()
        self.activateWindow()

    def refresh_from_tray(self) -> None:
        """从系统托盘刷新窗口列表和布局列表。"""
        self.refresh_windows()
        self.refresh_profiles(self.profile_combo.currentText().strip())
        self.show_status("窗口和布局列表已刷新")

    def _refresh_tray_profiles(self) -> None:
        """在托盘菜单打开前重建可恢复布局列表。"""
        if self.tray_profile_menu is None:
            return
        self.tray_profile_menu.clear()
        result = self.service.get_profile_names()
        if not result.success or not result.payload:
            empty_action = self.tray_profile_menu.addAction(
                "读取失败" if not result.success else "暂无布局"
            )
            empty_action.setEnabled(False)
            if not result.success:
                self.show_status(result.message, error=True)
            return
        for name in result.payload:
            action = self.tray_profile_menu.addAction(name)
            action.triggered.connect(
                lambda checked=False, profile_name=name: self.restore_profile_from_tray(
                    profile_name
                )
            )

    def restore_profile_from_tray(self, name: str) -> None:
        """
        从托盘选择布局后显示主窗口并进入标准恢复确认流程。

        Args:
            name (str): 要恢复的布局名称。
        """
        self.show_from_tray()
        self.refresh_profiles(name)
        self.profile_combo.setCurrentText(name)
        self.restore_current_profile()

    def quit_application(self) -> None:
        """从托盘菜单明确退出应用。"""
        self._quitting = True
        self._cleanup()
        application = QApplication.instance()
        if application is not None:
            application.quit()

    def _cleanup(self) -> None:
        """隐藏托盘图标并注销全局快捷键，确保清理只执行一次。"""
        if self._cleanup_finished:
            return
        self._cleanup_finished = True
        if self.tray_icon is not None:
            self.tray_icon.hide()
        if self.hotkey_hwnd:
            unregister_hotkeys(self.hotkey_hwnd)
            self.hotkey_hwnd = 0

    def _set_operation_enabled(self, enabled: bool) -> None:
        """
        启用或禁用需要选中窗口的控件。

        Args:
            enabled (bool): 是否启用控件。
        """
        for widget in (
            self.opacity_slider,
            self.topmost_button,
            self.left_button,
            self.right_button,
            self.maximize_button,
        ):
            widget.setEnabled(enabled)

    def _selection_changed(self) -> None:
        """根据当前表格选择更新操作控件状态。"""
        self._set_operation_enabled(self.selected_hwnd() is not None)

    def _opacity_value_changed(self, value: int) -> None:
        """
        更新透明度数值标签。

        Args:
            value (int): 当前滑块百分比。
        """
        self.opacity_label.setText(f"不透明度：{value}%")
        if self.selected_hwnd() is not None:
            self.opacity_timer.start()

    def selected_hwnd(self) -> int | None:
        """
        获取表格中选中的窗口句柄。

        Returns:
            int | None: 未选择时返回 None。
        """
        row = self.table.currentRow()
        if row < 0:
            return None
        item = self.table.item(row, 0)
        return int(item.data(Qt.ItemDataRole.UserRole)) if item is not None else None

    def activate_row_window(self, row: int, column: int) -> None:
        """
        双击窗口列表行时激活并闪烁对应窗口。

        Args:
            row (int): 双击的表格行号。
            column (int): 双击的表格列号。
        """
        del column
        item = self.table.item(row, 0)
        if item is None:
            return
        hwnd = int(item.data(Qt.ItemDataRole.UserRole))
        self._show_service_result(self.service.activate_window(hwnd))

    def refresh_windows(self) -> None:
        """重新枚举窗口，并尽可能保留当前选择。"""
        if self.opacity_slider.isSliderDown():
            return
        selected = self.selected_hwnd()
        result = self.service.refresh_windows()
        if not result.success or result.payload is None:
            self.show_status(result.message, error=True)
            return
        self.windows = list(result.payload)
        self.table.setRowCount(len(self.windows))
        selected_row = -1
        for row, window in enumerate(self.windows):
            executable = QTableWidgetItem(window.executable)
            executable.setData(Qt.ItemDataRole.UserRole, window.hwnd)
            values = [
                executable,
                QTableWidgetItem(window.title),
                QTableWidgetItem(str(window.pid)),
                QTableWidgetItem("是" if window.topmost else "否"),
                QTableWidgetItem(window.monitor.device),
            ]
            for column, item in enumerate(values):
                self.table.setItem(row, column, item)
            if window.hwnd == selected:
                selected_row = row
        if selected_row >= 0:
            self.table.selectRow(selected_row)
        self.apply_filter(self.search_edit.text())
        self._selection_changed()

    def apply_filter(self, text: str) -> None:
        """
        按进程名和标题过滤窗口表格。

        Args:
            text (str): 用户输入的搜索文本。
        """
        needle = text.strip().casefold()
        for row, window in enumerate(self.windows):
            haystack = f"{window.executable} {window.title}".casefold()
            self.table.setRowHidden(row, bool(needle) and needle not in haystack)

    def _show_service_result(
        self,
        result: OperationResult[Any],
        show_success: bool = True,
    ) -> None:
        """
        将应用服务结果映射到状态栏和窗口刷新。

        Args:
            result (OperationResult[Any]): 应用服务返回的统一结果。
            show_success (bool): 是否显示成功消息。
        """
        if not result.success:
            self.show_status(result.message, error=True)
            return
        if show_success and result.message:
            self.show_status(result.message)
        if result.refresh_required:
            self.refresh_windows()

    def preview_opacity(self) -> None:
        """在拖动滑块时实时预览选中窗口的透明度。"""
        self._apply_opacity(show_result=False)

    def commit_opacity(self) -> None:
        """滑动结束后应用最终透明度并显示结果。"""
        self.opacity_timer.stop()
        self._apply_opacity(show_result=True)

    def _apply_opacity(self, show_result: bool) -> None:
        """
        将当前透明度应用到选中窗口。

        Args:
            show_result (bool): 是否在状态栏显示最终结果。
        """
        hwnd = self.selected_hwnd()
        if hwnd is None:
            return
        value = self.opacity_slider.value()
        result = self.service.set_window_opacity(hwnd, value)
        if not result.success:
            self.opacity_timer.stop()
        self._show_service_result(result, show_success=show_result)

    def toggle_selected_topmost(self) -> None:
        """切换选中窗口的置顶状态。"""
        hwnd = self.selected_hwnd()
        if hwnd is None:
            return
        self._show_service_result(self.service.toggle_window_topmost(hwnd))

    def split_selected(self, side: str) -> None:
        """
        将选中窗口移动到指定半屏。

        Args:
            side (str): `left` 或 `right`。
        """
        hwnd = self.selected_hwnd()
        if hwnd is None:
            return
        self._show_service_result(self.service.split_window(hwnd, side))

    def maximize_selected(self) -> None:
        """最大化选中的窗口。"""
        hwnd = self.selected_hwnd()
        if hwnd is None:
            return
        self._show_service_result(self.service.maximize_window(hwnd))

    def minimize_all_programs(self) -> None:
        """最小化当前全部可管理程序窗口。"""
        self._show_service_result(
            self.service.minimize_all_programs(self.hotkey_hwnd)
        )

    def refresh_profiles(self, selected: str = "") -> None:
        """
        重新加载布局名称。

        Args:
            selected (str): 刷新后需要选中的布局名称。
        """
        result = self.service.get_profile_names()
        if not result.success or result.payload is None:
            self.show_status(result.message, error=True)
            return
        names = result.payload
        self.profile_combo.clear()
        self.profile_combo.addItems(names)
        if selected:
            self.profile_combo.setCurrentText(selected)
        self.restore_profile_button.setEnabled(bool(names))
        self.delete_profile_button.setEnabled(bool(names))

    def save_current_profile(self) -> None:
        """保存当前全部可管理窗口为命名布局。"""
        name = self.profile_combo.currentText().strip()
        if not name:
            self.show_status("请输入布局名称", error=True)
            return
        exists_result = self.service.profile_exists(name)
        if not exists_result.success:
            self.show_status(exists_result.message, error=True)
            return
        if exists_result.payload:
            answer = QMessageBox.question(self, "覆盖布局", f"确定覆盖布局“{name}”吗？")
            if answer != QMessageBox.StandardButton.Yes:
                return
        result = self.service.save_current_profile(name)
        if result.success:
            self.refresh_profiles(name)
        self._show_service_result(result)

    def restore_current_profile(self) -> None:
        """恢复当前选择的命名布局。"""
        name = self.profile_combo.currentText().strip()
        prepare_result = self.service.prepare_restore(name)
        if not prepare_result.success or prepare_result.payload is None:
            self.show_status(prepare_result.message, error=True)
            return
        plan = prepare_result.payload
        preview = self._restore_plan_preview_text(plan)
        if plan.ready_count == 0:
            QMessageBox.warning(self, "无法恢复布局", preview)
            self.show_status("布局中没有可执行项", error=True)
            return
        if plan.preview_required:
            answer = QMessageBox.question(
                self,
                "确认恢复布局",
                f"{preview}\n\n是否执行可恢复的窗口操作？",
            )
            if answer != QMessageBox.StandardButton.Yes:
                return
        execute_result = self.service.execute_restore(plan)
        if execute_result.success and execute_result.payload is not None:
            summary = execute_result.payload
            self.show_status(
                execute_result.message,
                error=summary.failed > 0 or summary.conflicts > 0,
            )
            if execute_result.refresh_required:
                self.refresh_windows()
            return
        self._show_service_result(execute_result)

    def _restore_plan_preview_text(self, plan: RestorePlan) -> str:
        """
        生成人类可读的恢复计划摘要。

        Args:
            plan (RestorePlan): 待展示的恢复计划。

        Returns:
            str: 包含数量和冲突原因的预览文本。
        """
        lines = [
            f"布局：{plan.profile_name}",
            f"可执行：{plan.ready_count}",
            f"跳过：{plan.skipped_count}",
            f"冲突：{plan.conflict_count}",
        ]
        problems = [
            f"- {item.executable}：{item.reason}"
            for item in plan.items
            if item.status in {"skipped", "conflict"}
        ]
        if problems:
            lines.extend(["", "需要注意：", *problems[:5]])
            if len(problems) > 5:
                lines.append(f"- 另有 {len(problems) - 5} 项未显示")
        return "\n".join(lines)

    def delete_current_profile(self) -> None:
        """确认后删除当前选择的命名布局。"""
        name = self.profile_combo.currentText().strip()
        if not name:
            return
        answer = QMessageBox.question(self, "删除布局", f"确定删除布局“{name}”吗？")
        if answer != QMessageBox.StandardButton.Yes:
            return
        result = self.service.delete_profile(name)
        if result.success:
            self.refresh_profiles()
        self._show_service_result(result)

    def _handle_hotkey(self, hotkey_id: int) -> None:
        """
        对当前前台窗口执行全局快捷键操作。

        Args:
            hotkey_id (int): RegisterHotKey 使用的快捷键 ID。
        """
        result = self.service.handle_hotkey(
            hotkey_id,
            self.hotkey_hwnd,
            self.selected_hwnd(),
        )
        self._show_service_result(result)

    def nativeEvent(self, event_type: bytes, message: int) -> tuple[bool, int]:
        """
        接收 Windows 原生快捷键消息。

        Args:
            event_type (bytes): Qt 原生事件类型。
            message (int): Windows MSG 结构地址。

        Returns:
            tuple[bool, int]: 是否处理事件及返回值。
        """
        msg = wintypes.MSG.from_address(int(message))
        if msg.message == WM_HOTKEY:
            self._handle_hotkey(int(msg.wParam))
            return True, 0
        if msg.message == WM_DISPLAYCHANGE:
            self._schedule_display_change_check()
        return super().nativeEvent(event_type, message)

    def show_status(self, message: str, error: bool = False) -> None:
        """
        在状态栏显示操作结果。

        Args:
            message (str): 状态文本。
            error (bool): 是否按错误状态显示。
        """
        color = "#b00020" if error else ""
        self.statusBar().setStyleSheet(f"color: {color};")
        self.statusBar().showMessage(message, 8000)

    def closeEvent(self, event: QCloseEvent) -> None:
        """
        启用托盘时隐藏窗口，否则清理资源并退出。

        Args:
            event (QCloseEvent): Qt 关闭事件。
        """
        if (
            not self._quitting
            and self._tray_enabled
            and self.tray_icon is not None
            and self.tray_icon.isVisible()
        ):
            event.ignore()
            self.hide()
            if not self._tray_notice_shown:
                self._pending_display_profiles = ()
                self.tray_icon.showMessage(
                    "WindowMaster 仍在运行",
                    "双击托盘图标可重新打开，右键菜单可退出。",
                    QSystemTrayIcon.MessageIcon.Information,
                    3000,
                )
                self._tray_notice_shown = True
            return
        self._cleanup()
        event.accept()
