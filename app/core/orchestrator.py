import json
import logging
import asyncio
from typing import Dict, Any, List, Optional, Callable
import litellm
from app.core.config import get_config
from app.core.db import register_task, is_task_debugged
from app.agents.os_agent import OSAgent
from app.agents.gui_agent import GUIAgent

logger = logging.getLogger(__name__)

# 全局运行状态
current_task_name: Optional[str] = None
shared_memory: Dict[str, Any] = {}

# 定时/手动任务运行时状态实时追踪
current_run_status: Dict[str, Any] = {
    "task_name": None,
    "status": "idle",          # 'idle', 'running', 'completed', 'failed'
    "active_agent": "None",
    "current_action": "None",
    "logs": []
}

class Orchestrator:
    def __init__(self, broadcast_cb: Optional[Callable[[Dict[str, Any]], None]] = None):
        self.broadcast_cb = broadcast_cb
        sys_config = get_config()
        self.cfg = sys_config.models.get("orchestrator")
        self.model = self.cfg.resolve_model()
        self.api_key = self.cfg.resolve_api_key()
        self.api_base = self.cfg.resolve_api_base()

        # 初始化支持的专用子 Agent
        self.agents = {
            "os_agent": OSAgent(),
            "gui_agent": GUIAgent()
        }

    def log(self, message: str, agent_name: str = "System"):
        logger.info(f"[{agent_name}] {message}")
        
        # 记录到当前运行日志中
        if current_run_status["status"] == "running":
            current_run_status["logs"].append(f"[{agent_name}] {message}")
            
        if self.broadcast_cb:
            self.broadcast_cb({
                "type": "log",
                "data": {
                    "agent": agent_name,
                    "message": message
                }
            })

    async def generate_plan(self, user_command: str) -> List[Dict[str, Any]]:
        """
        根据用户指令，通过 LLM 拆解出详细的任务执行计划。
        """
        self.log(f"正在分析用户指令: '{user_command}'", "Orchestrator")
        
        system_prompt = """你是一个多 Agent 系统的总调度器。你负责将用户输入的任务拆解为精细的多步执行计划。
目前系统中存在以下两个子 Agent，他们可以使用的工具集如下：
1. `os_agent` (操作系统/终端 Agent):
   - 工具: `execute_shell(command)`。
   - 职责: 处理命令行、脚本编写、环境配置、文件读写、静默安装等。
2. `gui_agent` (桌面 GUI 操作 Agent):
   - 工具: `find_elements(window_title)`、`click_gui_element(window_title, control_name, control_type)`、`type_gui_element(window_title, control_name, control_type, text)`、`capture_screen()`。
   - 职责: 模拟人工对特定的桌面窗口程序进行点击、文本输入。

你需要根据用户指令输出一个精细化的步骤列表。
每一项步骤必须是以下 JSON 格式：
{
  "step_id": 1,
  "agent_type": "os_agent" | "gui_agent",
  "description": "简短的步骤描述，告诉用户正在做什么",
  "instruction": "给具体子 Agent 的详细执行指令，应该包含完整的背景上下文或指令详情，不需要解释",
  "expected_outcome": "该步骤预期要达到的客观成果，用于自动验收"
}

请确保步骤切分足够原子化，例如，如果需要下载安装并打开软件输入，步骤应该是：
1. 运行下载命令 (os_agent)
2. 运行静默安装 (os_agent)
3. 查找窗口、点击输入 (gui_agent)

请直接输出 JSON 数组，不要包裹在 ```json ``` 等 Markdown 格式中。"""

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": f"用户指令是: {user_command}"}
        ]

        kwargs = {
            "model": self.model,
            "messages": messages,
            "response_format": {"type": "json_object"} if "gpt" in self.model else None
        }
        if self.api_key:
            kwargs["api_key"] = self.api_key
        if self.api_base:
            kwargs["api_base"] = self.api_base

        response = await litellm.acompletion(**kwargs)
        content = response.choices[0].message.content.strip()

        # 解析 JSON 结果
        try:
            if content.startswith("```"):
                # 兼容 Markdown 格式包裹
                lines = content.splitlines()
                if lines[0].startswith("```"):
                    lines = lines[1:]
                if lines[-1].startswith("```"):
                    lines = lines[:-1]
                content = "\n".join(lines).strip()
            
            plan = json.loads(content)
            if isinstance(plan, dict) and "steps" in plan:
                plan = plan["steps"]
            if not isinstance(plan, list):
                raise ValueError("Plan must be a list of steps")
            return plan
        except Exception as e:
            self.log(f"解析计划 JSON 失败: {e}. 原始输出为: {content}", "Orchestrator")
            # 兜底生成单步计划
            return [{
                "step_id": 1,
                "agent_type": "os_agent",
                "description": "执行用户命令",
                "instruction": user_command,
                "expected_outcome": "任务执行完成"
            }]

    async def execute_plan(self, task_name: str, plan: List[Dict[str, Any]]) -> bool:
        """
        逐个调度子 Agent 执行步骤计划，并进行结果验收与容错。
        """
        global current_task_name, shared_memory
        current_task_name = task_name
        shared_memory.clear()
        
        # 初始化运行时状态
        current_run_status["task_name"] = task_name
        current_run_status["status"] = "running"
        current_run_status["active_agent"] = "Orchestrator"
        current_run_status["current_action"] = "Initializing plan and preparing steps..."
        current_run_status["logs"] = []

        self.log(f"开始执行任务，总计 {len(plan)} 个步骤。", "Orchestrator")
        
        # 将计划结构同步给客户端
        if self.broadcast_cb:
            self.broadcast_cb({
                "type": "plan_initialized",
                "data": {
                    "task_name": task_name,
                    "steps": plan,
                    "is_debugged": is_task_debugged(task_name)
                }
            })

        for step in plan:
            step_id = step["step_id"]
            agent_type = step["agent_type"]
            desc = step["description"]
            inst = step["instruction"]
            outcome = step["expected_outcome"]

            # 动态更新当前执行信息
            current_run_status["active_agent"] = agent_type
            current_run_status["current_action"] = f"Executing Step {step_id}: {desc}"

            self.log(f">>> 步骤 {step_id}: {desc}", "Orchestrator")
            if self.broadcast_cb:
                self.broadcast_cb({
                    "type": "step_started",
                    "data": {"step_id": step_id}
                })

            if agent_type not in self.agents:
                self.log(f"未知的 Agent 类型: {agent_type}，跳过此步骤。", "Orchestrator")
                continue

            agent = self.agents[agent_type]
            
            # 执行重试回路 (最多3次)
            success = False
            retry_count = 0
            max_retries = 3
            error_feedback = ""

            while not success and retry_count < max_retries:
                if retry_count > 0:
                    self.log(f"正在进行第 {retry_count} 次重试，上次失败反馈: {error_feedback}", "Orchestrator")
                    step_instruction = f"{inst}\n[上一次执行失败反馈]: {error_feedback}\n请吸取教训，调整策略或参数重试。"
                else:
                    step_instruction = inst

                # 子 Agent 独立执行
                try:
                    self.log(f"派发任务给 {agent_type}...", "Orchestrator")
                    
                    # 定义子 Agent 的日志回调
                    def agent_log(msg: str):
                        self.log(msg, agent_type)

                    # 执行任务，获取结果
                    result = await agent.execute_task(
                        task_description=step_instruction,
                        context=shared_memory,
                        log_cb=agent_log
                    )
                    
                    self.log(f"子 Agent {agent_type} 执行完毕，开始进行验收...", "Orchestrator")
                    
                    # 调用验收器进行验收
                    from app.core.validator import validate_step_outcome
                    validation_passed, feedback = await validate_step_outcome(
                        step=step,
                        execution_result=result,
                        orchestrator_model=self.model,
                        api_key=self.api_key,
                        api_base=self.api_base
                    )
                    
                    if validation_passed:
                        self.log(f"步骤 {step_id} 验收通过！", "Orchestrator")
                        success = True
                        # 保存变量到共享内存
                        shared_memory[f"step_{step_id}_output"] = result
                        if self.broadcast_cb:
                            self.broadcast_cb({
                                "type": "step_completed",
                                "data": {"step_id": step_id, "output": result}
                            })
                    else:
                        error_feedback = feedback
                        self.log(f"步骤 {step_id} 验收未通过: {feedback}", "Orchestrator")
                        retry_count += 1
                except Exception as e:
                    error_feedback = str(e)
                    self.log(f"步骤 {step_id} 执行期间抛出异常: {e}", "Orchestrator")
                    retry_count += 1
                    await asyncio.sleep(1) # 短暂等待重试

            if not success:
                self.log(f"步骤 {step_id} 失败多次，任务整体终止。", "Orchestrator")
                
                # 更新状态为失败
                current_run_status["status"] = "failed"
                current_run_status["active_agent"] = "None"
                current_run_status["current_action"] = f"Failed at Step {step_id}: {error_feedback}"
                
                if self.broadcast_cb:
                    self.broadcast_cb({
                        "type": "step_failed",
                        "data": {"step_id": step_id, "error": error_feedback}
                    })
                return False

        self.log("所有任务步骤均已执行完毕并验收合格！", "Orchestrator")
        
        # 更新状态为成功完成
        current_run_status["status"] = "completed"
        current_run_status["active_agent"] = "None"
        current_run_status["current_action"] = "Task finished successfully."

        if self.broadcast_cb:
            self.broadcast_cb({
                "type": "task_completed",
                "data": {"task_name": task_name}
            })
        return True
