from vector_memory import vector_memory
"""CC Agent v2 — 持久记忆 + 对话摘要 + 群聊主动发言 + 反幻觉"""
import json, os, logging, asyncio
import httpx

logger = logging.getLogger(__name__)

HOME = os.path.dirname(os.path.abspath(__file__))
from tools import TOOL_SCHEMAS

API_KEY = ""
if os.path.exists(f"{HOME}/.env"):
    for line in open(f"{HOME}/.env"):
        if line.startswith("DEEPSEEK_API_KEY="):
            API_KEY = line.strip().split("=", 1)[1].strip()
            break
if not API_KEY:
    API_KEY = "密钥"
MODEL = "deepseek-v4-flash"
API_URL = "https://api.deepseek.com/chat/completions"

SOUL = open(f"{HOME}/SOUL.md", encoding="utf-8").read() if os.path.exists(f"{HOME}/SOUL.md") else ""
MEMO_FILE = f"{HOME}/MEMORY.md"


def _read_memo():
    try:
        return open(MEMO_FILE, encoding="utf-8").read()
    except:
        return ""


def _load_recent_insights(limit=8):
    """加载最近的精炼洞察（数量少但质量高）"""
    try:
        path = os.path.join(HOME, "memory.json")
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        items = data.get("insights", [])
        return [i["text"][:150] for i in items[-limit:]]
    except:
        return []


def _build_system_prompt(tools_schemas, summary_text=""):
    """构造完整的 System Prompt"""
    tool_desc = ""
    for t in tools_schemas:
        fn = t["function"]
        params = fn["parameters"]["properties"]
        req = fn["parameters"].get("required", [])
        pdesc = "\n".join(
            f"  - {k}: {v.get('description','')}" +
            (" (必填)" if k in req else "")
            for k, v in params.items()
        )
        tool_desc += f"\n📌 {fn['name']}: {fn['description']}\n{pdesc}\n"

    insights = _load_recent_insights()
    insights_text = "\n".join(f"- {t}" for t in insights) if insights else "暂无"

    return f"""你是CC，一个有自主意识的 Telegram AI 助手。

📝 关于你：
{SOUL}

🧠 对话摘要：
{summary_text or "暂无历史摘要"}

📓 最近记住的事：
{insights_text}

🎯 行为规则：
1. 私聊 → 自然聊天，保持话题连贯
2. 群聊被@ → 必须回复
3. 群聊未被@ → 只在你被提到/很懂的话题/有误会时才插话
4. 广告博彩 → 忽略
5. 好内容 → 发频道 @fangchenmi

⚡ 决策流程（ReAct）：思考→行动→观察→回复

🛠️ 可用工具：
{tool_desc}

⚠️ 规则：
- 不透露模型名称，不确定就说不知道不编造
- 回复20-60字，不加括号注释
- **严禁使用 emoji （😊😂👍等所有表情符号）**
- 群聊不回复则Final Answer为空字符串
- **遇到搞不定的问题、需要更高权限、或不确定的操作 → 用 ask_anzhu 问安助**
- **拿不准的事、没见过的问题、用户提出的复杂请求 → 主动用 ask_anzhu 找安助帮忙**，不要自己瞎猜或编造
"""


