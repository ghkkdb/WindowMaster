"""WindowMaster 程序入口。"""

import sys

from utils.win_api import enable_per_monitor_dpi_awareness


def main() -> int:
    """
    初始化并运行 WindowMaster。

    Returns:
        int: Qt 应用退出码。
    """
    enable_per_monitor_dpi_awareness()
    from PySide6.QtWidgets import QApplication

    from ui.main_window import MainWindow

    app = QApplication(sys.argv)
    app.setApplicationName("WindowMaster")
    window = MainWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
