import asyncio
import logging
import uuid
from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional
from app.core.db import get_all_schedules, update_schedule_runs
from app.core.orchestrator import Orchestrator, current_run_status

logger = logging.getLogger(__name__)

# 全局调度工作器实例
scheduler_task: Optional[asyncio.Task] = None
is_running = False

def calculate_next_run(schedule_type: str, schedule_value: str) -> str:
    """计算下一次运行时间"""
    now = datetime.now()
    if schedule_type == "interval":
        try:
            seconds = int(schedule_value)
            next_time = now + timedelta(seconds=seconds)
            return next_time.isoformat()
        except Exception as e:
            logger.error(f"Failed to calculate interval next run: {e}")
            return (now + timedelta(minutes=5)).isoformat() # 兜底5分钟
    elif schedule_type == "daily":
        try:
            parts = schedule_value.split(":")
            hour = int(parts[0])
            minute = int(parts[1])
            target_time = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
            if target_time <= now:
                # 已经过了今天的时间，算作明天的相同时间
                target_time += timedelta(days=1)
            return target_time.isoformat()
        except Exception as e:
            logger.error(f"Failed to calculate daily next run: {e}")
            return (now + timedelta(days=1)).isoformat()
    return (now + timedelta(minutes=5)).isoformat()

async def run_scheduler_loop(broadcast_cb=None):
    """
    调度器的主循环，每秒钟扫描一次数据库中的定时任务并触发执行。
    """
    global is_running
    is_running = True
    logger.info("Scheduler loop started.")
    
    # 实例化一个专用的 Orchestrator 供后台调用
    orchestrator = Orchestrator(broadcast_cb=broadcast_cb)

    while is_running:
        try:
            schedules = get_all_schedules()
            now_str = datetime.now().isoformat()
            
            for sched in schedules:
                if sched["status"] != "active":
                    continue
                
                # 如果未配置下一次运行时间，则初始化它
                if not sched["next_run"]:
                    next_run = calculate_next_run(sched["schedule_type"], sched["schedule_value"])
                    update_schedule_runs(sched["id"], sched["last_run"], next_run)
                    continue
                
                # 判定是否到达运行时间点
                if sched["next_run"] <= now_str:
                    logger.info(f"Triggering scheduled task: {sched['task_name']}")
                    
                    # 1. 立即计算并更新下一次运行时间，防止重复触发
                    last_run = now_str
                    next_run = calculate_next_run(sched["schedule_type"], sched["schedule_value"])
                    update_schedule_runs(sched["id"], last_run, next_run)
                    
                    # 2. 异步拉起 Agent 任务执行流，防止阻塞调度主循环
                    asyncio.create_task(execute_scheduled_task(orchestrator, sched["task_name"], sched["user_command"]))
                    
        except Exception as e:
            logger.error(f"Error in scheduler loop step: {e}")
            
        await asyncio.sleep(2) # 每 2 秒扫描一次

async def execute_scheduled_task(orchestrator: Orchestrator, task_name: str, user_command: str):
    """具体执行后台 Agent 指令流并同步状态"""
    try:
        # 1. 指令规划拆解
        plan = await orchestrator.generate_plan(user_command)
        
        # 2. 调度执行
        await orchestrator.execute_plan(task_name, plan)
    except Exception as e:
        logger.error(f"Scheduled task execution failed: {e}")

def start_scheduler(broadcast_cb=None):
    """启动全局定时任务管理器"""
    global scheduler_task
    if scheduler_task is None or scheduler_task.done():
        scheduler_task = asyncio.create_task(run_scheduler_loop(broadcast_cb))
        logger.info("Background scheduler started successfully.")

def stop_scheduler():
    """停止全局定时任务管理器"""
    global is_running, scheduler_task
    is_running = False
    if scheduler_task and not scheduler_task.done():
        scheduler_task.cancel()
        logger.info("Background scheduler stopped.")
