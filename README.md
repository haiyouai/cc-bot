<p align="center">
  <img src="https://image.pollinations.ai/prompt/CC%20Bot%20-%20Telegram%20AI%20assistant%20chatbot%20futuristic%20cyberpunk%20style%20blue%20and%20pink%20glowing%20neon%20robot%20girl%20logo?seed=8223087548" width="600" alt="CC Bot Banner"/>
</p>

# CC Bot - Telegram AI 群管家

一个基于 DeepSeek/Claude 的 Telegram AI 助手，支持群聊巡逻、自动回复、记忆系统、多工具调用。

## 功能

- **AI 聊天**：自然对话，记得上下文
- **群聊巡逻**：自动浏览群消息，发现有趣话题主动参与
- **私聊+群聊串联**：同一个用户在群聊和私聊的对话都能关联
- **记忆系统**：自动记住重要信息，下次聊天能想起来
- **工具调用**：查币价、搜新闻、搜索网络、查时间等
- **多模型支持**：DeepSeek / Claude / OpenAI 兼容 API

## 快速开始

### 1. 配置环境

```bash
cp .env.example .env
# 编辑 .env 填入你的配置
```

### 2. 安装依赖

```bash
pip3 install telethon httpx
```

### 3. 运行

```bash
python3 main.py
# 首次运行需要扫码登录 Telegram
```

## 目录结构

```
├── main.py        # 主程序（事件处理、巡逻）
├── agent.py       # AI 对话代理（ReAct 循环）
├── tools.py       # 工具集（搜索、查价、语音等）
├── memory.py      # 记忆系统（SQLite + JSON）
├── SOUL.md        # AI 人格设定
├── vector_memory  # 向量记忆模块
└── tools/         # 工具包
```

## 自定义

编辑 `SOUL.md` 可以改变 AI 的性格和行为风格。

## 许可证

GPL v3

## 说明

本项目最初为个人使用开发，开源供学习参考。
