import os
import sys
import logging
import base64
from typing import Dict, Any, List, Optional
from app.core.guardrail import request_action_approval

logger = logging.getLogger(__name__)

# 动态加载 Windows 特有依赖，以便跨平台测试开发
IS_WINDOWS = sys.platform == 'win32'
pywinauto_app = None
pyautogui = None

if IS_WINDOWS:
    try:
        from pywinauto.application import Application
        import pyautogui
    except ImportError as e:
        logger.warning(f"Failed to import pywinauto or pyautogui on Windows: {e}")
else:
    logger.info("Not running on Windows. GUI Tools will operate in MOCK mode.")

async def capture_screen(task_name: str, save_path: str = "screenshot.png") -> str:
    """捕获屏幕截图，返回文件路径"""
    logger.info("Capturing screen...")
    if IS_WINDOWS and pyautogui:
        # 截图不需要动作确认，通常是只读的观察操作
        try:
            screenshot = pyautogui.screenshot()
            screenshot.save(save_path)
            return os.path.abspath(save_path)
        except Exception as e:
            logger.error(f"Failed to capture screen: {e}")
            return ""
    else:
        # Mock mode
        with open(save_path, "w") as f:
            f.write("mock screenshot content")
        return os.path.abspath(save_path)

async def find_elements(task_name: str, window_title: str) -> List[Dict[str, Any]]:
    """
    参考 Windows-Use 逻辑，利用 UI Automation 获取窗口内的所有交互控件。
    """
    logger.info(f"Finding elements in window: {window_title}")
    elements = []
    
    if IS_WINDOWS:
        try:
            # 连接或启动窗口
            app = Application(backend="uia").connect(title_re=f".*{window_title}.*", timeout=3)
            window = app.window(title_re=f".*{window_title}.*")
            
            # 遍历子控件树
            descendants = window.descendants()
            for elem in descendants:
                info = elem.element_info
                # 只获取有名字且有一定交互价值的控件
                if info.name or info.automation_id:
                    rect = info.rectangle
                    elements.append({
                        "name": info.name,
                        "automation_id": info.automation_id,
                        "control_type": info.control_type,
                        "visible": info.visible,
                        "rect": {
                            "left": rect.left,
                            "top": rect.top,
                            "right": rect.right,
                            "bottom": rect.bottom,
                            "width": rect.width(),
                            "height": rect.height()
                        }
                    })
        except Exception as e:
            logger.error(f"Error listing descendants of '{window_title}': {e}")
    else:
        # Mock elements for development testing
        elements = [
            {"name": "确认", "automation_id": "btn_confirm", "control_type": "Button", "rect": {"left": 100, "top": 200, "width": 50, "height": 30}},
            {"name": "输入框", "automation_id": "txt_input", "control_type": "Edit", "rect": {"left": 100, "top": 150, "width": 200, "height": 30}}
        ]
        
    return elements

async def click_gui_element(task_name: str, window_title: str, control_name: str, control_type: str = "Button") -> str:
    """
    定位并点击特定的 GUI 控件，集成动作审批拦截。
    """
    action_args = {
        "window_title": window_title,
        "control_name": control_name,
        "control_type": control_type
    }
    
    # 动作审批拦截检查
    decision, approved_args = await request_action_approval(
        task_name=task_name,
        action_type="gui_click",
        action_args=action_args,
        description=f"打算在窗口 '{window_title}' 中点击 '{control_name}' ({control_type})"
    )
    
    win_t = approved_args.get("window_title", window_title)
    ctrl_n = approved_args.get("control_name", control_name)
    ctrl_t = approved_args.get("control_type", control_type)

    if IS_WINDOWS:
        try:
            app = Application(backend="uia").connect(title_re=f".*{win_t}.*", timeout=3)
            window = app.window(title_re=f".*{win_t}.*")
            
            # 定位控件
            control = window.child_window(title=ctrl_n, control_type=ctrl_t)
            if control.exists():
                control.click_input() # 模拟真实的鼠标点击
                return f"Successfully clicked element '{ctrl_n}' in window '{win_t}'."
            else:
                return f"Error: Element '{ctrl_n}' of type '{ctrl_t}' not found in window '{win_t}'."
        except Exception as e:
            logger.error(f"GUI Click failed: {e}")
            return f"Failed to click: {str(e)}"
    else:
        # Mock success
        return f"[MOCK] Clicked element '{ctrl_n}' in window '{win_t}'."

async def type_gui_element(task_name: str, window_title: str, control_name: str, control_type: str, text: str) -> str:
    """
    定位并在特定的 GUI 控件中输入文本，集成动作审批拦截。
    """
    action_args = {
        "window_title": window_title,
        "control_name": control_name,
        "control_type": control_type,
        "text": text
    }
    
    # 动作审批拦截检查
    decision, approved_args = await request_action_approval(
        task_name=task_name,
        action_type="gui_type",
        action_args=action_args,
        description=f"打算在窗口 '{window_title}' 的控件 '{control_name}' 中输入文本: '{text}'"
    )
    
    win_t = approved_args.get("window_title", window_title)
    ctrl_n = approved_args.get("control_name", control_name)
    ctrl_t = approved_args.get("control_type", control_type)
    in_text = approved_args.get("text", text)

    if IS_WINDOWS:
        try:
            app = Application(backend="uia").connect(title_re=f".*{win_t}.*", timeout=3)
            window = app.window(title_re=f".*{win_t}.*")
            
            # 定位控件
            control = window.child_window(title=ctrl_n, control_type=ctrl_t)
            if control.exists():
                control.click_input()
                control.type_keys(in_text, with_spaces=True, clear=True)
                return f"Successfully typed '{in_text}' into element '{ctrl_n}' in window '{win_t}'."
            else:
                return f"Error: Element '{ctrl_n}' of type '{ctrl_t}' not found in window '{win_t}'."
        except Exception as e:
            logger.error(f"GUI Type failed: {e}")
            return f"Failed to type text: {str(e)}"
    else:
        # Mock success
        return f"[MOCK] Typed '{in_text}' into element '{ctrl_n}' in window '{win_t}'."
