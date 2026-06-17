import json
import logging
from typing import List, Dict, Any, Callable, Optional
import litellm
from app.core.config import get_config

logger = logging.getLogger(__name__)

class BaseAgent:
    def __init__(self, name: str, system_prompt: str):
        self.name = name
        self.system_prompt = system_prompt
        
        # Load agent-specific model configuration
        sys_config = get_config()
        self.agent_cfg = sys_config.models.get(name)
        if not self.agent_cfg:
            # Fallback to orchestrator model if specific agent model is not configured
            self.agent_cfg = sys_config.models.get("orchestrator")
            
        if not self.agent_cfg:
            raise ValueError(f"No model configuration found for agent '{name}' or fallback 'orchestrator'")
            
        self.model = self.agent_cfg.model
        self.api_key = self.agent_cfg.resolve_api_key()
        self.api_base = self.agent_cfg.api_base
        
        # Available tools for this agent
        self.tools: List[Dict[str, Any]] = []
        self.tool_map: Dict[str, Callable] = {}

    def register_tool(self, name: str, description: str, parameters: Dict[str, Any], func: Callable):
        """注册工具供 Agent 决策时使用"""
        tool_definition = {
            "type": "function",
            "function": {
                "name": name,
                "description": description,
                "parameters": parameters
            }
        }
        self.tools.append(tool_definition)
        self.tool_map[name] = func

    async def run_llm(self, messages: List[Dict[str, str]], use_tools: bool = True) -> Any:
        """调用云端 LLM (包含可选的工具包定义)"""
        kwargs = {
            "model": self.model,
            "messages": messages,
        }
        if self.api_key:
            kwargs["api_key"] = self.api_key
        if self.api_base:
            kwargs["api_base"] = self.api_base

        if use_tools and self.tools:
            kwargs["tools"] = self.tools
            kwargs["tool_choice"] = "auto"

        # Using asyncio threadpool or standard async call
        # LiteLLM's acompletion is native async
        try:
            response = await litellm.acompletion(**kwargs)
            return response
        except Exception as e:
            logger.error(f"Agent {self.name} LLM call failed: {e}")
            raise e

    async def execute_task(self, task_description: str, context: Dict[str, Any], log_cb: Callable[[str], None]) -> Dict[str, Any]:
        """
        执行子任务的核心循环。子类需要重写或者扩展此方法。
        """
        raise NotImplementedError("Subclasses must implement execute_task")
