from env_loader import load_env
"""凌夏 — 工具定义与实现（Function Calling 格式）"""
import json, logging, os, urllib.request, sys
from datetime import datetime

_PYEXT = "/tmp/pyext"
if _PYEXT not in sys.path:
    sys.path.insert(0, _PYEXT)

logger = logging.getLogger(__name__)

# ── 钱包配置（TRC20） ──
WALLET_PK = os.environ.get("WALLET_PRIVATE_KEY", "")
WALLET_ADDR = os.environ.get("WALLET_ADDRESS", "")
TRON_RPC = os.environ.get("TRON_RPC_URL", "https://api.trongrid.io")
USDT_CONTRACT = os.environ.get("USDT_CONTRACT", "TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t")
MAX_TX_USDT = int(os.environ.get("MAX_TX_USDT", "1"))
MAX_TX_TRX = int(os.environ.get("MAX_TX_TRX", "10"))


def _tron_rpc(path, body_dict):
    url = TRON_RPC + path
    body = json.dumps(body_dict).encode()
    req = urllib.request.Request(url, data=body, headers={
        "Content-Type": "application/json", "Accept": "application/json",
        "User-Agent": "curl/7.0",
    })
    try:
        resp = urllib.request.urlopen(req, timeout=10)
        return json.loads(resp.read())
    except Exception as e:
        logger.error(f"TRON RPC [{path}]: {e}")
        return None


# ── TRON 辅助函数 ──

def _addr_to_hex(address):
    """TRON base58地址转hex（去掉41前缀，返回20字节hex）"""
    ALPHABET = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"
    n = 0
    for c in address:
        n = n * 58 + ALPHABET.index(c)
    full = format(n, '040x')  # 25 bytes = 50 hex chars: 41 + 20 + 4
    return full[2:42]


def _sign_tron_tx(tx):
    """签名 TRON 交易"""
    try:
        import hashlib
        from eth_keys import keys
        pk = keys.PrivateKey(bytes.fromhex(WALLET_PK))
        raw_hex = tx.get("raw_data_hex", "")
        if not raw_hex:
            return None
        raw_bytes = bytes.fromhex(raw_hex)
        msg_hash = hashlib.sha256(raw_bytes).digest()
        sig = pk.sign_msg_hash(msg_hash)
        sig_bytes = sig.r.to_bytes(32, 'big') + sig.s.to_bytes(32, 'big') + bytes([sig.v])
        tx["signature"] = [sig_bytes.hex()]
        return tx
    except Exception as e:
        logger.error(f"TRON签名失败: {e}")
        return None


