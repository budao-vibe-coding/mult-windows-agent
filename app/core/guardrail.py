import asyncio
import uuid
import logging
import json
from typing import Dict, Tuple, Any, Callable, Optional
from app.core.db import is_task_debugged, is_action_approved, add_approved_action

logger = logging.getLogger(__name__)

# 全局待审批队列
# approval_id -> (Future, action_details_dict)
pending_approvals: Dict[str, Tuple[asyncio.Future, Dict[str, Any]]] = {}

# WebSocket 广播回调函数 (由 FastAPI 启动时注册)
broadcast_callback: Optional[Callable[[Dict[str, Any]], None]] = None

class SkipActionException(Exception):
    """用户跳过了该动作的执行"""
    pass

class TaskTerminatedException(Exception):
    """用户终止了任务的运行"""
    pass

def register_broadcast_callback(cb: Callable[[Dict[str, Any]], None]):
    global broadcast_callback
    broadcast_callback = cb

async def request_action_approval(
    task_name: str, 
    action_type: str, 
    action_args: Dict[str, Any],
    description: str = ""
) -> Tuple[str, Dict[str, Any]]:
    """
    请求执行动作审批。
    如果任务处于调试期且动作未被录入白名单，则会在此挂起，通过 WebSocket 触发展示审批弹窗，直到用户点击决策。
    返回: (决策结果 'approve'/'skip'/'terminate', 修改后的动作参数)
    """
    # 1. 检查任务是否已经调试完成并加入白名单
    if is_task_debugged(task_name):
        return "approve", action_args

    # 2. 检查此具体动作签名是否已被核准 (白名单化)
    # 将参数转为排序后的字符串作为指纹签名
    sig_str = json_signature(action_args)
    if is_action_approved(task_name, action_type, sig_str):
        logger.info(f"Action '{action_type}' with signature '{sig_str}' is already approved. Auto-executing.")
        return "approve", action_args

    # 3. 未被核准，且在调试状态下 -> 触发挂起审批
    approval_id = str(uuid.uuid4())
    loop = asyncio.get_running_loop()
    fut = loop.create_future()
    
    action_details = {
        "approval_id": approval_id,
        "task_name": task_name,
        "action_type": action_type,
        "action_args": action_args,
        "description": description or f"请求执行: {action_type}"
    }
    
    pending_approvals[approval_id] = (fut, action_details)
    logger.info(f"Intercepted action. Awaiting user approval: {action_details}")

    # 发送 WebSocket 消息通知桌面端 UI 弹窗
    if broadcast_callback:
        broadcast_callback({
            "type": "action_intercepted",
            "data": action_details
        })
    else:
        logger.warning("No broadcast callback registered! Auto-approving for headless runtime.")
        return "approve", action_args

    try:
        # 挂起协程，等待 UI 的回复
        decision, response_args, remember = await fut
        
        if decision == "approve":
            if remember:
                # 记录进数据库白名单
                add_approved_action(task_name, action_type, sig_str)
            return "approve", response_args
        elif decision == "skip":
            raise SkipActionException("Action skipped by user.")
        else:
            raise TaskTerminatedException("Task execution terminated by user.")
            
    finally:
        # 清除待审批状态
        pending_approvals.pop(approval_id, None)

def resolve_approval(approval_id: str, decision: str, response_args: Dict[str, Any], remember: bool = False):
    """
    当用户在客户端点击 同意/跳过/终止 时，调用此方法恢复挂起的协程。
    """
    if approval_id in pending_approvals:
        fut, _ = pending_approvals[approval_id]
        if not fut.done():
            fut.set_result((decision, response_args, remember))
            return True
    return False

def json_signature(data: Any) -> str:
    """生成标准化 JSON 字符串指纹"""
    return json.dumps(data, sort_keys=True, ensure_ascii=False)
