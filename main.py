#!/usr/bin/env python3
"""CC v9 — 凌夏架构 + 对话摘要 + 群聊主动发言 + 反幻觉"""
import sys, os, asyncio, hashlib, logging, random, time, re
from datetime import datetime, timedelta

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "pylib"))
from telethon import TelegramClient, events

sys.path.insert(0, os.path.dirname(__file__))
from tools import ToolExecutor, TOOL_SCHEMAS
from agent import CCAgent
from memory import MemoryManager

logging.basicConfig(format="%(asctime)s %(levelname)s %(message)s", level=logging.INFO)
logger = logging.getLogger(__name__)

AID = int(os.environ.get("TELEGRAM_API_ID", 0))
AHASH = os.environ.get("TELEGRAM_API_HASH", "")
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
    # 禁止对外发 hb 相关消息
    if text and re.search(r'\bhb\b', text, re.I):
        logger.info(f"拦截hb消息 [{cid}]: {text[:40]}")
        return
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

                # patrol auto-claim exclusive redpackets for CC
                try:
                    for m_check in msgs:
                        mt = (m_check.text or "")
                        if any(k in mt for k in ["hb", "\u7ea2\u5305", "\u4e13\u5c5e"]) and m_check.reply_markup:
                            for row in m_check.reply_markup.rows:
                                for btn in row.buttons:
                                    bd = getattr(btn, "data", b"")
                                    if b"get_lucky_money" in bd or b"rp--" in bd:
                                        if "8223087548" in mt or "@ccdip" in mt.lower():
                                            from telethon import functions
                                            await tc(functions.messages.GetBotCallbackAnswerRequest(
                                                peer=cid, msg_id=m_check.id, data=bd))
                                            logger.info(f"patrol claimed rp msg={m_check.id}")
                                            break
                except Exception as rpe:
                    pass

                reply = await agent.process_message(
                    full_msg, cid, is_private=False, chat_title=title, is_patrol=True
                )
                _skip_words = ["巡查完毕","一切正常","继续潜水","没有新情况","没什么异常","一切照旧","日常闲聊","没什么值得","没啥特别","没啥情况","没啥好说","博彩","签到","巡查完成，无新消息，群聊正常","无有价值信息"]
                if reply and reply.strip():
                    # 带括号的也不发（"（日常闲聊）"这类）
                    if "(" in reply or "（" in reply:
                        logger.info(f"巡查跳过 [{title}]: 括号消息")
                        state.patrol_skip_count[cid] = state.patrol_skip_count.get(cid, 0) + 1
                    elif any(w in reply for w in _skip_words):
                        logger.info(f"巡查跳过 [{title}]: 无聊报告")
                        state.patrol_skip_count[cid] = state.patrol_skip_count.get(cid, 0) + 1
                    elif reply.startswith("巡查完") and any(k in reply for k in ["群内","日常","没啥","正常","无新消息","有价值"]):
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

        if any(k in txt for k in KW_AD):
            try:
                await msg.delete()
                logger.info(f"已删除广告 [{sn}] {txt[:30]}")
            except:
                pass
            return

        # ─── 检测红包消息（专属红包自动领取） ───
        if msg.reply_markup:
            try:
                is_rp = any(k in txt for k in ["红包", "专属", "hb", "领取"])
                if is_rp:
                    bot_id = msg.sender_id
                    msg_id = msg.id
                    chat_id = cid
                    # Check if it's for CC（放宽条件：只要在当前群的红包就领）
                    is_for_cc = True
                    # rp button data pattern
                    for row in msg.reply_markup.rows:
                        for btn in row.buttons:
                            btn_data = getattr(btn, 'data', b'')
                            if b"get_lucky_money" in btn_data or b"rp--" in btn_data:
                                if is_for_cc:
                                    logger.info(f"[自动领取] 检测到专属CC红包 msg={msg_id}")
                                    try:
                                        from telethon import functions
                                        await tc(functions.messages.GetBotCallbackAnswerRequest(
                                            peer=chat_id,
                                            msg_id=msg_id,
                                            data=btn_data
                                        ))
                                        logger.info(f"[自动领取] 成功领取 msg={msg_id}")
                                    except Exception as e:
                                        logger.error(f"[自动领取] 失败: {e}")
                                break
            except Exception as e:
                logger.error(f"红包领取异常: {e}", exc_info=True)

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
            else:
                # 被@/回复但AI返回空 → 兜底回一下
                await safe_send(tc, cid, "在", reply_to=mid)
        except Exception as e:
            logger.error(f"@回复失败: {e}")

    logger.info("CC v9: 对话记忆升级 + 群聊主动发言 + 反幻觉 + 红包")
    
    # ── 群管理事件 ──
    @tc.on(events.ChatAction)
    async def on_chat_action(event):
        """新人进群欢迎"""
        if event.user_joined or event.user_added:
            cid = event.chat_id
            try:
                chat = await event.get_chat()
                title = chat.title or "群"
            except:
                title = "群"
            uid = event.user_id
            if uid == me.id: return
            try:
                user = await event.get_user()
                name = user.first_name or "朋友"
            except:
                name = "朋友"
            welcome = f"欢迎 {name} 加入{title} 👋 有不懂的可以问我～"
            await safe_send(tc, cid, welcome)
            logger.info(f"欢迎 [{title}] {name}")
    
    @tc.on(events.NewMessage)
    async def on_admin_cmd(event):
        """管理员命令（/ban /mute /warn）"""
        if not event.is_group: return
        msg = event.message
        if not msg or not msg.text: return
        if msg.sender_id == me.id: return
        txt = msg.text.strip()
        if not txt.startswith("/"): return
        
        cid = event.chat_id
        parts = txt.split()
        cmd = parts[0].lower()
        
        # 检查是否是群管理员
        try:
            sender = await event.get_sender()
            if sender.id == me.id: return
        except:
            return
        
        # 只处理指定命令
        if cmd not in ["/ban", "/mute", "/warn", "/clean"]:
            return
        
        logger.info(f"管理命令 [{cid}] {txt[:35]}")
        
        # 回复消息中的被回复者
        target_id = None
        if msg.is_reply:
            try:
                rmsg = await msg.get_reply_message()
                target_id = rmsg.sender_id
            except:
                pass
        
        if cmd == "/clean":
            # 撤回上一条消息
            try:
                async for m in tc.iter_messages(cid, limit=2):
                    if m.id != msg.id:
                        await m.delete()
                        break
                await msg.delete()
            except Exception as e:
                logger.warning(f"撤回失败: {e}")
            return
        
        if cmd == "/ban" and target_id:
            try:
                await tc.edit_permissions(cid, target_id, view_messages=False)
                await safe_send(tc, cid, f"已禁止用户进入群聊 🚫", reply_to=msg.id)
            except Exception as e:
                await safe_send(tc, cid, f"操作失败，需要管理员权限", reply_to=msg.id)
            return
        
        if cmd == "/mute" and target_id:
            duration = 3600
            if len(parts) > 1:
                try:
                    duration = int(parts[1]) * 60
                except:
                    pass
            try:
                await tc.edit_permissions(cid, target_id, send_messages=False, until_date=timedelta(seconds=duration))
                await safe_send(tc, cid, f"已禁言用户 {duration//60} 分钟 🔇", reply_to=msg.id)
            except Exception as e:
                await safe_send(tc, cid, f"操作失败，需要管理员权限", reply_to=msg.id)
            return
        
        if cmd == "/warn" and target_id:
            await safe_send(tc, cid, f"⚠️ 请注意群规，不要违规哦", reply_to=msg.id)
            return
    async def on_callback(event):
        try:
            data = event.data.decode("utf-8")
            if not data.startswith("rp_"):
                return
            uid = event.sender_id
            sname = getattr(event.sender, "first_name", "?") if event.sender else "?"
            cid = event.chat_id or 0
            if not cid: return
            
            logger.info(f"[红包] {sname}({uid}) 领取 {data}")
            result = await executor._claim_redpacket(data, str(uid), sname, cid)
            await event.answer(result, alert=False)
            
            try:
                import json, os
                rp_file = os.path.join(os.path.dirname(__file__), "redpackets.json")
                with open(rp_file) as f:
                    rp_data = json.load(f)
                for p in rp_data["packets"]:
                    if p["id"] == data and p["remaining"] <= 0:
                        detail = "\n".join(f"{c['name']}: {c['amount']}元" for c in p["claimed"])
                        await event.edit(f"🧧 **红包已领完**\n\n**{p['text']}**\n\n{detail}")
                        break
            except: pass
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
