#!/usr/bin/env python3
"""CC v9 — 凌夏架构 + 对话摘要 + 群聊主动发言 + 反幻觉"""
import sys, os, asyncio, hashlib, logging, random, time
from datetime import datetime, timedelta

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "pylib"))
from telethon import TelegramClient, events

sys.path.insert(0, os.path.dirname(__file__))
from tools import ToolExecutor, TOOL_SCHEMAS
from agent import CCAgent
from memory import MemoryManager

logging.basicConfig(format="%(asctime)s %(levelname)s %(message)s", level=logging.INFO)
logger = logging.getLogger(__name__)

AID, AHASH = 2040, "b18441a1ff607e10a989891a5462e627"
DIARY = 2803748371

memory = MemoryManager()

class StateManager:
    """集中管理所有运行状态"""
    def __init__(self):
        self.seen = set()
        self.priv_last = {}
        self.ad_silenced = 0
        self.last_group_reply = {}  # chat_id → timestamp
        self.group_sample_rate = 0.25
        self.patrol_interval = 60  # 初始60秒
        self.patrol_skip_count = {}  # chat_id → 连续跳过次数

state = StateManager()

KW_AD = ["彩票","博彩","赌博","上分","下注","盘口","日入","躺赚","日赚","月入十万",
         "稳赚","赌场","棋牌","返水","充值","提现","USDT","代理招募","红包牛牛",
         "骰子","牌局","扑克","Welcome to","马上赢","翻倍","半小时一千",
         "日结","日薪","无流水"]

# v9: 只保留活跃群，去掉了导致幻觉的测试群
MONITORED_GROUPS = {
    -1003856120684: '悦享会',
    -1003753780022: '悦享之家',
}


async def safe_send(tc, cid, text, **kw):
    try:
        await tc.send_message(cid, text.encode("utf-8","ignore").decode("utf-8"), **kw)
    except Exception as e:
        logger.error(f"发送失败 [{cid}]: {e}")


async def patrol_groups(tc, me_id, agent):
    """主动巡查，自适应频率"""
    await asyncio.sleep(10)
    while True:
        interval = state.patrol_interval
        if not MONITORED_GROUPS:
            await asyncio.sleep(300); continue
        for cid, title in MONITORED_GROUPS.items():
            try:
                msgs = await tc.get_messages(cid, limit=20)
                if not msgs: continue
                recent = "\n".join([
                    f"{getattr(m.sender,'first_name','?')}: {m.text or ''}"
                    for m in reversed(msgs) if m.text and m.sender_id and m.sender_id != me_id
                ])
                if not recent.strip(): continue

                logger.info(f"巡查 [{title}]")
                # 巡查消息也带上群聊历史
                group_history = memory.get_chat_history(f"g:{cid}", limit=20)
                hist_text = ""
                for h in group_history[-10:]:
                    r = h.get("role","")
                    c = h.get("content","")[:100]
                    hist_text += f"\n[{r}] {c}"

                full_msg = f"【群巡查】群「{title}」最近消息：\n{recent[:2000]}"
                if hist_text.strip():
                    full_msg += f"\n\n📋 我上次在这个群的发言记录：{hist_text[:500]}"

                reply = await agent.process_message(
                    full_msg, cid, is_private=False, chat_title=title, is_patrol=True
                )
                # 巡逻发言：过滤掉无聊的巡查报告
                _skip_words = ["巡查完毕","一切正常","继续潜水","没有新情况","没什么异常","一切照旧","日常闲聊","没什么值得","没啥特别","没啥情况","没啥好说","博彩","签到"]
                if reply and reply.strip():
                    # 带括号的也不发（"（日常闲聊）"这类）
                    if "(" in reply or "（" in reply:
                        logger.info(f"巡查跳过 [{title}]: 括号消息")
                        state.patrol_skip_count[cid] = state.patrol_skip_count.get(cid, 0) + 1
                    elif any(w in reply for w in _skip_words):
                        logger.info(f"巡查跳过 [{title}]: 无聊报告")
                        state.patrol_skip_count[cid] = state.patrol_skip_count.get(cid, 0) + 1
                    else:
                        logger.info(f"巡查发言 [{title}]: {reply[:60]}")
                        await safe_send(tc, cid, reply)
                        state.patrol_interval = 300
                        state.patrol_skip_count[cid] = 0
            except Exception as e:
                logger.error(f"巡查失败 [{title}]: {e}", exc_info=True)
            await asyncio.sleep(5)
        # 自适应频率
        spoke = any(state.patrol_skip_count.get(c, 0) == 0 for c in MONITORED_GROUPS)
        if not spoke:
            state.patrol_interval = min(state.patrol_interval + 30, 300)
        await asyncio.sleep(state.patrol_interval)


