import logging
from typing import Dict, Any, Callable
from app.agents.base import BaseAgent
from app.tools.gui_tools import find_elements, click_gui_element, type_gui_element, capture_screen

logger = logging.getLogger(__name__)

class GUIAgent(BaseAgent):
    def __init__(self):
        system_prompt = """你是一个 Windows 原生 GUI 桌面自动化 Agent (GUIAgent)。你的职责是定位和控制活动桌面软件的交互元素。
你支持基于 Windows UI Automation API 的控件树解析，这使得你能够无需视觉模型，直接通过控件的 'name'、'automation_id' 或 'control_type' 来对其发起点击、输入操作。

操作策略指南：
1. 当需要与某一桌面软件交互时，首先调用 `find_elements` 工具获取目标窗口内的控件树信息，分析需要点击/输入的控件特征。
2. 获得控件坐标和属性后，使用 `click_gui_element` 或 `type_gui_element` 来发起真实的模拟点击与文本输入。
3. 可以在操作后调用 `capture_screen` 捕获最新的屏幕截图，用于比对验证界面状态。
4. 你的最终响应应该是对你刚才执行的所有界面模拟操作的总结。
"""
        super().__init__(name="gui_agent", system_prompt=system_prompt)
        
        # 注册找控件工具
        self.register_tool(
            name="find_elements",
            description="获取特定窗口内的所有可见和交互式 UI 控件树信息（包含控件名称、类别及边界）。",
            parameters={
                "type": "object",
                "properties": {
                    "window_title": {
                        "type": "string",
                        "description": "目标窗口的名称或部分匹配标题 (例如 '无标题 - 记事本')"
                    }
                },
                "required": ["window_title"]
            },
            func=find_elements
        )

        # 注册点击控件工具
        self.register_tool(
            name="click_gui_element",
            description="点击窗口中满足特定特征的控件元素。",
            parameters={
                "type": "object",
                "properties": {
                    "window_title": {
                        "type": "string",
                        "description": "目标窗口名称"
                    },
                    "control_name": {
                        "type": "string",
                        "description": "控件显示的文字名称 (例如 '确认'，'关闭')"
                    },
                    "control_type": {
                        "type": "string",
                        "description": "控件类型 (如 'Button', 'MenuItem')"
                    }
                },
                "required": ["window_title", "control_name"]
            },
            func=click_gui_element
        )

        # 注册控件键入工具
        self.register_tool(
            name="type_gui_element",
            description="定位特定的输入文本框，并输入文本字符。",
            parameters={
                "type": "object",
                "properties": {
                    "window_title": {
                        "type": "string",
                        "description": "目标窗口名称"
                    },
                    "control_name": {
                        "type": "string",
                        "description": "输入框控件的标签名或识别名"
                    },
                    "control_type": {
                        "type": "string",
                        "description": "控件类型 (默认可用 'Edit')"
                    },
                    "text": {
                        "type": "string",
                        "description": "准备输入的文字内容"
                    }
                },
                "required": ["window_title", "control_name", "text"]
            },
            func=type_gui_element
        )

        # 注册截屏工具
        self.register_tool(
            name="capture_screen",
            description="捕获当前桌面的全屏截图，保存为本地图片文件。",
            parameters={
                "type": "object",
                "properties": {
                    "save_path": {
                        "type": "string",
                        "description": "截图保存路径，默认可填 'screenshot.png'"
                    }
                },
                "required": ["save_path"]
            },
            func=capture_screen
        )

    async def execute_task(self, task_description: str, context: Dict[str, Any], log_cb: Callable[[str], None]) -> Dict[str, Any]:
        """
        执行主调度器派发的 GUI 交互步骤
        """
        log_cb(f"收到 GUI 指令: {task_description}")
        
        # 构建消息流
        messages = [
            {"role": "system", "content": self.system_prompt},
            {"role": "user", "content": f"当前共享内存上下文: {context}\n请执行 GUI 任务: {task_description}"}
        ]

        step_limit = 10
        step_count = 0
        final_summary = ""

        # 获取正在运行的计划名称，用于安全过滤拦截
        from app.core import orchestrator
        task_name = orchestrator.current_task_name or "UnknownTask"

        while step_count < step_limit:
            log_cb(f"正在进行思考步骤 {step_count + 1}...")
            response = await self.run_llm(messages, use_tools=True)
            message = response.choices[0].message
            
            # 记录思考内容
            if message.content:
                log_cb(f"Agent 思考: {message.content}")
                messages.append({"role": "assistant", "content": message.content})
                final_summary = message.content

            # 检查工具调用
            tool_calls = getattr(message, "tool_calls", None)
            if not tool_calls:
                log_cb("GUI 操作序列就绪并执行完毕。")
                break

            # 处理工具调用
            messages.append(message)
            for tool_call in tool_calls:
                func_name = tool_call.function.name
                func_args = {}
                try:
                    func_args = json.loads(tool_call.function.arguments)
                except Exception:
                    import re
                    args_str = tool_call.function.arguments
                    args_str = re.sub(r'\\([^\'\"\\/bfnrtu])', r'\1', args_str)
                    try:
                        func_args = json.loads(args_str)
                    except:
                        pass
                
                log_cb(f"准备调用 GUI 工具: {func_name}({func_args})")
                
                if func_name in self.tool_map:
                    func = self.tool_map[func_name]
                    try:
                        # 传入 task_name 供 guardrail 校验
                        result = await func(task_name=task_name, **func_args)
                        log_cb(f"工具执行输出: {result}")
                    except Exception as err:
                        result = f"[ERROR]: 工具执行抛出异常: {err}"
                        log_cb(result)
                else:
                    result = f"[ERROR]: 未定义工具 {func_name}"
                    log_cb(result)

                # 将工具返回的 observation 填回上下文
                messages.append({
                    "role": "tool",
                    "tool_call_id": tool_call.id,
                    "name": func_name,
                    "content": str(result)
                })

            step_count += 1

        return {
            "status": "completed" if step_count < step_limit else "limit_exceeded",
            "summary": final_summary,
            "steps_taken": step_count
        }

# 辅助 json 导入
import json