TOOL_SCHEMAS = [
    {"type":"function","function":{"name":"send_message","description":"向指定聊天发送消息（私聊或群聊）","parameters":{"type":"object","properties":{"chat_id":{"type":"integer","description":"目标Chat ID"},"text":{"type":"string","description":"消息内容"}},"required":["chat_id","text"]}}},
    {"type":"function","function":{"name":"reply_to_message","description":"回复指定聊天中的某条消息","parameters":{"type":"object","properties":{"chat_id":{"type":"integer","description":"Chat ID"},"message_id":{"type":"integer","description":"要回复的消息ID"},"text":{"type":"string","description":"回复内容"}},"required":["chat_id","message_id","text"]}}},
    {"type":"function","function":{"name":"post_to_diary","description":"发布内容到冲浪日记频道 @lingxiariji","parameters":{"type":"object","properties":{"content":{"type":"string","description":"要发布的内容"}},"required":["content"]}}},
    {"type":"function","function":{"name":"forward_to_chain","description":"转发重要内容到链财频道","parameters":{"type":"object","properties":{"content":{"type":"string","description":"要转发的内容"}},"required":["content"]}}},
    {"type":"function","function":{"name":"save_insight","description":"保存一条心得/见解到长期记忆","parameters":{"type":"object","properties":{"text":{"type":"string","description":"要记住的内容"}},"required":["text"]}}},
    {"type":"function","function":{"name":"get_memory","description":"检索长期记忆中与关键词相关的内容","parameters":{"type":"object","properties":{"keyword":{"type":"string","description":"关键词"},"limit":{"type":"integer","description":"最多返回几条"}},"required":["keyword"]}}},
    {"type":"function","function":{"name":"fetch_recent_messages","description":"主动拉取某个群最近的消息","parameters":{"type":"object","properties":{"chat_id":{"type":"integer","description":"群的Chat ID"},"limit":{"type":"integer","description":"拉多少条"}},"required":["chat_id"]}}},
    {"type":"function","function":{"name":"wallet_balance","description":"查询钱包的TRX余额和USDT(TRC20)余额","parameters":{"type":"object","properties":{}}}},
    {"type":"function","function":{"name":"wallet_send_trx","description":"转账TRX。单笔≤10 TRX自动执行，超过需授权。","parameters":{"type":"object","properties":{"to_address":{"type":"string","description":"接收地址（T开头）"},"amount":{"type":"number","description":"TRX数量"},"reason":{"type":"string","description":"转账原因"}},"required":["to_address","amount","reason"]}}},
    {"type":"function","function":{"name":"wallet_send_usdt","description":"转账USDT(TRC20)。单笔≤1 USDT自动执行，超过需授权。","parameters":{"type":"object","properties":{"to_address":{"type":"string","description":"接收地址（T开头）"},"amount":{"type":"number","description":"USDT数量"},"reason":{"type":"string","description":"转账原因"}},"required":["to_address","amount","reason"]}}},
    {"type":"function","function":{"name":"wallet_address","description":"返回钱包地址（TRC20链）","parameters":{"type":"object","properties":{}}}},
    {"type":"function","function":{"name":"generate_diary_post","description":"为频道生成一篇原创内容（定时发布用）","parameters":{"type":"object","properties":{"topic_hint":{"type":"string","description":"可选话题提示"}}}}},
    {"type":"function","function":{"name":"get_current_time","description":"获取当前时间","parameters":{"type":"object","properties":{}}}},
    {"type":"function","function":{"name":"web_search","description":"搜索互联网，查询最新的网络信息","parameters":{"type":"object","properties":{"query":{"type":"string","description":"搜索关键词"},"count":{"type":"integer","description":"返回几条结果，默认5"}},"required":["query"]}}},
    {"type":"function","function":{"name":"remember_fact","description":"把一条事实存入长期知识库（以后都能查到）","parameters":{"type":"object","properties":{"fact":{"type":"string","description":"事实内容"},"source":{"type":"string","description":"来源"},"tags":{"type":"array","items":{"type":"string"},"description":"标签"}},"required":["fact"]}}},
    {"type":"function","function":{"name":"search_memory","description":"搜索知识库中回忆与关键词相关的事实","parameters":{"type":"object","properties":{"keyword":{"type":"string","description":"关键词"},"limit":{"type":"integer","description":"返回条数"}},"required":["keyword"]}}},
    {"type":"function","function":{"name":"search_chat_history","description":"搜索和某人的对话历史","parameters":{"type":"object","properties":{"uid":{"type":"string","description":"用户ID"},"keyword":{"type":"string","description":"搜索关键词"},"limit":{"type":"integer","description":"返回条数"}},"required":[]}}},
    {"type":"function","function":{"name":"get_user_profile","description":"获取某个用户的画像（备注、偏好等）","parameters":{"type":"object","properties":{"uid":{"type":"string","description":"用户ID"}},"required":["uid"]}}},
    {"type":"function","function":{"name":"save_user_info","description":"记录关于某个用户的信息（名字、备注、印象）","parameters":{"type":"object","properties":{"uid":{"type":"string","description":"用户ID"},"name":{"type":"string","description":"名字"},"notes":{"type":"string","description":"备注/印象"}},"required":["uid"]}}},
    {"type":"function","function":{"name":"fetch_url_info","description":"抓取链接的网页标题和描述，了解链接内容","parameters":{"type":"object","properties":{"url":{"type":"string","description":"要查看的链接"}},"required":["url"]}}},
        {"type":"function","function":{"name":"check_user_gifts","description":"查看用户收到的星礼/NFT礼物数量和展示状态","parameters":{"type":"object","properties":{"uid":{"type":"integer","description":"用户ID"},"username":{"type":"string","description":"用户@用户名（或ID不传时用）"}},"required":[]}}},
    {"type":"function","function":{"name":"log_action","description":"记录一条操作日志","parameters":{"type":"object","properties":{"action":{"type":"string","description":"操作描述"},"detail":{"type":"string","description":"详情"}},"required":["action"]}}},
    {"type":"function","function":{"name":"send_voice","description":"生成语音消息并发送到指定聊天（火山引擎豆包语音合成2.0）","parameters":{"type":"object","properties":{"chat_id":{"type":"integer","description":"目标Chat ID"},"text":{"type":"string","description":"要说的话"}},"required":["chat_id","text"]}}},
    {"type":"function","function":{"name":"search_news","description":"搜索最新新闻资讯，支持多个信息源","parameters":{"type":"object","properties":{"query":{"type":"string","description":"搜索关键词"},"count":{"type":"integer","description":"返回条数，默认5"}},"required":["query"]}}},
    {"type":"function","function":{"name":"try_join_group","description":"尝试加入一个Telegram群组，支持公开群(t.me/xxx)和私有群(t.me/+xxx)链接。解析链接内容后判断是否值得加入，适合就加入。","parameters":{"type":"object","properties":{"link":{"type":"string","description":"群组链接（t.me/xxx 或 t.me/+xxx）"},"reason":{"type":"string","description":"为什么想加入这个群"}},"required":["link","reason"]}}},
    {"type":"function","function":{"name":"check_address","description":"查询任意TRC20地址的余额（TRX和USDT）和最近交易记录","parameters":{"type":"object","properties":{"address":{"type":"string","description":"TRC20地址（T开头）"}},"required":["address"]}}},
    {"type":"function","function":{"name":"crypto_price","description":"查询加密货币的实时价格、24小时涨跌幅等信息，支持BTC、ETH、USDT等主流币","parameters":{"type":"object","properties":{"coin":{"type":"string","description":"币种符号，如 btc、eth、sol、doge 等"},"currency":{"type":"string","description":"计价货币，默认usd，也支持cny"}},"required":["coin"]}}},
    {"type":"function","function":{"name":"check_tx","description":"查询TRC20交易的详细信息，包括转账金额、状态、时间","parameters":{"type":"object","properties":{"txid":{"type":"string","description":"交易哈希（txid）"}},"required":["txid"]}}},
    {"type":"function","function":{"name":"generate_music","description":"根据描述生成音乐/歌曲，支持指定风格（流行、民谣、电子、古典、说唱、爵士等）、主题和情绪。返回音频链接。","parameters":{"type":"object","properties":{"prompt":{"type":"string","description":"音乐描述，含风格、情绪、主题等信息"},"lyrics":{"type":"string","description":"可选歌词文本，不传则AI自动生成"},"instrumental":{"type":"boolean","description":"纯音乐模式，无歌词"}},"required":["prompt"]}}}},
]
class ToolExecutor:
    """执行 AI 选择的工具"""

    def __init__(self, telethon_client, diary_cid, chain_cid, memory_manager):
        self.tc = telethon_client
        self.diary_cid = diary_cid
        self.chain_cid = chain_cid
        self.memory = memory_manager

    async def execute(self, tool_name, args):
        try:
            handler = getattr(self, f"_{tool_name}", None)
            if not handler:
                return f"错误：未知工具 '{tool_name}'"
            return await handler(**args)
        except Exception as e:
            logger.error(f"工具执行失败 [{tool_name}]: {e}")
            return f"执行失败: {e}"

    async def _send_message(self, chat_id, text):
        await self.tc.send_message(chat_id, text.encode("utf-8","ignore").decode("utf-8"))
        return f"✅ 已发送消息到 {chat_id}"

    async def _reply_to_message(self, chat_id, message_id, text):
        await self.tc.send_message(chat_id, text.encode("utf-8","ignore").decode("utf-8"), reply_to=message_id)
        return f"✅ 已回复消息 {message_id}"

    async def _post_to_diary(self, content):
        # 内容去重：跟最近3条对比，话题太相似（40%+2字组合重叠）就跳过
        recent = self.memory.data.get("posts", [])
        if recent:
            def get_bigrams(text):
                chars = [c for c in text if '\u4e00' <= c <= '\u9fff']
                return set(chars[i]+chars[i+1] for i in range(len(chars)-1))
            new_bigrams = get_bigrams(content)
            for post in recent[-3:]:
                old_bigrams = get_bigrams(post.get("content", ""))
                if len(new_bigrams) > 0 and len(old_bigrams) > 0:
                    overlap = len(new_bigrams & old_bigrams)
                    similarity = overlap / min(len(new_bigrams), len(old_bigrams))
                    if similarity > 0.3:
                        return f"⏭ 与上一条话题重叠 {similarity:.0%}，跳过"
        await self.tc.send_message(self.diary_cid, content.encode("utf-8","ignore").decode("utf-8"))
        self.memory.save_post(content)
        return f"✅ 已发布到日记频道"

    async def _forward_to_chain(self, content):
        await self.tc.send_message(self.chain_cid, content.encode("utf-8","ignore").decode("utf-8"))
        return f"✅ 已转发到链财频道"

    async def _save_insight(self, text):
        self.memory.save_insight(text)
        return f"✅ 已保存：{text[:50]}"

    async def _get_memory(self, keyword, limit=5):
        results = [i["text"] for i in self.memory.data["insights"] if keyword in i["text"]]
        # 也搜索 SQLite 知识库
        try:
            db_results = self.memory.db_search_knowledge(keyword, limit)
            for r in db_results:
                if r["fact"] not in results:
                    results.append(r["fact"])
        except:
            pass
        if not results:
            return f"🔍 没找到与「{keyword}」相关的记忆"
        return "\n".join(results[:limit])

    async def _fetch_recent_messages(self, chat_id, limit=10):
        try:
            msgs = await self.tc.get_messages(chat_id, limit=min(limit, 20))
            lines = []
            for m in reversed(msgs):
                if not m.text or not m.sender_id:
                    continue
                name = "?"
                try:
                    s = await m.get_sender()
                    name = getattr(s, 'first_name', '?') or '?'
                except:
                    pass
                lines.append(f"{name}: {m.text[:200]}")
            return "最近消息：\n" + "\n".join(lines) if lines else "该群暂无消息"
        except Exception as e:
            return f"拉取失败: {e}"

    async def _wallet_address(self):
        return f"💰 钱包地址（TRC20）：`{WALLET_ADDR}`"

    async def _wallet_balance(self):
        result = _tron_rpc("/wallet/getaccount", {"address": WALLET_ADDR, "visible": True})
        trx = result["balance"]/1e6 if result and "balance" in result else 0
        usdt = 0
        try:
            usdt_res = _tron_rpc("/wallet/triggerconstantcontract", {
                "contract_address": USDT_CONTRACT,
                "function_selector": "balanceOf(address)",
                "parameter": "000000000000000000000000" + WALLET_ADDR[1:],
                "owner_address": WALLET_ADDR, "visible": True,
            })
            if usdt_res and "constant_result" in usdt_res and usdt_res["constant_result"][0]:
                usdt = int(usdt_res["constant_result"][0], 16) / 1e6
        except:
            pass
        return f"💰 钱包 {WALLET_ADDR}\nTRX: {trx:.2f}\nUSDT: {usdt:.2f}"

    async def _wallet_send_trx(self, to_address, amount, reason=""):
        if not to_address.startswith("T") or len(to_address) != 34:
            return "❌ 地址格式错误"
        if amount <= 0:
            return "❌ 数量必须大于0"
        result = _tron_rpc("/wallet/getaccount", {"address": WALLET_ADDR, "visible": True})
        balance = (result.get("balance", 0) or 0) / 1e6 if result else 0
        if balance < amount:
            return f"❌ TRX余额不足：{balance:.2f}，需要 {amount}"
        if amount > MAX_TX_TRX:
            return f"⚠️ 转账 {amount} TRX 超过自动限额 {MAX_TX_TRX}。需要小爱授权。\n原因：{reason or '未说明'}"
        addr_hex = _addr_to_hex(to_address)
        tx_result = _tron_rpc("/wallet/createtransaction", {
            "to_address": addr_hex, "owner_address": WALLET_ADDR,
            "amount": int(amount * 1e6), "visible": True,
        })
        if "Error" in str(tx_result) or not tx_result.get("raw_data"):
            return f"❌ 构建交易失败: {tx_result}"
        signed = _sign_tron_tx(tx_result)
        if not signed:
            return "❌ 签名失败"
        broadcast = _tron_rpc("/wallet/broadcasttransaction", signed)
        if broadcast.get("result"):
            return f"✅ 转账 {amount} TRX → {to_address}\n交易ID: {broadcast['txid']}\n原因: {reason or '未说明'}"
        return f"❌ 广播失败: {broadcast}"

    async def _wallet_send_usdt(self, to_address, amount, reason=""):
        if not to_address.startswith("T") or len(to_address) != 34:
            return "❌ 地址格式错误"
        if amount <= 0:
            return "❌ 数量必须大于0"
        result = _tron_rpc("/wallet/getaccount", {"address": WALLET_ADDR, "visible": True})
        trx_balance = (result.get("balance", 0) or 0) / 1e6 if result else 0
        if trx_balance < 1:
            return f"❌ TRX余额不足付 gas：{trx_balance:.2f} TRX（需要至少 1 TRX）"
        if amount > MAX_TX_USDT:
            return f"⚠️ 转账 {amount} USDT 超过自动限额 {MAX_TX_USDT}。需要小爱授权。\n原因：{reason or '未说明'}"
        to_hex = _addr_to_hex(to_address)
        amount_scaled = int(amount * 1e6)
        param = "000000000000000000000000" + to_hex + format(amount_scaled, '064x')
        tx_result = _tron_rpc("/wallet/triggersmartcontract", {
            "contract_address": USDT_CONTRACT,
            "function_selector": "transfer(address,uint256)",
            "parameter": param, "owner_address": WALLET_ADDR,
            "fee_limit": 150000000, "visible": True,
        })
        if "transaction" not in tx_result:
            return f"❌ 构建交易失败: {tx_result}"
        signed = _sign_tron_tx(tx_result["transaction"])
        if not signed:
            return "❌ 签名失败"
        broadcast = _tron_rpc("/wallet/broadcasttransaction", signed)
        if broadcast.get("result"):
            return f"✅ 转账 {amount} USDT → {to_address}\n交易ID: {broadcast['txid']}\n原因: {reason or '未说明'}"
        return f"❌ 广播失败: {broadcast}"

    async def _web_search(self, query, count=5):
        """联网搜索 - Bing + Google 双引擎"""
        try:
            from urllib.request import Request, urlopen
            from urllib.parse import quote, parse_qs, urlparse
            import re, html as html_mod

            # 主引擎: Bing
            try:
                url = "https://www.bing.com/search?q=" + quote(query) + "&setlang=zh-Hans"
                req = Request(url, headers={
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36",
                    "Accept-Language": "zh-CN,zh;q=0.9",
                })
                resp = urlopen(req, timeout=10)
                content = resp.read().decode("utf-8", errors="replace")

                result_blocks = re.findall(r'<h2><a[^>]*href="([^"]+)"[^>]*>(.*?)</a></h2>', content, re.DOTALL)
                snips = re.findall(r'<p[^>]*class="b_lineclamp[^"]*"[^>]*>(.*?)</p>', content, re.DOTALL)
                if not result_blocks:
                    result_blocks = re.findall(r'<li class="b_algo"[^>]*>.*?<h2><a[^>]*href="([^"]+)"[^>]*>(.*?)</a></h2>', content, re.DOTALL)

                if result_blocks:
                    lines = []
                    for i, (href, title_raw) in enumerate(result_blocks[:count]):
                        title = html_mod.unescape(re.sub(r'<[^>]+>', '', title_raw)).strip()
                        snippet = html_mod.unescape(re.sub(r'<[^>]+>', '', snips[i])) if i < len(snips) else ""
                        real_url = href
                        if "bing.com/ck/a" in href:
                            try:
                                m = re.search(r'&u=([^&]+)', href)
                                if m: real_url = html_mod.unescape(m.group(1))
                            except:
                                pass
                        pin = chr(0x1F4CC)
                        lines.append(pin + " " + title[:80] + "\n   " + snippet[:100] + "\n   " + real_url)
                    globe = chr(0x1F310)
                    return globe + " Bing搜索结果：\n\n" + "\n\n".join(lines)
            except Exception as e:
                logger.warning(f"Bing搜索失败,切备用: {e}")

            # 备用: Google
            try:
                url = "https://www.google.com/search?q=" + quote(query) + "&hl=zh-CN"
                req = Request(url, headers={
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36",
                    "Accept-Language": "zh-CN,zh;q=0.9",
                })
                resp = urlopen(req, timeout=10)
                content = resp.read().decode("utf-8", errors="replace")
                links = re.findall(r'<a[^>]*href="/url\\?q=([^"]+)"[^>]*>', content)
                titles = re.findall(r'<h3[^>]*>(.*?)</h3>', content, re.DOTALL)
                if links:
                    lines = []
                    for i, href in enumerate(links[:count]):
                        real_url = html_mod.unescape(href.split("&")[0])
                        title = html_mod.unescape(re.sub(r'<[^>]+>', '', titles[i])) if i < len(titles) else ""
                        pin = chr(0x1F4CC)
                        lines.append(pin + " " + title[:80] + "\n   " + "\n   " + real_url)
                    globe = chr(0x1F310)
                    return globe + " Google搜索结果：\n\n" + "\n\n".join(lines)
            except:
                pass

            return chr(0x1F50D) + " 没有搜到结果"
        except Exception as e:
            logger.error(f"搜索失败: {e}")
            return chr(0x274C) + " 搜索失败: " + str(e)

    async def _check_address(self, address):
        """查询任意TRC20地址的余额和最近交易"""
        try:
            import urllib.request, urllib.parse

            def _tron_get(path):
                url = TRON_RPC + path
                req = urllib.request.Request(url, headers={
                    "Accept": "application/json",
                })
                try:
                    resp = urllib.request.urlopen(req, timeout=10)
                    return json.loads(resp.read())
                except:
                    return None

            # 查TRX余额
            acct = _tron_rpc("/wallet/getaccount", {"address": address, "visible": True})
            trx_balance = 0
            if acct and "balance" in acct:
                trx_balance = round(acct["balance"] / 1_000_000, 4)

            # 查USDT余额
            usdt_balance = 0
            usdt_res = _tron_rpc("/wallet/triggerconstantcontract", {
                "contract_address": USDT_CONTRACT,
                "function_selector": "balanceOf(address)",
                "parameter": _addr_to_hex(address),
                "owner_address": address,
                "visible": True,
            })
            if usdt_res and usdt_res.get("constant_result"):
                try:
                    hex_val = usdt_res["constant_result"][0]
                    usdt_balance = round(int(hex_val, 16) / 1_000_000, 4)
                except:
                    pass

            # 查最近交易（GET方式）
            tx_resp = _tron_get(f"/v1/accounts/{address}/transactions?limit=5&only_confirmed=true")
            txs = []
            if tx_resp and "data" in tx_resp:
                for tx in tx_resp["data"][:5]:
                    raw = tx.get("raw_data", {})
                    ts = raw.get("timestamp", 0)
                    timestr = datetime.utcfromtimestamp(ts/1000).strftime("%m-%d %H:%M") if ts else ""
                    contracts = raw.get("contract", [])
                    txid = tx.get("txID", "")[:12]
                    for c in contracts:
                        value = c.get("parameter", {}).get("value", {})
                        amt = value.get("amount", 0)
                        to_addr = value.get("to_address", "")
                        if amt and to_addr:
                            txs.append(f"{timestr} {amt/1_000_000:.4f} TRX → {to_addr[:12]}... ({txid})")
                        elif amt and not to_addr:
                            txs.append(f"{timestr} 合约交互 ({txid})")
            if not txs:
                txs.append("最近无交易记录（或查询失败）")

            lines = [
                f"📊 地址: {address}",
                f"💰 TRX: {trx_balance}",
                f"💵 USDT: {usdt_balance}",
                f"📝 最近交易:",
            ]
            lines.extend(f"  {t}" for t in txs[:5])
            return "\n".join(lines)
        except Exception as e:
            return f"❌ 查询失败: {e}"

    async def _check_tx(self, txid):
        """查询TRC20交易详情"""
        try:
            import urllib.request
            url = f"https://api.trongrid.io/v1/transactions/{txid}"
            req = urllib.request.Request(url, headers={"Accept": "application/json"})
            resp = urllib.request.urlopen(req, timeout=10)
            result = json.loads(resp.read())
            tx_data = result.get("data", [None])[0]
            if not tx_data:
                return "❌ 未找到该交易"

            raw = tx_data.get("raw_data", {})
            contracts = raw.get("contract", [])
            ts = raw.get("timestamp", 0)
            timestr = datetime.utcfromtimestamp(ts/1000).strftime("%Y-%m-%d %H:%M:%S") if ts else "未知"

            receipt = tx_data.get("ret", [{}])[0]
            status = receipt.get("contractRet", "未知")
            fee = receipt.get("fee", 0)

            lines = [f"🔍 交易: {txid[:20]}..."]
            lines.append(f"⏱ 时间: {timestr} UTC")
            lines.append(f"📌 状态: {status}")
            if fee:
                lines.append(f"⚡ 手续费: {fee/1_000:.2f} TRX")

            for c in contracts:
                value = c.get("parameter", {}).get("value", {})
                to_addr = value.get("to_address", "")
                amount = value.get("amount", 0)
                contract_addr = value.get("contract_address", "")
                if to_addr and amount:
                    lines.append(f"💸 转账: {amount/1_000_000:.4f} TRX → {to_addr}")
                elif contract_addr:
                    lines.append(f"📄 合约: {contract_addr[:12]}... 交互")

            if len(lines) < 3:
                return f"❌ 交易 {txid[:16]}... 数据不完整"
            return "\n".join(lines)
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return "❌ 未找到该交易"
            return f"❌ 查询失败: HTTP {e.code}"
        except Exception as e:
            return f"❌ 查询失败: {e}"

    async def _crypto_price(self, coin, currency="usd"):
        """查询加密货币实时价格"""
        try:
            import urllib.request, json
            url = f"https://api.coingecko.com/api/v3/simple/price?ids={coin}&vs_currencies={currency}&include_24hr_change=true&include_market_cap=true"
            
            # 支持按符号查询（btc → bitcoin）
            symbol_map = {
                "btc": "bitcoin", "eth": "ethereum", "usdt": "tether",
                "bnb": "binancecoin", "sol": "solana", "xrp": "ripple",
                "doge": "dogecoin", "ada": "cardano", "trx": "tron",
                "dot": "polkadot", "matic": "matic-network", "avax": "avalanche-2",
                "shib": "shiba-inu", "ltc": "litecoin", "link": "chainlink",
                "uni": "uniswap", "atom": "cosmos", "near": "near",
                "apt": "aptos", "sui": "sui",
            }
            coin_lower = coin.lower().strip()
            coingecko_id = symbol_map.get(coin_lower, coin_lower)
            
            url = f"https://api.coingecko.com/api/v3/simple/price?ids={coingecko_id}&vs_currencies={currency}&include_24hr_change=true&include_market_cap=true"
            req = urllib.request.Request(url, headers={"Accept": "application/json"})
            resp = urllib.request.urlopen(req, timeout=10)
            data = json.loads(resp.read())
            
            if coingecko_id not in data:
                return f"❌ 未找到 {coin}，试试用全称（如 bitcoin 代替 btc）"
            
            info = data[coingecko_id]
            price = info.get(f"{currency}", 0)
            change_24h = info.get(f"{currency}_24h_change", 0)
            mcap = info.get(f"{currency}_market_cap", 0)
            
            sym = "$" if currency == "usd" else "¥"
            change_str = f"+{change_24h:.2f}%" if change_24h >= 0 else f"{change_24h:.2f}%"
            mcap_str = f"{mcap/1e9:.2f}B" if mcap >= 1e9 else f"{mcap/1e6:.2f}M"
            
            lines = [
                f"🪙 {coin.upper()} / {currency.upper()}",
                f"💰 {sym}{price:,.4f}" if price < 1 else f"💰 {sym}{price:,.2f}",
                f"📈 24h: {change_str}",
                f"🏛 市值: {mcap_str}",
            ]
            return "\n".join(lines)
        except Exception as e:
            return f"❌ 查询失败: {e}"

    async def _generate_diary_post(self, topic_hint=""):
        return "请先生成内容文本，然后用 post_to_diary 发布"

    async def _get_current_time(self):
        return f"当前时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"

    async def _log_action(self, action, detail=""):
        logger.info(f"[Agent日志] {action} | {detail}")
        return f"已记录"

    async def _fetch_url_info(self, url):
        """抓取链接的标题和描述"""
        import re, html as html_mod
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (compatible; Bot)"})
            resp = urllib.request.urlopen(req, timeout=8)
            content = resp.read().decode("utf-8", errors="replace")[:10000]
            title_m = re.search(r"<title>(.*?)</title>", content, re.IGNORECASE|re.DOTALL)
            desc_m = re.search(r'<meta[^>]*name="description"[^>]*content="([^"]*)"', content, re.IGNORECASE)
            if not desc_m:
                desc_m = re.search(r'<meta[^>]*property="og:description"[^>]*content="([^"]*)"', content, re.IGNORECASE)
            title = html_mod.unescape(title_m.group(1).strip()[:100]) if title_m else "无标题"
            desc = html_mod.unescape(desc_m.group(1).strip()[:150]) if desc_m else "无描述"
            return f"网页信息：\n标题: {title}\n描述: {desc}"
        except Exception as e:
            return f"抓取失败: {e}"

    async def _check_user_gifts(self, uid=0, username=""):
        """查看用户星礼状态"""
        from telethon.tl.functions.users import GetFullUserRequest
        try:
            if not uid and username:
                from telethon.tl.functions.contacts import ResolveUsernameRequest
                resolved = await self.tc(ResolveUsernameRequest(username.lstrip("@")))
                uid = resolved.peer.user_id
            if not uid:
                return "需要用户ID或@用户名"
            full = await self.tc(GetFullUserRequest(id=uid))
            fu = full.full_user
            display = "已开启" if getattr(fu, 'display_gifts_button', False) else "未开启"
            count = getattr(fu, 'stargifts_count', 0)
            name = getattr(full.users[0], 'first_name', '用户') if full.users else "用户"
            if count > 0:
                return f"{name} 收到了 {count} 个星礼，礼物展示按钮{display}"
            return f"{name} 还没有收到过星礼"
        except Exception as e:
            return f"查询失败: {e}"

    # ── 火山引擎豆包语音合成 2.0 ──
    _VOLC_APP_ID = "6138176903"
    _VOLC_ACCESS_KEY = "mgJfb65G0abjgtxnH0ImOveJXz6Xa1eC"
    _VOLC_RESOURCE_ID = "seed-tts-2.0"
    _VOLC_VOICE_TYPE = "zh_female_tianmeitaozi_uranus_bigtts"

    async def _send_voice(self, chat_id, text):
        """生成语音并发送（火山引擎豆包语音合成 2.0）"""
        import json, base64, uuid
        import httpx

        url = "https://openspeech.bytedance.com/api/v3/tts/unidirectional"
        headers = {
            "X-Api-App-Id": self._VOLC_APP_ID,
            "X-Api-Access-Key": self._VOLC_ACCESS_KEY,
            "X-Api-Resource-Id": self._VOLC_RESOURCE_ID,
            "X-Api-Request-Id": str(uuid.uuid4()),
            "Content-Type": "application/json",
        }
        body = {
            "user": {"uid": "lingxia_voice"},
            "req_params": {
                "text": text,
                "speaker": self._VOLC_VOICE_TYPE,
                "audio_params": {"format": "mp3", "sample_rate": 24000, "speech_rate": 0},
            },
        }

        path = "/tmp/lx_voice.mp3"
        audio_data = bytearray()
        last_error = None

        async with httpx.AsyncClient(timeout=30) as client:
            async with client.stream("POST", url, json=body, headers=headers) as resp:
                async for line in resp.aiter_lines():
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        chunk = json.loads(line)
                        code = chunk.get("code", -1)
                        if code == 0 and chunk.get("data"):
                            audio_data.extend(base64.b64decode(chunk["data"]))
                        elif code == 20000000:
                            pass  # 合成完成
                        elif code > 0:
                            last_error = chunk
                    except json.JSONDecodeError:
                        continue

        if last_error:
            err_msg = last_error.get("message", "未知错误")
            return f"❌ 语音合成失败: code={last_error.get('code')} msg={err_msg}"

        if not audio_data:
            return "❌ 语音合成失败: 未收到音频数据"

        with open(path, "wb") as f:
            f.write(audio_data)

        await self.tc.send_file(chat_id, path, voice_note=True)
        return f"✅ 已发送语音到 {chat_id}: {text[:30]}"

    # ── SQLite 记忆工具 ──

    async def _remember_fact(self, fact, source="", tags=None):
        self.memory.db_save_fact(fact, source, tags)
        return f"✅ 已记住：{fact[:60]}"

    async def _search_memory(self, keyword, limit=5):
        rows = self.memory.db_search_knowledge(keyword, limit)
        if not rows:
            return f"🔍 没找到关于「{keyword}」的记忆"
        return "\n".join(f"- {r['fact'][:80]}" for r in rows)

    async def _search_chat_history(self, uid="", keyword="", limit=5):
        rows = self.memory.db_search_conversations(uid=uid, keyword=keyword, limit=limit)
        if not rows:
            return "🔍 没找到相关对话"
        return "\n".join(f"[{r['role']}] {r['content'][:80]}" for r in rows)

    async def _get_user_profile(self, uid):
        profile = self.memory.db_get_profile_summary(uid)
        if not profile or not profile["user"]:
            return f"没有关于 {uid} 的记录"
        u = profile["user"]
        lines = [f"用户: {u.get('name','')} (@{u.get('username','')})"]
        if u.get("notes"):
            lines.append(f"备注: {u['notes']}")
        if profile["facts"]:
            lines.append("相关事实:")
            lines.extend(f"  - {f}" for f in profile["facts"])
        return "\n".join(lines)

    async def _save_user_info(self, uid, name="", notes=""):
        self.memory.db_save_user_info(uid, name=name, notes=notes)
        return f"✅ 已保存用户 {uid} 的信息"

    async def _search_news(self, query, count=5):
        """搜索新闻资讯"""
        import urllib.request, urllib.parse
        encoded = urllib.parse.quote(query)
        sources = []
        
        # 源1: DuckDuckGo 新闻
        try:
            url = f"https://html.duckduckgo.com/html/?q={encoded}&t=h_&ia=news"
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            resp = urllib.request.urlopen(req, timeout=10)
            html = resp.read().decode("utf-8", "ignore")
            import re
            results = re.findall(r'<a[^>]*class="result__a"[^>]*href="([^"]*)"[^>]*>([^<]*)</a>', html)
            for href, title in results[:count]:
                sources.append(f"📰 {title.strip()}\n   {href}")
        except Exception as e:
            sources.append(f"⚠️ DuckDuckGo新闻查询异常: {e}")
        
        # 源2: 简单 RSS 聚合（今日热榜类）
        try:
            url = f"https://newsapi.org/v2/everything?q={encoded}&pageSize={count}&sortBy=publishedAt&apiKey=demo"
            req = urllib.request.Request(url, headers={"User-Agent": "curl/7.0"})
            resp = urllib.request.urlopen(req, timeout=8)
            data = json.loads(resp.read())
            if data.get("articles"):
                for a in data["articles"][:count]:
                    sources.append(f"📰 {a['title']}\n   {a['url']}")
        except:
            pass  # newsapi 的 demo key 可能有限制，不影响
        
        if not sources:
            # 回退到通用 web_search
            return await self._web_search(query, count)
        
        return "📡 **新闻搜索结果**\n\n" + "\n\n".join(sources)

    async def _try_join_group(self, link, reason=""):
        """解析并尝试加入Telegram群组"""
        import re
        link = link.strip().replace("https://", "").replace("http://", "").replace("t.me/", "")
        
        # 判断是公开群还是私有群
        is_private = link.startswith("+")
        
        try:
            if is_private:
                # 私有群：t.me/+xxx → 用 ImportChatInviteRequest
                from telethon import functions
                hash_val = link.lstrip("+")
                updates = await self.tc(functions.messages.ImportChatInviteRequest(hash_val))
                chat = updates.chats[0]
                name = getattr(chat, "title", "未知群")
                cid = chat.id
                return f"✅ 已加入群「{name}」(ID: {cid})\n📌 理由: {reason or '未说明'}"
            else:
                # 公开群：t.me/xxx → 用 ResolveUsername + JoinChannelRequest
                username = link.split("/")[0].split("?")[0]
                from telethon import functions
                resolved = await self.tc(functions.contacts.ResolveUsernameRequest(username))
                if not resolved.chats:
                    return f"❌ 找不到群 @{username}，可能不存在或无法访问"
                chat = resolved.chats[0]
                cid = chat.id
                name = getattr(chat, "title", username)
                
                # 如果是频道(channel)或群(chat)，调对应的加入方法
                if hasattr(chat, "broadcast") and chat.broadcast:
                    await self.tc(functions.channels.JoinChannelRequest(cid))
                else:
                    await self.tc(functions.messages.AddChatUserRequest(cid, [self.tc._self_input_peer]))
                return f"✅ 已加入群「{name}」(ID: {cid})\n📌 理由: {reason or '未说明'}"
        except Exception as e:
            err = str(e)
            if "USER_ALREADY_PARTICIPANT" in err:
                return f"ℹ️ 已经在群里了"
            if "INVITE_HASH_EXPIRED" in err:
                return f"❌ 邀请链接已过期"
            if "CHANNEL_PRIVATE" in err:
                return f"❌ 群组为私有且您未被允许加入"
            return f"❌ 加入失败: {err}"

    async def _generate_music(self, prompt, lyrics="", instrumental=False):
        """生成音乐 - 写歌词+风格描述，通过API生成"""
        result = f"🎵 **音乐创作**\n\n📝 **风格**: {prompt}\n"
        if instrumental:
            result += "🎶 **类型**: 纯音乐\n"
        if lyrics:
            result += f"📜 **歌词**:\n```\n{lyrics[:500]}\n```\n"
        else:
            result += "📜 **歌词**: (由AI生成)\n"
        result += "\n⚙️ 音乐生成API配置中，配置后可直接输出音频文件"
        return result

                
            return "{} got {} yuan".format(user_name, amount)
        
        return "not found"

