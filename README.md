# douyin-vault-skill

抖音博主 → Obsidian 知识库的一条龙 Claude Code / ZCode 技能：全量视频抓取、防封限速下载、GPU 语音转写、AI 提炼问题、知识库组装、群聊历史深挖。

Douyin creator → Obsidian knowledge base pipeline: full video list capture, rate-limited anti-ban download, GPU large-v3 transcription, AI question extraction, vault assembly with graph view, and web-DM history deep-dive.

## 实战验证 / Battle-tested

用本技能一次性完成了：

- 104 个视频全量抓取（0 失败，含 post 接口漏掉的 6 条最新视频）
- 453 分钟音频 GPU 转录（RTX 4060 + faster-whisper large-v3，~6x 实时）
- 516 个可勾选的具体问题 + 7 大主题页 + 104 篇笔记
- Obsidian 网状图谱（内容相似度互联 + 路径配色）
- 群聊 278 条全量历史挖掘（UI 翻到底 + 服务器游标验证建群时间）

## 快速开始

```bash
# 1. 用真实浏览器(如 Playwright)登录 douyin.com 抓博主视频列表为 videos.json
#    格式: [{id, desc, dur_ms, urls:[直链...], create, digg}]

# 2. 限速下载
python scripts/download.py videos.json -o D:/data/videos

# 3. GPU 转录(先 pip install faster-whisper nvidia-cublas-cu12 nvidia-cudnn-cu12)
python scripts/transcribe.py D:/data/videos -o D:/data

# 4. AI 逐条分析, 每条写 analysis/{seq}_{id}.md (模板见 SKILL.md)

# 5. 组装 Obsidian vault(含图谱配色)
python scripts/build_vault.py D:/data -o D:/data/vault --themes themes.json
```

完整方法论与 11 个踩坑实录见 [SKILL.md](SKILL.md)。

## 技能安装 / Install as skill

```bash
git clone https://github.com/0xAlchemist-cs/douyin-vault-skill ~/.zcode/skills/douyin-vault
# 或复制到你的 agent 技能目录, 之后提到"抖音博主知识库"即自动路由
```

## 防封原则 / Anti-ban principles

- 下载走 CDN 签名直链，不带账号 cookie，与账号完全脱钩
- 串行 + 随机间隔 4-9s + 失速自动断线续传 + 多镜像轮换
- 账号仅在扫码登录与列表分页阶段使用（个位数请求）
- 安全 SDK 一拦截立即停手

## License

MIT
