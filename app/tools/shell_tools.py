import asyncio
import logging
import subprocess
from typing import Dict, Any, Tuple
from app.core.guardrail import request_action_approval

logger = logging.getLogger(__name__)

async def run_shell_command(task_name: str, command: str) -> str:
    """
    在 Windows 下执行命令行工具（CMD 或 PowerShell），包含动作审批检查。
    """
    logger.info(f"Preparing to run shell command: {command}")
    
    # 动作审批拦截检查
    decision, approved_args = await request_action_approval(
        task_name=task_name,
        action_type="execute_shell",
        action_args={"command": command},
        description=f"打算执行命令行指令: {command}"
    )
    
    # 获取（可能被用户修改后的）指令
    exec_command = approved_args.get("command", command)
    
    # 开始异步执行系统命令
    # 在 Windows 系统上指定 shell=True 时，默认会调用 cmd.exe
    process = await asyncio.create_subprocess_shell(
        exec_command,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE
    )
    
    stdout, stderr = await process.communicate()
    
    stdout_str = stdout.decode("gbk", errors="replace").strip() # Windows 默认 GBK 编码
    stderr_str = stderr.decode("gbk", errors="replace").strip()
    
    output = []
    if stdout_str:
        output.append(stdout_str)
    if stderr_str:
        output.append(f"[ERROR]: {stderr_str}")
        
    result_str = "\n".join(output)
    logger.info(f"Command execution completed with returncode {process.returncode}")
    return result_str if result_str else f"Command executed successfully (no output, returncode: {process.returncode})"
