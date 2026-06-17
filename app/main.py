import os
import json
import logging
import asyncio
from typing import List, Dict, Any
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import load_config, get_config
from app.core.db import init_db, register_task, get_whitelist_tasks
from app.core.orchestrator import Orchestrator
from app.core.guardrail import register_broadcast_callback, resolve_approval

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger(__name__)

# 初始化 FastAPI
app = FastAPI(title="Windows Multi-Agent Auto-System Backend")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# WebSocket 连接管理
class ConnectionManager:
    def __init__(self):
        self.active_connections: List[WebSocket] = []

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)
        logger.info(f"New WebSocket client connected. Active connections: {len(self.active_connections)}")

    def disconnect(self, websocket: WebSocket):
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)
            logger.info(f"WebSocket client disconnected. Active connections: {len(self.active_connections)}")

    async def send_personal_message(self, message: Dict[str, Any], websocket: WebSocket):
        await websocket.send_json(message)

    async def broadcast(self, message: Dict[str, Any]):
        for connection in self.active_connections:
            try:
                await connection.send_json(message)
            except Exception as e:
                logger.error(f"Failed to send message to websocket client: {e}")

manager = ConnectionManager()

# 将 guardrail 的广播回调绑定到 WebSocket 的广播上
def ws_broadcast_handler(message: Dict[str, Any]):
    # 使用 asyncio 安排在运行循环中执行
    asyncio.create_task(manager.broadcast(message))

# 注册回调
register_broadcast_callback(ws_broadcast_handler)

# 启动任务管理
orchestrator_instance = Orchestrator(broadcast_cb=ws_broadcast_handler)

@app.on_event("startup")
def startup_event():
    # 初始化配置文件与数据库
    load_config()
    init_db()
    logger.info("Database initialized and config loaded successfully.")

# RESTful 接口
@app.get("/api/whitelist")
def get_whitelist():
    return {"status": "success", "data": get_whitelist_tasks()}

@app.get("/api/config")
def get_system_config():
    config = get_config()
    return {"status": "success", "data": config.dict()}

# 主 WebSocket 管道
@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await manager.connect(websocket)
    try:
        while True:
            data = await websocket.receive_text()
            message = json.loads(data)
            msg_type = message.get("type")
            msg_data = message.get("data", {})
            
            logger.info(f"Received WebSocket message: {msg_type} -> {msg_data}")
            
            if msg_type == "submit_task":
                task_name = msg_data.get("task_name", "Default Task")
                user_command = msg_data.get("user_command", "")
                
                # 异步执行任务规划与派发，防止阻塞 WebSocket 监听线程
                asyncio.create_task(run_task_flow(task_name, user_command))
                
            elif msg_type == "resolve_approval":
                approval_id = msg_data.get("approval_id")
                decision = msg_data.get("decision")
                response_args = msg_data.get("response_args", {})
                remember = msg_data.get("remember", False)
                
                resolved = resolve_approval(approval_id, decision, response_args, remember)
                await websocket.send_json({
                    "type": "approval_resolved_ack",
                    "data": {"approval_id": approval_id, "success": resolved}
                })
                
            elif msg_type == "mark_task_debugged":
                task_name = msg_data.get("task_name")
                is_debugged = msg_data.get("is_debugged", True)
                register_task(task_name, is_debugged=is_debugged)
                # 广播状态变更
                await manager.broadcast({
                    "type": "task_debugged_updated",
                    "data": {"task_name": task_name, "is_debugged": is_debugged}
                })
                
    except WebSocketDisconnect:
        manager.disconnect(websocket)
    except Exception as e:
        logger.error(f"WebSocket error: {e}")
        manager.disconnect(websocket)

async def run_task_flow(task_name: str, user_command: str):
    """主调度工作流封装，通过 WebSocket 实时推送状态"""
    try:
        # 1. 解析计划
        plan = await orchestrator_instance.generate_plan(user_command)
        
        # 2. 执行计划
        success = await orchestrator_instance.execute_plan(task_name, plan)
        
        logger.info(f"Task '{task_name}' flow execution completed: success={success}")
    except Exception as e:
        logger.error(f"Error in task flow execution: {e}")
        await manager.broadcast({
            "type": "log",
            "data": {
                "agent": "System",
                "message": f"[FATAL ERROR]: 任务执行遭遇崩溃: {str(e)}"
            }
        })

# 静态文件托管 (存放高颜值 Web 页面前端)
ui_path = os.path.join(os.path.dirname(__file__), "ui")
if os.path.exists(ui_path):
    app.mount("/static", StaticFiles(directory=os.path.join(ui_path, "static")), name="static")

@app.get("/")
def read_root():
    index_file = os.path.join(ui_path, "index.html")
    if os.path.exists(index_file):
        return FileResponse(index_file)
    return HTMLResponse("<h1>UI Path not found. Set up app/ui/index.html.</h1>")