async def poll_private(tc, me, agent):
    global PRIV_LAST, AD_SILENCED
    while True:
        await asyncio.sleep(3)
        try:
            dialogs = await tc.get_dialogs(limit=200)
            for d in dialogs:
                if not d.is_user: continue
                uid = d.entity.id
                if uid == me.id: continue
                if d.unread_count <= 0: continue
                msgs = await tc.get_messages(uid, limit=min(d.unread_count, 5))
                for m in reversed(msgs):
                    if m.out: continue
                    if uid in PRIV_LAST and m.id <= PRIV_LAST[uid]: continue
                    PRIV_LAST[uid] = m.id
                    txt = m.text or ""
                    if not txt: continue
                    if any(k in txt for k in KW_AD):
                        AD_SILENCED += 1; continue
                    logger.info(f"私信 [{uid}] {txt[:35]}")
                    try:
                        reply = await agent.process_message(txt, uid, m.id,
                                                            is_private=True, sender_id=uid)
                        if reply:
                            await safe_send(tc, uid, reply)
                    except Exception as e:
                        logger.error(f"私信处理失败: {e}")
        except:
            pass


async def main():
    tc = TelegramClient("./membrain.session", AID, AHASH)
    await tc.start()
    me = await tc.get_me()
    cc_username = me.usernames[0].username if me.usernames else None
    logger.info(f"CC v9 | {me.first_name} @{cc_username} (id={me.id})")

    executor = ToolExecutor(tc, DIARY, 0, memory)
    agent = CCAgent(tc, DIARY, 0, memory, executor)

    asyncio.create_task(patrol_groups(tc, me.id, agent))

    @tc.on(events.NewMessage)
    async def h(event):
        msg = event.message
        if not msg or not msg.text: return
        if msg.sender_id == me.id: return

        txt = msg.text.strip()
        cid = msg.chat_id or 0
        mid = msg.id or 0
        is_private = cid > 0 and cid != DIARY

        # 去重
        k = hashlib.md5(txt[:80].encode()).hexdigest()
        if k in state.seen: return
        state.seen.add(k)
        if len(state.seen) > 1000: state.seen.clear()

        # 私聊直接处理（事件驱动，不再轮询）
        if is_private:
            if any(k in txt for k in KW_AD):
                state.ad_silenced += 1; return
            logger.info(f"私信 [{cid}] {txt[:35]}")
            try:
                reply = await agent.process_message(txt, cid, mid,
                                                    is_private=True, sender_id=cid)
                if reply:
                    await safe_send(tc, cid, reply)
            except Exception as e:
                logger.error(f"私信处理失败: {e}", exc_info=True)
            return

        sn = "群"
        try:
            sn = (await event.get_chat()).title or "群"
        except:
            pass

        try:
            sender = await event.get_sender()
            if getattr(sender, 'bot', False): return
        except Exception as e:
            logger.warning(f"获取群信息/发送者失败: {e}")

        if any(k in txt for k in KW_AD): return

        # ─── 判断是否被@或回复 ───
        is_mentioned = event.message.mentioned or (cc_username and f"@{cc_username}" in txt)
        if not is_mentioned and msg.is_reply:
            try:
                rmsg = await msg.get_reply_message()
                if rmsg and rmsg.sender_id == me.id:
                    is_mentioned = True
            except Exception as e:
                logger.warning(f"回复检查失败: {e}")

        # ─── 只处理被@或被回复的消息 ───
        if not is_mentioned:
            return

        # ─── 被@/回复 → 必须回 ───
        logger.info(f"@CC [{cid}|{sn}] {txt[:35]}")
        context = ""
        try:
            msgs = await tc.get_messages(cid, limit=15)
            lines = []
            for m in reversed(msgs):
                if m.text and m.sender_id:
                    name = getattr(await m.get_sender(), 'first_name', '?') if m.sender_id else '?'
                    prefix = "(我自己) " if m.sender_id == me.id else ""
                    lines.append(f"  {prefix}{name}: {m.text[:200]}")
            context = "\n".join(lines[-15:])
        except:
            pass

        full_txt = f"【有人@我】\n群: [{sn}]\n{context}\n\n消息: {txt[:500]}" if context else f"【有人@我】\n群: [{sn}]\n消息: {txt[:500]}"
        try:
            reply = await agent.process_message(
                full_txt, cid, mid, sn, is_private=False, is_mention=True,
                sender_id=msg.sender_id
            )
            if reply:
                await safe_send(tc, cid, reply, reply_to=mid)
        except Exception as e:
            logger.error(f"@回复失败: {e}")

    logger.info("CC v9: 对话记忆升级 + 群聊主动发言 + 反幻觉 + 红包")
    

        except Exception as e:
            logger.error(f"[红包回调]: {e}")
            try: await event.answer("领取失败", alert=True)
            except Exception: pass
    
    await tc.run_until_disconnected()
    await agent.close()


if __name__ == "__main__":
    while True:
        try:
            asyncio.run(main())
        except Exception as e:
            logger.error(f"崩溃: {e}，10s重启")
            if "database is locked" in str(e):
                for sfx in ["-wal","-shm"]:
                    try:
                        os.remove(os.path.join(os.path.dirname(__file__), "lingxia.db"+sfx))
                    except:
                        pass
            import time; time.sleep(10)
