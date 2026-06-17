import os
import sys
import asyncio
import unittest
from unittest.mock import AsyncMock, patch
import sqlite3

# 将当前目录加入 Python 搜索路径
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from app.core.config import load_config
from app.core.db import init_db, is_task_debugged, is_action_approved
from app.core.orchestrator import Orchestrator
from app.core.guardrail import pending_approvals, resolve_approval

class MockFunction:
    def __init__(self, name, arguments):
        self.name = name
        self.arguments = arguments

class MockToolCall:
    def __init__(self, id, name, arguments):
        self.id = id
        self.function = MockFunction(name, arguments)

class MockMessage:
    def __init__(self, content, tool_calls=None):
        self.content = content
        self.tool_calls = tool_calls

class MockChoice:
    def __init__(self, content, tool_calls=None):
        self.message = MockMessage(content, tool_calls)

class MockResponse:
    def __init__(self, content, tool_calls=None):
        self.choices = [MockChoice(content, tool_calls)]

class TestMultiAgentWorkflow(unittest.IsolatedAsyncioTestCase):
    
    async def asyncSetUp(self):
        # 强制配置测试用数据库
        os.environ["APP_DATA_DB"] = "test_app_data.db"
        if os.path.exists("test_app_data.db"):
            os.remove("test_app_data.db")
            
        load_config()
        # 修改内存中数据库路径为测试库
        from app.core import db
        db.get_db_connection = lambda: sqlite3.connect("test_app_data.db")
        init_db()

    async def asyncTearDown(self):
        if os.path.exists("test_app_data.db"):
            try:
                os.remove("test_app_data.db")
            except:
                pass
        if os.path.exists("test_dir"):
            try:
                os.rmdir("test_dir")
            except:
                pass

    @patch("litellm.acompletion")
    async def test_orchestrator_and_guardrail_flow(self, mock_completion):
        """
        测试整体的多 Agent 状态机调度流、动作拦截以及调试通过后的自动放行。
        """
        # 1. 模拟 Planner (步骤拆解) 和 Validator (结果验收) 的 LLM 响应
        # 第一次返回：Planner 的任务拆解 JSON
        # 第二次返回：OS Agent 的思考（要调用 execute_command）
        # 第三次返回：OS Agent 的思考总结
        # 第四次返回：Validator 验收合格 JSON
        
        mock_planner_response = MockResponse(json_plan_str())
        
        tool_calls = [
            MockToolCall(
                id="call_123",
                name="execute_command",
                arguments='{"command": "mkdir test_dir"}'
            )
        ]
        mock_os_agent_step1 = MockResponse(
            content="我认为我需要使用 shell 工具创建目录。",
            tool_calls=tool_calls
        )
        
        mock_os_agent_step2 = MockResponse(content="目录已成功创建，任务完成。")
        
        mock_validator_response = MockResponse(content='{"passed": true, "feedback": "验收通过"}')
        
        mock_completion.side_effect = [
            mock_planner_response,    # 任务拆解
            mock_os_agent_step1,      # Agent 提出动作
            mock_os_agent_step2,      # Agent 结束思考
            mock_validator_response   # 验收器通过
        ]

        # 创建总调度器
        # 我们注册一个模拟广播回调，以便在后台自动同意动作拦截
        async def mock_broadcast(msg):
            if msg["type"] == "action_intercepted":
                approval_id = msg["data"]["approval_id"]
                # 模拟用户在客户端勾选“记住本次审批”并点击“同意”
                await asyncio.sleep(0.1)
                resolve_approval(approval_id, "approve", msg["data"]["action_args"], remember=True)

        def sync_broadcast(msg):
            asyncio.create_task(mock_broadcast(msg))

        from app.core.guardrail import register_broadcast_callback
        register_broadcast_callback(sync_broadcast)

        orchestrator = Orchestrator(broadcast_cb=sync_broadcast)

        task_name = "CreateDirTask"
        user_cmd = "帮我创建一个名为 test_dir 的文件夹"
        
        # --- 第一次执行：进入调试模式，会触发拦截审批 ---
        self.assertFalse(is_task_debugged(task_name))
        
        # 生成计划
        plan = await orchestrator.generate_plan(user_cmd)
        self.assertEqual(len(plan), 1)
        self.assertEqual(plan[0]["agent_type"], "os_agent")
        
        # 执行计划
        success = await orchestrator.execute_plan(task_name, plan)
        self.assertTrue(success)
        
        # 验证是否成功创建了文件夹
        self.assertTrue(os.path.exists("test_dir"))
        
        # 验证动作是否被成功录入白名单
        # 注意：execute_shell 参数被 hash 指纹化存储
        self.assertTrue(is_action_approved(task_name, "execute_shell", '{"command": "mkdir test_dir"}'))

        # --- 第二次执行：模拟再次运行。本次运行由于命令已在白名单中，因此即使 task_debugged 未设为 true，也应无拦截放行 ---
        # 清除 test_dir 目录以便测试再次执行效果
        if os.path.exists("test_dir"):
            os.rmdir("test_dir")
            
        mock_completion.side_effect = [
            mock_os_agent_step1,      # Agent 提出动作
            mock_os_agent_step2,      # Agent 结束思考
            mock_validator_response   # 验收器通过
        ]
        
        # 模拟没有 UI 广播处理（代表如果是拦截状态，程序会卡死，如果没卡死成功运行，证明白名单免除拦截成功）
        orchestrator_headless = Orchestrator(broadcast_cb=None)
        success_headless = await orchestrator_headless.execute_plan(task_name, plan)
        self.assertTrue(success_headless)
        self.assertTrue(os.path.exists("test_dir"))

def json_plan_str():
    return """
    [
      {
        "step_id": 1,
        "agent_type": "os_agent",
        "description": "创建 test_dir 目录",
        "instruction": "请运行 mkdir test_dir 指令创建文件夹",
        "expected_outcome": "在系统当前路径下存在一个名为 test_dir 的文件夹"
      }
    ]
    """

if __name__ == "__main__":
    unittest.main()
