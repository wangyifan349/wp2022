# notepad_dark.py
# 轻量深色记事本，黑底红字，选中金底绿字，异步文件 IO
# 依赖: pip install PyQt5 chardet

import sys, threading
from PyQt5.QtWidgets import (QApplication, QMainWindow, QPlainTextEdit, QFileDialog,
                             QAction, QToolBar, QStatusBar, QLabel, QMessageBox, QFontDialog)
from PyQt5.QtGui import QFont, QColor, QTextCharFormat, QTextCursor, QKeySequence
from PyQt5.QtCore import Qt, pyqtSignal, QObject
import chardet

# 简单的信号桥（用于线程向主线程发送结果）
class SignalBridge(QObject):
    loaded = pyqtSignal(str, str)    # path, text
    saved = pyqtSignal(str, bool)    # path, success
    error = pyqtSignal(str)          # message

def detect_encoding(data_bytes):
    try:
        r = chardet.detect(data_bytes)
        enc = r.get('encoding') or 'utf-8'
        return enc
    except Exception:
        return 'utf-8'

def read_file_async(path, bridge):
    def job():
        try:
            with open(path, 'rb') as f:
                b = f.read()
            enc = detect_encoding(b)
            text = b.decode(enc, errors='replace')
            bridge.loaded.emit(path, text)
        except Exception as e:
            bridge.error.emit(f"打开失败: {e}")
    threading.Thread(target=job, daemon=True).start()

def write_file_async(path, text, bridge):
    def job():
        try:
            # 优先用 utf-8 保存
            with open(path, 'wb') as f:
                b = text.encode('utf-8')
                f.write(b)
            bridge.saved.emit(path, True)
        except Exception as e:
            bridge.error.emit(f"保存失败: {e}")
            bridge.saved.emit(path, False)
    threading.Thread(target=job, daemon=True).start()

def apply_styles(edit: QPlainTextEdit):
    # 基本风格
    edit.setStyleSheet("""
        QPlainTextEdit {
            background: #0b0b0b;
            color: #ff3b3b;
            selection-background-color: #b8860b;
            selection-color: #00c400;
            padding: 6px;
            border: 1px solid #222;
            font-family: "Consolas", "Menlo", "Monaco", "Courier New", monospace;
            font-size: 13px;
        }
    """)
    # 光标与行高微调
    fm = edit.fontMetrics()
    edit.setTabStopDistance(4 * fm.horizontalAdvance(' '))

class Notepad(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("记事本（深色）")
        self.resize(900, 640)
        self.path = None
        self.modified = False

        # 中心编辑器（使用 QPlainTextEdit 性能更好）
        self.editor = QPlainTextEdit()
        self.editor.setLineWrapMode(QPlainTextEdit.NoWrap)
        font = QFont("Consolas", 13)
        self.editor.setFont(font)
        apply_styles(self.editor)
        self.setCentralWidget(self.editor)

        # 信号桥与线程回调连接
        self.bridge = SignalBridge()
        self.bridge.loaded.connect(self.on_loaded)
        self.bridge.saved.connect(self.on_saved)
        self.bridge.error.connect(self.on_error)

        # 最简工具栏与菜单
        tb = QToolBar("工具")
        self.addToolBar(tb)
        new_act = QAction("新建", self); new_act.setShortcut(QKeySequence.New); new_act.triggered.connect(self.new_file)
        open_act = QAction("打开", self); open_act.setShortcut(QKeySequence.Open); open_act.triggered.connect(self.open_file)
        save_act = QAction("保存", self); save_act.setShortcut(QKeySequence.Save); save_act.triggered.connect(self.save_file)
        saveas_act = QAction("另存为", self); saveas_act.triggered.connect(self.save_as)
        font_act = QAction("字体", self); font_act.triggered.connect(self.choose_font)
        tb.addAction(new_act); tb.addAction(open_act); tb.addAction(save_act); tb.addAction(saveas_act); tb.addAction(font_act)

        # 状态栏
        sb = QStatusBar()
        self.setStatusBar(sb)
        self.pos_label = QLabel("Ln 1, Col 1")
        sb.addPermanentWidget(self.pos_label)

        # 连接编辑器信号
        self.editor.textChanged.connect(self.on_text_changed)
        self.editor.cursorPositionChanged.connect(self.update_cursor_pos)

        # 设置更明显的选中样式（兼容部分平台）
        fmt = QTextCharFormat()
        fmt.setForeground(QColor("#00c400"))
        fmt.setBackground(QColor("#b8860b"))
        # 不直接应用，使用 stylesheet 已覆盖大部分

    # 文件操作（异步）
    def open_file(self):
        if self.maybe_save() is False:
            return
        path, _ = QFileDialog.getOpenFileName(self, "打开文件", "", "所有文件 (*);;文本文件 (*.txt)")
        if not path:
            return
        self.statusBar().showMessage("正在打开...")
        read_file_async(path, self.bridge)

    def on_loaded(self, path, text):
        self.path = path
        self.editor.setPlainText(text)
        self.modified = False
        self.update_title()
        self.statusBar().showMessage(f"已打开: {path}", 4000)

    def save_file(self):
        if not self.path:
            return self.save_as()
        self.statusBar().showMessage("正在保存...")
        write_file_async(self.path, self.editor.toPlainText(), self.bridge)

    def save_as(self):
        path, _ = QFileDialog.getSaveFileName(self, "另存为", "", "文本文件 (*.txt);;所有文件 (*)")
        if not path:
            return False
        self.path = path
        self.statusBar().showMessage("正在保存...")
        write_file_async(self.path, self.editor.toPlainText(), self.bridge)
        return True

    def on_saved(self, path, ok):
        if ok:
            self.modified = False
            self.update_title()
            self.statusBar().showMessage(f"已保存: {path}", 3000)
        else:
            self.statusBar().showMessage("保存失败", 3000)

    def on_error(self, msg):
        QMessageBox.critical(self, "错误", msg)
        self.statusBar().clearMessage()

    # 其它 UI 行为
    def new_file(self):
        if self.maybe_save() is False:
            return
        self.editor.clear()
        self.path = None
        self.modified = False
        self.update_title()

    def maybe_save(self):
        if not self.modified:
            return True
        res = QMessageBox.warning(self, "保存更改", "文档已更改，是否保存？", QMessageBox.Save | QMessageBox.Discard | QMessageBox.Cancel)
        if res == QMessageBox.Save:
            return self.save_file()
        if res == QMessageBox.Discard:
            return True
        return False

    def on_text_changed(self):
        self.modified = True
        self.update_title()

    def update_title(self):
        name = self.path if self.path else "未命名"
        mark = "*" if self.modified else ""
        self.setWindowTitle(f"{mark}{name} - 记事本（深色）")

    def update_cursor_pos(self):
        tc = self.editor.textCursor()
        line = tc.blockNumber() + 1
        col = tc.columnNumber() + 1
        self.pos_label.setText(f"Ln {line}, Col {col}")

    def choose_font(self):
        ok, font = QFontDialog.getFont(self.editor.font(), self, "选择字体")
        if ok:
            self.editor.setFont(font)

    def closeEvent(self, event):
        if self.maybe_save() is False:
            event.ignore()
        else:
            event.accept()

def main():
    app = QApplication(sys.argv)
    # 更现代的窗口风格（尝试）
    app.setStyle("Fusion")
    w = Notepad()
    w.show()
    sys.exit(app.exec_())

if __name__ == "__main__":
    main()
