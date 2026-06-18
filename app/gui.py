import sys
import os
# 确保项目根目录在 python 搜索路径中，防止 ModuleNotFoundError
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import threading
import time
import logging
import uvicorn

# 异步启动 uvicorn 服务的线程
def start_backend():
    # 强制在子线程中运行 load_config 并启动服务器
    from app.core.config import load_config
    load_config()
    uvicorn.run("app.main:app", host="127.0.0.1", port=8000, log_level="warning")

def wait_for_server(host: str, port: int, timeout: float = 10.0) -> bool:
    import socket
    start_time = time.time()
    while time.time() - start_time < timeout:
        try:
            with socket.create_connection((host, port), timeout=1.0):
                return True
        except (socket.timeout, ConnectionRefusedError, OSError):
            time.sleep(0.2)
    return False

def main():
    logging.basicConfig(level=logging.INFO)
    logger = logging.getLogger("GUIApp")

    # 1. 启动 FastAPI 后端服务
    backend_thread = threading.Thread(target=start_backend)
    backend_thread.daemon = True
    backend_thread.start()
    logger.info("FastAPI backend thread started.")

    # 动态探测后端端口是否成功打开，最长等待 10 秒
    logger.info("Waiting for FastAPI server to bind to port 8000...")
    if not wait_for_server("127.0.0.1", 8000, 10.0):
        logger.error("FastAPI backend server failed to start or port 8000 is occupied!")

    # 2. 启动 WebView 桌面客户端
    # 我们优先使用轻量、原生 WebView2 的 pywebview 作为窗口承载器，它在 Windows 下有极佳的边缘融合效果和性能。
    try:
        import webview
        logger.info("Starting Desktop UI using pywebview...")
        
        # 创建一个 1100x750 磨砂渐变风格视窗，开启开发者工具
        window = webview.create_window(
            title="Windows Multi-Agent 桌面协同助手",
            url="http://127.0.0.1:8000",
            width=1150,
            height=780,
            resizable=True,
            min_size=(800, 600)
        )
        # 启动 GUI 循环
        webview.start(debug=False)
        
    except ImportError:
        logger.warning("pywebview is not installed. Attempting to fall back to PySide6 QWebEngineView...")
        try:
            from PySide6.QtCore import QUrl
            from PySide6.QtWidgets import QApplication, QMainWindow
            from PySide6.QtWebEngineWidgets import QWebEngineView

            app = QApplication(sys.argv)
            window = QMainWindow()
            window.setWindowTitle("Windows Multi-Agent 桌面协同助手 (PySide6)")
            window.resize(1150, 780)

            browser = QWebEngineView()
            browser.setUrl(QUrl("http://127.0.0.1:8000"))
            window.setCentralWidget(browser)
            
            window.show()
            sys.exit(app.exec())
        except Exception as e:
            logger.error(f"Failed to start any GUI client: {e}. Please access http://127.0.0.1:8000 via your browser directly.")
            # 挂起主线程，允许用户直接通过浏览器访问
            try:
                while True:
                    time.sleep(1)
            except KeyboardInterrupt:
                logger.info("Shutting down...")

if __name__ == "__main__":
    main()
