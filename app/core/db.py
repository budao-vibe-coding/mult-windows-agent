import sqlite3
import json
from datetime import datetime
from typing import Optional, List, Dict, Any
from app.core.config import get_config

def get_db_connection():
    config = get_config()
    conn = sqlite3.connect(config.server.db_path)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # 1. 任务白名单表 (记录调试完成的任务)
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS task_whitelist (
        task_name TEXT PRIMARY KEY,
        is_debugged INTEGER DEFAULT 0,
        dag_signature TEXT,
        registered_at TEXT
    )
    """)
    # 动态为已有的数据库升级，添加 user_command 字段
    try:
        cursor.execute("ALTER TABLE task_whitelist ADD COLUMN user_command TEXT")
    except sqlite3.OperationalError:
        pass
    
    # 2. 已核准动作表 (记录单个已允许执行的具体动作)
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS approved_actions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        task_name TEXT,
        action_type TEXT,
        action_signature TEXT,
        approved_at TEXT,
        UNIQUE(task_name, action_type, action_signature)
    )
    """)

    # 3. 定时任务表
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS scheduled_tasks (
        id TEXT PRIMARY KEY,
        task_name TEXT,
        user_command TEXT,
        schedule_type TEXT, -- 'interval' 或 'daily'
        schedule_value TEXT, -- 间隔秒数 或 'HH:MM'
        status TEXT DEFAULT 'active', -- 'active' 或 'paused'
        last_run TEXT,
        next_run TEXT
    )
    """)
    
    conn.commit()
    conn.close()

def save_schedule(id: str, task_name: str, user_command: str, schedule_type: str, schedule_value: str, status: str = "active") -> None:
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
    INSERT INTO scheduled_tasks (id, task_name, user_command, schedule_type, schedule_value, status)
    VALUES (?, ?, ?, ?, ?, ?)
    ON CONFLICT(id) DO UPDATE SET
        task_name=excluded.task_name,
        user_command=excluded.user_command,
        schedule_type=excluded.schedule_type,
        schedule_value=excluded.schedule_value,
        status=excluded.status
    """, (id, task_name, user_command, schedule_type, schedule_value, status))
    conn.commit()
    conn.close()

def get_all_schedules() -> List[Dict[str, Any]]:
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM scheduled_tasks")
    rows = cursor.fetchall()
    conn.close()
    return [dict(r) for r in rows]

def delete_schedule(id: str) -> None:
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM scheduled_tasks WHERE id = ?", (id,))
    conn.commit()
    conn.close()

def update_schedule_runs(id: str, last_run: str, next_run: str) -> None:
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
    UPDATE scheduled_tasks SET last_run = ?, next_run = ? WHERE id = ?
    """, (last_run, next_run, id))
    conn.commit()
    conn.close()

def register_task(task_name: str, is_debugged: bool = True, dag_signature: str = "", user_command: str = "") -> None:
    conn = get_db_connection()
    cursor = conn.cursor()
    now = datetime.now().isoformat()
    cursor.execute("""
    INSERT INTO task_whitelist (task_name, is_debugged, dag_signature, registered_at, user_command)
    VALUES (?, ?, ?, ?, ?)
    ON CONFLICT(task_name) DO UPDATE SET
        is_debugged=excluded.is_debugged,
        dag_signature=excluded.dag_signature,
        registered_at=excluded.registered_at,
        user_command=excluded.user_command
    """, (task_name, 1 if is_debugged else 0, dag_signature, now, user_command))
    conn.commit()
    conn.close()

def is_task_debugged(task_name: str) -> bool:
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT is_debugged FROM task_whitelist WHERE task_name = ?", (task_name,))
    row = cursor.fetchone()
    conn.close()
    if row:
        return bool(row["is_debugged"])
    return False

def add_approved_action(task_name: str, action_type: str, action_signature: str) -> None:
    conn = get_db_connection()
    cursor = conn.cursor()
    now = datetime.now().isoformat()
    try:
        cursor.execute("""
        INSERT OR IGNORE INTO approved_actions (task_name, action_type, action_signature, approved_at)
        VALUES (?, ?, ?, ?)
        """, (task_name, action_type, action_signature, now))
        conn.commit()
    finally:
        conn.close()

def is_action_approved(task_name: str, action_type: str, action_signature: str) -> bool:
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
    SELECT 1 FROM approved_actions 
    WHERE task_name = ? AND action_type = ? AND action_signature = ?
    """, (task_name, action_type, action_signature))
    row = cursor.fetchone()
    conn.close()
    return row is not None

def get_whitelist_tasks() -> List[Dict[str, Any]]:
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT task_name, is_debugged, registered_at, user_command FROM task_whitelist")
    rows = cursor.fetchall()
    conn.close()
    return [dict(r) for r in rows]