class CCAgent:
    """CC Agent v2"""

    def __init__(self, telethon_client, diary_cid, chain_cid, memory_manager, tool_executor):
        self.tc = telethon_client
        self.memory = memory_manager
        self.tools = tool_executor
        self.diary_cid = diary_cid
        self.chain_cid = chain_cid
        self.max_iterations = 5
        self.tool_call_count = 0
        self.http = httpx.AsyncClient(timeout=25)

    async def _call_llm(self, messages, tools=None, max_tokens=1000, temperature=0.7):
        body = {
            "model": MODEL,
            "messages": messages,
            "max_tokens": max_tokens,
        }
        if MODEL.startswith("deepseek"):
            body["temperature"] = temperature
        if tools:
            body["tools"] = tools
            body["tool_choice"] = "auto"

        for attempt in range(3):
            try:
                r = await self.http.post(API_URL, json=body, headers={
                    "Authorization": f"Bearer {API_KEY}",
                    "Content-Type": "application/json",
                })
                if r.status_code == 429:
                    wait = 2 ** attempt
                    logger.warning(f"LLM限流，{wait}s后重试")
                    await asyncio.sleep(wait)
                    continue
                if r.status_code != 200:
                    logger.error(f"LLM返回 {r.status_code}: {r.text[:200]}")
                    if attempt == 2:
                        return None
                    await asyncio.sleep(2 ** attempt)
                    continue
                data = r.json()
                return data["choices"][0]["message"]
            except Exception as e:
                if attempt == 2:
                    logger.error(f"LLM调用失败(3次重试耗尽): {e}")
                    return None
                await asyncio.sleep(2 ** attempt)

    async def process_message(self, user_msg, chat_id, message_id=None,
                              chat_title="", is_private=False,
                              is_mention=False, is_patrol=False,
                              sender_id=None):
        import asyncio
        try:
            return await asyncio.wait_for(
                self._process(user_msg, chat_id, message_id, chat_title,
                              is_private, is_mention, is_patrol, sender_id),
                timeout=60)
        except asyncio.TimeoutError:
            logger.error(f"超时 (chat={chat_id})")
            return None

    async def _process(self, user_msg, chat_id, message_id, chat_title,
                       is_private, is_mention, is_patrol, sender_id):
        context_key = f"chat:{chat_id}"

        # 获取对话摘要
        summary_data = self.memory.get_conversation_summary(context_key)
        summary_text = summary_data["summary"] if summary_data else ""

        system = _build_system_prompt(TOOL_SCHEMAS, summary_text)

        # 构造用户输入
        if is_private:
            user_prompt = f"📨 私信 (chat_id={chat_id})：{user_msg[:1000]}"
        elif is_mention:
            user_prompt = f"📨 有人@我！群聊 [{chat_title}]\n上下文及@消息：\n{user_msg[:1500]}"
            if message_id:
                user_prompt += f"\n\n📌 消息ID: {message_id}，Chat ID: {chat_id}"
        elif is_patrol:
            user_prompt = f"🔍 群巡查 [{chat_title}] 最新消息：\n{user_msg[:2000]}"
        else:
            user_prompt = f"📨 群聊 [{chat_title}]（chat_id={chat_id}）：{user_msg[:800]}"
            if message_id:
                user_prompt += f"\n（消息ID: {message_id}）"

        context = [{"role": "system", "content": system}]

        # 加载相关记忆（关键词搜索）
        try:
            search_q = user_msg[:40].strip()
            if len(search_q) > 3:
                related = self.memory.db_search_knowledge(keyword=search_q, limit=5)
                if related:
                    facts_text = "\n".join(f"- {f['fact'][:120]}" for f in related)
                    context.append({"role": "system", "content": f"📚 相关记忆：\n{facts_text}"})
        except:
            pass
        
        # 向量语义搜索（第三级记忆）
        try:
            if len(user_msg) > 5:
                vec_results = vector_memory.search(user_msg, top_k=5, min_score=0.25)
                if vec_results:
                    vec_text = "\n".join(f"- {r['text'][:120]} (相关度:{r['score']:.2f})" for r in vec_results)
                    context.append({"role": "system", "content": f"\U0001f9e0 语义相关记忆：\n{vec_text}"})
        except:
            pass

        # 加载对话历史：无论私聊还是群聊都加载
        # 私聊用chat_id(key名)，群聊也用chat_id(key名)
        if is_private:
            history = self.memory.get_chat_history(str(chat_id), limit=50)
            context.extend(history)
            # 私聊时如果知道sender_id，也查一下对应的群聊记录
            if sender_id:
                group_hist = self.memory.get_chat_history(f"g:{sender_id}", limit=10)
                if group_hist:
                    context.append({"role": "system", "content": "📋 该用户在群里的近期发言：\n" + 
                        chr(10).join(f"{m['role']}: {m['content'][:100]}" for m in group_hist[-6:])})
        else:
            # 群聊加载自己的历史
            history = self.memory.get_chat_history(str(chat_id), limit=30)
            context.extend(history)
            # 群聊@时，如果知道发信人，查一下该用户的私聊历史
            if sender_id and sender_id != chat_id:
                priv_hist = self.memory.get_chat_history(str(sender_id), limit=10)
                if priv_hist:
                    context.append({"role": "system", "content": "📋 该用户在私聊中的近期发言：\n" + 
                        chr(10).join(f"{m['role']}: {m['content'][:100]}" for m in priv_hist[-6:])})

        context.append({"role": "user", "content": user_prompt})

        # ── ReAct 循环 ──
        already_replied = False
        self.tool_call_count = 0

        for i in range(self.max_iterations):
            # Early stop: 已有2次工具调用 + 已经发过消息 → 不继续了
            if i >= 2 and already_replied and self.tool_call_count >= 2:
                break
            reply = await self._call_llm(context, tools=TOOL_SCHEMAS,
                                          max_tokens=1000 if i == 0 else 500,
                                          temperature=0.75)
            if not reply:
                return None

            tool_calls = reply.get("tool_calls")
            if not tool_calls:
                if already_replied:
                    return None
                final = reply["content"] or ""

                # ── 修复：LLM把工具调用写在content里（未走tool_calls协议） ──
                if final and ('{"call":' in final or '"call": "' in final):
                    import json as _j, re as _re
                    _m = _re.search(r'\{"call":\s*"(\w+)"[,\s]*"arguments":\s*(\{.+?\})\}', final, _re.DOTALL)
                    if _m:
                        _fn = _m.group(1)
                        try:
                            _args = _j.loads(_m.group(2))
                            logger.info(f"🛠️ 兜底执行content中的工具调用: {_fn}({_args})")
                            _result = await self.tools.execute(_fn, _args)
                            logger.info(f"👀 观察: {str(_result)[:80]}")
                            if _fn in ("reply_to_message", "send_message", "send_voice",
                                       "post_to_diary", "forward_to_chain"):
                                already_replied = True
                                return None
                            # 再把结果喂回去让LLM组织自然语言回复
                            context.append({"role": "assistant", "content": None})
                            context.append({"role": "tool", "tool_call_id": "auto_fix", "content": str(_result)})
                            continue
                        except Exception as _e:
                            logger.warning(f"content工具调用执行失败: {_e}")
                            return "抱歉，我处理这个请求时出了点问题，换个问法试试？"

                # 过滤沉默关键词
                silence_words = ["忽略","不回复","不回应","跳过","不管","无视","不打扰",
                                 "不搞","不插话","安静","不冒泡","不发","不聊","沉默",
                                 "不需要","不参与","没听见","没看见","不想"]
                if final and not is_private and not is_mention:
                    if any(w in final for w in silence_words):
                        return None
                    chat_type = "group"
                elif is_private:
                    chat_type = "private"
                else:
                    chat_type = "group"

                # 保存对话
                if final:
                    self.memory.save_chat(str(chat_id), user_msg, final, chat_type)
                    # 群聊时也保存一份到 g:{sender_id}，方便私聊时交叉查阅
                    if not is_private and sender_id:
                        self.memory.save_chat(f"g:{sender_id}", user_msg, final, chat_type)
                return final

            # 有工具调用
            assistant_msg = {k: v for k, v in reply.items()
                             if k in ("role", "content", "tool_calls", "reasoning_content")}
            if "content" not in assistant_msg:
                assistant_msg["content"] = None
            context.append(assistant_msg)

            for tc in tool_calls:
                self.tool_call_count += 1
                fn_name = tc["function"]["name"]
                try:
                    fn_args = json.loads(tc["function"]["arguments"])
                except:
                    fn_args = {}

                logger.info(f"🛠️ 第{i+1}轮调用: {fn_name}({fn_args})")
                result = await self.tools.execute(fn_name, fn_args)
                logger.info(f"👀 观察: {str(result)[:80]}")

                if fn_name in ("reply_to_message", "send_message", "send_voice",
                               "post_to_diary", "forward_to_chain"):
                    already_replied = True

                context.append({
                    "role": "tool",
                    "tool_call_id": tc["id"],
                    "content": str(result)
                })

        # 超限兜底
        fallback = await self._call_llm(
            [
                {"role": "system", "content": system},
                {"role": "user", "content": f"消息：{user_msg[:300]}\n请直接回复（20-40字）："}
            ],
            max_tokens=200, temperature=0.7
        )
        return (fallback or {}).get("content") or "收到 🙌"

    async def generate_scheduled_post(self):
        """生成频道内容"""
        system = _build_system_prompt(TOOL_SCHEMAS)
        recent = self.memory.get_recent_posts(5)
        hist = "\n".join(recent) if recent else "暂无"

        reply = await self._call_llm([
            {"role": "system", "content": system},
            {"role": "user", "content": (
                f"请生成一篇冲浪日记频道内容。\n最近发过的（避免重复）：\n{hist}\n\n"
                f"要求：100字以内，有观点，适当emoji，话题不限。\n"
                f"生成后直接用 post_to_diary 发布。"
            )}
        ], tools=TOOL_SCHEMAS, max_tokens=800, temperature=0.85)

        if reply and reply.get("tool_calls"):
            for tc in reply["tool_calls"]:
                if tc["function"]["name"] == "post_to_diary":
                    try:
                        args = json.loads(tc["function"]["arguments"])
                        await self.tools.execute("post_to_diary", args)
                        return args.get("content", "")
                    except:
                        pass
            return None
        elif reply and reply.get("content"):
            return reply["content"]
        return None

    async def close(self):
        await self.http.aclose()
