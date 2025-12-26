import sys
from PyQt5.QtWidgets import (
    QApplication, QWidget, QLabel, QLineEdit, QTextEdit, QPushButton, QVBoxLayout,
    QHBoxLayout, QMessageBox, QFrame, QSizePolicy
)
from PyQt5.QtCore import QThread, pyqtSignal
from PyQt5.QtGui import QFont, QPalette, QColor
from base64 import b64encode, b64decode
from Crypto.Cipher import ChaCha20

class CryptoThread(QThread):
    result_signal = pyqtSignal(str)
    error_signal = pyqtSignal(str)

    def __init__(self, mode, text, key):
        super().__init__()
        self.mode = mode
        self.text = text
        self.key = key

    def run(self):
        try:
            bkey = (self.key.ljust(32, '0'))[:32].encode('utf-8')
            if self.mode == "encrypt":
                cipher = ChaCha20.new(key=bkey)
                nonce = cipher.nonce
                ciphertext = cipher.encrypt(self.text.encode('utf-8'))
                crypted = (b64encode(nonce + ciphertext)).hex()
                self.result_signal.emit(crypted)
            elif self.mode == "decrypt":
                raw = b64decode(bytes.fromhex(self.text))
                nonce = raw[:8]
                ciphertext = raw[8:]
                cipher = ChaCha20.new(key=bkey, nonce=nonce)
                plain = cipher.decrypt(ciphertext)
                self.result_signal.emit(plain.decode('utf-8'))
            else:
                self.error_signal.emit("未知操作类型")
        except Exception as e:
            self.error_signal.emit("解密/加密错误：" + str(e))


class CryptoWidget(QWidget):
    def __init__(self):
        super().__init__()
        self.crypto_thread = None
        self.init_ui()

    def init_ui(self):
        self.setWindowTitle("ChaCha20 对称加密/解密工具 (字符串专用)")
        self.setMinimumSize(650, 420)

        font = QFont("Microsoft YaHei", 12)
        self.setFont(font)

        palette = QPalette()
        palette.setColor(QPalette.Window, QColor("#F4F4FB"))
        self.setPalette(palette)

        layout = QVBoxLayout()
        layout.setSpacing(16)

        lbl_key = QLabel("密钥（32位，建议复杂随机）")
        self.key_input = QLineEdit()
        self.key_input.setPlaceholderText("请输入32位密钥")
        self.key_input.setEchoMode(QLineEdit.Password)
        self.key_input.setMinimumHeight(36)
        self.key_input.setFont(font)

        lbl_text = QLabel("加密输入明文 / 解密输入密文（base64-hex）")
        self.text_input = QTextEdit()
        self.text_input.setFont(font)
        self.text_input.setMinimumHeight(50)
        self.text_input.setPlaceholderText("请输入内容（明文或密文）")

        op_layout = QHBoxLayout()
        self.btn_encrypt = QPushButton("加密")
        self.btn_encrypt.setMinimumHeight(40)
        self.btn_encrypt.setFont(font)
        self.btn_decrypt = QPushButton("解密")
        self.btn_decrypt.setMinimumHeight(40)
        self.btn_decrypt.setFont(font)
        op_layout.addWidget(self.btn_encrypt)
        op_layout.addWidget(self.btn_decrypt)

        sep = QFrame()
        sep.setFrameShape(QFrame.HLine)
        sep.setFrameShadow(QFrame.Sunken)
        sep.setLineWidth(2)

        lbl_result = QLabel("结果（可复制）：")
        self.result_output = QTextEdit()
        self.result_output.setFont(font)
        self.result_output.setReadOnly(True)
        self.result_output.setMinimumHeight(70)
        self.btn_copy = QPushButton("复制结果")
        self.btn_copy.setMinimumHeight(34)
        self.btn_copy.setFont(font)
        self.btn_copy.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)

        layout.addWidget(lbl_key)
        layout.addWidget(self.key_input)
        layout.addWidget(lbl_text)
        layout.addWidget(self.text_input)
        layout.addLayout(op_layout)
        layout.addWidget(sep)
        layout.addWidget(lbl_result)
        layout.addWidget(self.result_output)
        layout.addWidget(self.btn_copy)
        self.setLayout(layout)

        self.btn_encrypt.clicked.connect(self.encrypt_data)
        self.btn_decrypt.clicked.connect(self.decrypt_data)
        self.btn_copy.clicked.connect(self.copy_result)

    def encrypt_data(self):
        self.process_crypto("encrypt")

    def decrypt_data(self):
        self.process_crypto("decrypt")

    def process_crypto(self, mode):
        text = self.text_input.toPlainText().strip()
        key = self.key_input.text().strip()
        if not text or not key:
            QMessageBox.warning(self, "输入错误", "密钥和内容都不能为空！")
            return
        if len(key) < 8:
            QMessageBox.warning(self, "弱口令", "密钥太短，建议使用32位高强度密钥！")
            return
        self.result_output.clear()
        self.crypto_thread = CryptoThread(mode, text, key)
        self.crypto_thread.result_signal.connect(self.show_result)
        self.crypto_thread.error_signal.connect(self.show_error)
        self.crypto_thread.start()

    def show_result(self, res):
        self.result_output.setPlainText(res)

    def show_error(self, err):
        QMessageBox.critical(self, "错误", err)

    def copy_result(self):
        result = self.result_output.toPlainText()
        if result:
            QApplication.clipboard().setText(result)
            QMessageBox.information(self, "复制成功", "结果已复制到剪贴板！")
        else:
            QMessageBox.warning(self, "无内容", "没有可复制的内容！")


if __name__ == "__main__":
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    widget = CryptoWidget()
    widget.show()
    sys.exit(app.exec_())
