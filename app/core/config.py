import os
import yaml
from typing import Dict, Any, Optional
from pydantic import BaseModel, Field
from dotenv import load_dotenv

# 自动从项目根目录的 .env 文件中加载环境变量
load_dotenv()

class ModelConfig(BaseModel):
    model: str
    api_key: Optional[str] = None
    api_base: Optional[str] = None

    def resolve_model(self) -> str:
        if self.model.startswith("ENV_"):
            env_var = self.model[4:]
            val = os.getenv(env_var)
            if val:
                return val
            # 兜底默认模型
            if "OPENAI" in env_var:
                return "openai/gpt-4o"
            elif "RESPONSE" in env_var:
                return "deepseek/deepseek-chat"
            elif "ANTHROPIC" in env_var:
                return "anthropic/claude-3-5-sonnet"
        return self.model

    def resolve_api_key(self) -> Optional[str]:
        if not self.api_key:
            return None
        if self.api_key.startswith("ENV_"):
            env_var = self.api_key[4:]
            return os.getenv(env_var)
        return self.api_key

    def resolve_api_base(self) -> Optional[str]:
        if not self.api_base:
            return None
        if self.api_base.startswith("ENV_"):
            env_var = self.api_base[4:]
            val = os.getenv(env_var)
            return val if val else None
        return self.api_base

class ServerConfig(BaseModel):
    host: str = "127.0.0.1"
    port: int = 8000
    debug: bool = True
    db_path: str = "app_data.db"
    sandbox_dir: str = "./sandbox"

class SafetyConfig(BaseModel):
    intercept_actions: list[str] = Field(default_factory=list)

class SystemConfig(BaseModel):
    server: ServerConfig
    safety: SafetyConfig
    models: Dict[str, ModelConfig]

_config_instance: Optional[SystemConfig] = None

def load_config(config_path: str = "config.yaml") -> SystemConfig:
    global _config_instance
    if _config_instance is not None:
        return _config_instance

    if not os.path.exists(config_path):
        raise FileNotFoundError(f"Configuration file not found: {config_path}")

    with open(config_path, "r", encoding="utf-8") as f:
        raw_data = yaml.safe_load(f)

    # Initialize directories
    server_data = raw_data.get("server", {})
    sandbox = server_data.get("sandbox_dir", "./sandbox")
    os.makedirs(sandbox, exist_ok=True)

    _config_instance = SystemConfig(**raw_data)
    return _config_instance

def get_config() -> SystemConfig:
    global _config_instance
    if _config_instance is None:
        return load_config()
    return _config_instance
