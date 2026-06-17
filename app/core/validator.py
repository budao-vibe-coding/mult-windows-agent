import json
import logging
from typing import Dict, Any, Tuple, Optional
import litellm

logger = logging.getLogger(__name__)

async def validate_step_outcome(
    step: Dict[str, Any],
    execution_result: Any,
    orchestrator_model: str,
    api_key: Optional[str] = None,
    api_base: Optional[str] = None
) -> Tuple[bool, str]:
    """
    使用大模型作为验收评估器，判定实际执行成果是否契合预期。
    返回: (是否通过: bool, 反馈信息: str)
    """
    desc = step.get("description", "")
    inst = step.get("instruction", "")
    expected = step.get("expected_outcome", "")
    
    # 格式化子 Agent 的实际输出
    if isinstance(execution_result, dict):
        result_str = json.dumps(execution_result, indent=2, ensure_ascii=False)
    else:
        result_str = str(execution_result)

    # 快捷初步检查：如果包含致命异常且没有正常输出
    if "[ERROR]" in result_str and "Failed" in result_str:
        # 存在明显错误，直接判定不通过，省去一次 LLM 调用
        return False, f"执行结果包含明确的错误异常标记: {result_str}"

    system_prompt = """你是一个任务结果验收器。你的工作是对比【步骤指令】和【预期目标】，分析【实际执行结果】，判定该任务步骤是否已成功达成预期目标。
如果实际执行结果满足了预期目标（哪怕有轻微的无碍警告，只要核心目的达到即算成功），则通过。
如果执行出错、未产生预期文件、未达成预期界面状态或目标未达成，则不通过，并提供详细的改进原因供子 Agent 参考重试。

你需要以 JSON 格式输出评估结果，格式如下：
{
  "passed": true | false,
  "feedback": "若 passed 为 false，请在此指出未达标的详细原因和错误日志；若 passed 为 true，填 '验收通过'。"
}

请直接输出 JSON，不要将其包裹在 ```json 等 Markdown 代码块中。"""

    user_content = f"""【步骤名称】: {desc}
【步骤指令】: {inst}
【预期目标】: {expected}

【实际执行结果】:
{result_str}
"""

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_content}
    ]

    kwargs = {
        "model": orchestrator_model,
        "messages": messages,
        "response_format": {"type": "json_object"} if "gpt" in orchestrator_model else None
    }
    if api_key:
        kwargs["api_key"] = api_key
    if api_base:
        kwargs["api_base"] = api_base

    try:
        response = await litellm.acompletion(**kwargs)
        content = response.choices[0].message.content.strip()

        # 兼容 Markdown 格式包裹
        if content.startswith("```"):
            lines = content.splitlines()
            if lines[0].startswith("```"):
                lines = lines[1:]
            if lines[-1].startswith("```"):
                lines = lines[:-1]
            content = "\n".join(lines).strip()

        eval_result = json.loads(content)
        passed = bool(eval_result.get("passed", False))
        feedback = eval_result.get("feedback", "无详细反馈")
        return passed, feedback

    except Exception as e:
        logger.error(f"Validator LLM evaluation failed: {e}")
        # 降级：如果大模型验收失败，但执行结果不包含 "Error/Failed" 关键字，默认为通过
        if "error" in result_str.lower() or "failed" in result_str.lower() or "exception" in result_str.lower():
            return False, f"LLM 验收出错，且执行结果中检测到疑似错误信息: {result_str}"
        return True, "LLM 验收器解析失败，降级默认为通过。"
