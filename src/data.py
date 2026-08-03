import sqlite3
from typing import List
from .comm import *

def _connect(db_path: str) -> sqlite3.Connection:
    """Open SQLite with WAL + busy_timeout (P0-2 concurrent safety)."""
    conn = sqlite3.connect(db_path, timeout=30)
    try:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA busy_timeout=5000")
    except sqlite3.Error as e:
        logger.warning(f"sqlite pragma: {e}")
    return conn


def initialize_db(db_path: str, table_name: str):
    logger.debug(f"db_path: {db_path}, table_name: {table_name}")

    """初始化数据库，创建表"""
    conn = _connect(db_path)
    cursor = conn.cursor()
    
    # 创建表（如果不存在）
    cursor.execute(f'''
    CREATE TABLE IF NOT EXISTS {table_name} (
        bvid TEXT PRIMARY KEY
    )
    ''')

    if table_name == "MissAV":
        cursor.execute(f"PRAGMA table_info({table_name})")
        existing = {row[1] for row in cursor.fetchall()}
        columns = {
            "title": "TEXT",
            "title_jp": "TEXT",
            "actresses": "TEXT",
            "genres": "TEXT",
            "release_date": "TEXT",
            "duration": "TEXT",
            "source": "TEXT",
            "found_date": "TEXT",
            "add_date": "TEXT",
        }
        for name, column_type in columns.items():
            if name not in existing:
                cursor.execute(f"ALTER TABLE {table_name} ADD COLUMN {name} {column_type}")
    
    conn.commit()
    conn.close()

def batch_insert_bvids(bvid_list: list[str], db_path: str, table_name: str):
    """批量插入BVID，自动忽略已存在的"""
    conn = _connect(db_path)
    cursor = conn.cursor()
    
    try:
        # 使用 INSERT OR IGNORE 避免重复插入
        cursor.executemany(
            f'INSERT OR IGNORE INTO {table_name} (bvid) VALUES (?)',
            [(bvid,) for bvid in bvid_list]
        )
        conn.commit()
        logger.info(f"成功插入 {cursor.rowcount}")
    except sqlite3.Error as e:
        logger.error(f"插入BVID时出错: {e}")
        conn.rollback()
    finally:
        conn.close()

def find_in_db(bvid: str, db_path: str, table_name: str) -> bool:
    try:
        # 连接到 SQLite 数据库
        conn = _connect(db_path)
        cursor = conn.cursor()
        # 执行查询
        query = f"SELECT 1 FROM {table_name} WHERE bvid = ? LIMIT 1"
        cursor.execute(query, (bvid,))
        result = cursor.fetchone()
        # 关闭连接
        cursor.close()
        conn.close()
        
        return result is not None
        
    except sqlite3.Error as e:
        print(f"数据库错误: {e}")
        return False
    except Exception as e:
        print(f"发生错误: {e}")
        return False
