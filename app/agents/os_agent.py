import logging
from typing import Dict, Any, Callable
from app.agents.base import BaseAgent
from app.tools.shell_tools import run_shell_command

logger = logging.getLogger(__name__)

class OSAgent(BaseAgent):
    def __init__(self):
        system_prompt = """你是一个操作系统命令行 Agent (OSAgent)。你的职责是利用命令行工具 (PowerShell/CMD) 在 Windows 系统中完成各种底层配置、软件安装、文件管理等任务。
你可以编写并执行单行或多行 Shell 指令。
当你调用 `execute_command` 执行脚本或命令行后，系统会向你返回实际的终端输出或错误日志。
你应该仔细分析命令行返回，如有错误（如未找到命令、权限不足等），要善于调整参数或命令重试。

重要原则：
1. 你的最终响应应该是对你刚才执行的所有操作的一个最终总结（说明你执行了什么，达成了什么效果，产生的文件是什么）。
2. 在任务完成前，你需要调用 `execute_command` 来切实改变操作系统状态，不要只靠嘴说！
"""
        super().__init__(name="os_agent", system_prompt=system_prompt)
        
        # 注册 execute_command 工具
        self.register_tool(
            name="execute_command",
            description="在 Windows 系统的 shell (CMD/PowerShell) 中执行特定的命令行命令。可以包含脚本运行、文件创建或环境管理。",
            parameters={
                "type": "object",
                "properties": {
                    "command": {
                        "type": "string",
                        "description": "需要执行的具体命令行指令字符串"
                    }
                },
                "required": ["command"]
            },
            func=run_shell_command
        )

    async def execute_task(self, task_description: str, context: Dict[str, Any], log_cb: Callable[[str], None]) -> Dict[str, Any]:
        """
        执行主调度器派发的任务
        """
        log_cb(f"收到指令: {task_description}")
        
        # 构建消息流
        messages = [
            {"role": "system", "content": self.system_prompt},
            {"role": "user", "content": f"当前共享内存上下文: {context}\n请执行任务: {task_description}"}
        ]

        step_limit = 10
        step_count = 0
        final_summary = ""

        # 获取当前正在运行的计划名称，用于安全过滤拦截
        from app.core import orchestrator
        task_name = orchestrator.current_task_name or "UnknownTask"

        while step_count < step_limit:
            log_cb(f"正在进行思考步骤 {step_count + 1}...")
            response = await self.run_llm(messages, use_tools=True)
            message = response.choices[0].message
            
            # 记录 LLM 的思考内容
            if message.content:
                log_cb(f"Agent 思考: {message.content}")
                messages.append({"role": "assistant", "content": message.content})
                final_summary = message.content

            # 检查是否调用了工具
            tool_calls = getattr(message, "tool_calls", None)
            if not tool_calls:
                # LLM 没有发起工具调用，说明已经执行完毕
                log_cb("任务思考结束，完成步骤。")
                break

            # 处理工具调用
            messages.append(message) # 必须把带有 tool_calls 的 assistant 消息放进历史中
            for tool_call in tool_calls:
                func_name = tool_call.function.name
                func_args = {}
                try:
                    func_args = json.loads(tool_call.function.arguments)
                except Exception:
                    # 有时候大模型返回的 JSON 有多余符号，做简单容错
                    import re
                    args_str = tool_call.function.arguments
                    args_str = re.sub(r'\\([^\'\"\\/bfnrtu])', r'\1', args_str)
                    try:
                        func_args = json.loads(args_str)
                    except:
                        pass
                
                log_cb(f"准备调用工具: {func_name}({func_args})")
                
                if func_name in self.tool_map:
                    # 执行工具
                    func = self.tool_map[func_name]
                    try:
                        # 传入 task_name 供 guardrail 校验
                        if func_name == "execute_command":
                            result = await func(task_name=task_name, command=func_args.get("command", ""))
                        else:
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
