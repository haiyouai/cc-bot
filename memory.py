"""凌夏记忆模块 v2 — SQLite长期记忆 + JSON缓存 + 自动萃取 + 对话摘要"""
import json, os, sqlite3, time, re
from datetime import datetime

HOME = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(HOME, "lingxia.db")

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    uid TEXT PRIMARY KEY,
    name TEXT DEFAULT '',
    username TEXT DEFAULT '',
    first_seen REAL DEFAULT (strftime('%s','now')),
    notes TEXT DEFAULT '',
    preferences TEXT DEFAULT '{}'
);
CREATE TABLE IF NOT EXISTS conversations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    uid TEXT NOT NULL,
    role TEXT NOT NULL,
    content TEXT NOT NULL,
    timestamp REAL DEFAULT (strftime('%s','now')),
    chat_type TEXT DEFAULT 'private',
    chat_id TEXT DEFAULT ''
);
CREATE TABLE IF NOT EXISTS knowledge (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    fact TEXT UNIQUE NOT NULL,
    source TEXT DEFAULT '',
    confidence REAL DEFAULT 0.5,
    created REAL DEFAULT (strftime('%s','now')),
    updated REAL DEFAULT (strftime('%s','now')),
    tags TEXT DEFAULT '[]'
);
CREATE TABLE IF NOT EXISTS groups (
    chat_id TEXT PRIMARY KEY,
    title TEXT DEFAULT '',
    last_active REAL DEFAULT (strftime('%s','now')),
    notes TEXT DEFAULT '',
    is_watched INTEGER DEFAULT 0
);
CREATE TABLE IF NOT EXISTS summaries (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    context_key TEXT NOT NULL,
    summary TEXT NOT NULL,
    msg_count INTEGER DEFAULT 0,
    created REAL DEFAULT (strftime('%s','now'))
);
CREATE INDEX IF NOT EXISTS idx_conv_uid ON conversations(uid);
CREATE INDEX IF NOT EXISTS idx_conv_time ON conversations(timestamp);
CREATE INDEX IF NOT EXISTS idx_know_tags ON knowledge(tags);
CREATE INDEX IF NOT EXISTS idx_summaries_key ON summaries(context_key);
"""

import threading

_db_local = threading.local()


def _get_db():
    """获取线程本地数据库连接（复用）"""
    if not hasattr(_db_local, 'conn') or _db_local.conn is None:
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA busy_timeout=5000")
        _db_local.conn = conn
    return _db_local.conn


def _close_db():
    """关闭当前线程的数据库连接"""
    if hasattr(_db_local, 'conn') and _db_local.conn:
        try:
            _db_local.conn.close()
        except:
            pass
        _db_local.conn = None

def _init_db():
    conn = _get_db()
    conn.executescript(SCHEMA)
    conn.commit()
    conn.close()

class MemoryManager:
    def __init__(self):
        _init_db()
        self.memory_path = os.path.join(HOME, "memory.json")
        self.data = self._load()

    def _load(self):
        try:
            with open(self.memory_path, encoding="utf-8") as f:
                return json.load(f)
        except:
            return {"posts": [], "chats": {}, "insights": []}

    def _save(self):
        with open(self.memory_path, "w", encoding="utf-8") as f:
            json.dump(self.data, f, ensure_ascii=False, indent=2)

    def get_recent_posts(self, n=5):
        return [p["content"][:80] for p in self.data["posts"][-n:]]

    def save_post(self, content):
        self.data["posts"].append({"content": content, "time": str(datetime.now())})
        if len(self.data["posts"]) > 100:
            self.data["posts"] = self.data["posts"][-80:]
        self._save()

    def get_chat_history(self, uid, limit=50):
        """获取对话历史（默认50条）"""
        return self.data["chats"].get(str(uid), [])[-limit:]

    def get_conversation_summary(self, context_key):
        """获取对话摘要"""
        try:
            conn = _get_db()
            row = conn.execute(
                "SELECT summary, msg_count FROM summaries WHERE context_key=? ORDER BY id DESC LIMIT 1",
                (context_key,)
            ).fetchone()
            conn.close()
            if row:
                return dict(row)
            return None
        except:
            return None

    def save_chat(self, uid, user_msg, reply, chat_type="private"):
        """保存对话到JSON缓存 + SQLite，自动触发摘要"""
        uid = str(uid)
        if uid not in self.data["chats"]:
            self.data["chats"][uid] = []
        self.data["chats"][uid].append({"role": "user", "content": user_msg})
        self.data["chats"][uid].append({"role": "assistant", "content": reply})
        if len(self.data["chats"][uid]) > 200:
            self.data["chats"][uid] = self.data["chats"][uid][-180:]
        self._save()
        self._db_save_chat(uid, user_msg, reply, chat_type)
        # 自动萃取
        self._auto_extract(uid, user_msg, reply)

    def _needs_summary(self, context_key):
        """检查是否需要生成新摘要（每50条消息生成一次）"""
        try:
            conn = _get_db()
            row = conn.execute(
                "SELECT msg_count FROM summaries WHERE context_key=? ORDER BY id DESC LIMIT 1",
                (context_key,)
            ).fetchone()
            conn.close()
            current_count = row["msg_count"] if row else 0
            return current_count == 0
        except:
            return False

    def save_summary(self, context_key, summary, msg_count):
        """保存对话摘要"""
        try:
            conn = _get_db()
            conn.execute(
                "INSERT INTO summaries (context_key, summary, msg_count) VALUES (?,?,?)",
                (context_key, summary[:500], msg_count)
            )
            conn.commit()
            conn.close()
        except:
            pass

    def save_insight(self, text):
        """保存洞察，限制数量避免噪声"""
        self.data["insights"].append({"text": text, "time": str(datetime.now())})
        if len(self.data["insights"]) > 300:
            self.data["insights"] = self.data["insights"][-200:]
        self._save()
        self._db_save_knowledge(text)

    def get_recent_insights(self, limit=8):
        """获取最近的洞察（返回完整文本）"""
        items = self.data["insights"][-limit:]
        return [i["text"] for i in items]

    # ── SQLite ──

    def _db_save_chat(self, uid, user_msg, reply, chat_type="private"):
        try:
            conn = _get_db()
            now = time.time()
            conn.execute("INSERT INTO conversations (uid, role, content, timestamp, chat_type) VALUES (?,?,?,?,?)",
                         (str(uid), "user", user_msg[:1000], now, chat_type))
            conn.execute("INSERT INTO conversations (uid, role, content, timestamp, chat_type) VALUES (?,?,?,?,?)",
                         (str(uid), "assistant", reply[:1000], now, chat_type))
            conn.commit()
            conn.close()
        except:
            pass

    def _db_save_knowledge(self, text):
        try:
            conn = _get_db()
            conn.execute(
                "INSERT OR IGNORE INTO knowledge (fact, source, confidence, tags) VALUES (?,?,?,?)",
                (text[:500], "凌夏自动记录", 0.5, '["auto"]')
            )
            conn.commit()
            conn.close()
        except:
            pass

    def _auto_extract(self, uid, user_msg, reply):
        """从对话中萃取有价值的信息"""
        triggers = ["教程","经验","方法","技巧","项目","干货","攻略","内幕","避坑",
                     "注意","重要","记住","学会","发现","分享","推荐","踩坑","踩雷",
                     "我是","我叫","我喜欢","我在","我做","我的"]
        if any(t in user_msg for t in triggers):
            self._db_save_knowledge(f"用户: {user_msg[:200]}")

    def db_search_knowledge(self, keyword="", limit=10):
        conn = _get_db()
        if keyword:
            rows = conn.execute(
                "SELECT fact, source, confidence, tags, created FROM knowledge WHERE fact LIKE ? ORDER BY confidence DESC, updated DESC LIMIT ?",
                (f"%{keyword}%", limit)
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT fact, source, confidence, tags, created FROM knowledge ORDER BY updated DESC LIMIT ?",
                (limit,)
            ).fetchall()
        conn.close()
        return [dict(r) for r in rows]

    def db_search_conversations(self, uid=None, keyword="", limit=10):
        conn = _get_db()
        if uid and keyword:
            rows = conn.execute(
                "SELECT role, content, timestamp FROM conversations WHERE uid=? AND content LIKE ? ORDER BY id DESC LIMIT ?",
                (str(uid), f"%{keyword}%", limit)
            ).fetchall()
        elif uid:
            rows = conn.execute(
                "SELECT role, content, timestamp FROM conversations WHERE uid=? ORDER BY id DESC LIMIT ?",
                (str(uid), limit)
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT role, content, timestamp, chat_type, chat_id FROM conversations WHERE content LIKE ? ORDER BY id DESC LIMIT ?",
                (f"%{keyword}%", limit)
            ).fetchall()
        conn.close()
        return [dict(r) for r in rows]

    def db_save_user_info(self, uid, name="", username="", notes=""):
        conn = _get_db()
        existing = conn.execute("SELECT * FROM users WHERE uid=?", (str(uid),)).fetchone()
        if existing:
            updates = {}
            if name: updates["name"] = name
            if username: updates["username"] = username
            if notes: updates["notes"] = notes
            if updates:
                sets = ", ".join(f"{k}=?" for k in updates)
                vals = list(updates.values()) + [str(uid)]
                conn.execute(f"UPDATE users SET {sets} WHERE uid=?", vals)
        else:
            conn.execute("INSERT INTO users (uid, name, username, notes) VALUES (?,?,?,?)",
                         (str(uid), name, username, notes))
        conn.commit()
        conn.close()

    def db_get_user_info(self, uid):
        conn = _get_db()
        row = conn.execute("SELECT * FROM users WHERE uid=?", (str(uid),)).fetchone()
        conn.close()
        return dict(row) if row else None

    def db_save_fact(self, fact, source="", tags=None):
        conn = _get_db()
        now = time.time()
        tags_json = json.dumps(tags or ["manual"])
        conn.execute(
            "INSERT OR REPLACE INTO knowledge (fact, source, confidence, updated, tags) VALUES (?,?,?,?,?)",
            (fact[:500], source, 0.8, now, tags_json)
        )
        conn.commit()
        conn.close()

    def db_get_recent_facts(self, limit=10):
        conn = _get_db()
        rows = conn.execute(
            "SELECT fact, source, confidence, tags, created FROM knowledge ORDER BY updated DESC LIMIT ?",
            (limit,)
        ).fetchall()
        conn.close()
        return [dict(r) for r in rows]

    def db_get_profile_summary(self, uid):
        conn = _get_db()
        user = conn.execute("SELECT * FROM users WHERE uid=?", (str(uid),)).fetchone()
        recent = conn.execute(
            "SELECT content FROM conversations WHERE uid=? ORDER BY id DESC LIMIT 3",
            (str(uid),)
        ).fetchall()
        facts = []
        if user:
            notes = dict(user).get("notes", "")
            if notes:
                facts = conn.execute(
                    "SELECT fact FROM knowledge WHERE fact LIKE ? ORDER BY updated DESC LIMIT 3",
                    (f"%{notes[:20]}%",)
                ).fetchall()
        conn.close()
        return {
            "user": dict(user) if user else None,
            "recent": [r["content"] for r in reversed(recent)],
            "facts": [r["fact"] for r in facts],
        }
