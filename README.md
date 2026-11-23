# douyin-vault-skill

抖音博主全量知识库流水线 → Obsidian 网状图谱。一次部署，增量更新终身可用。

**Douyin creator → Obsidian knowledge base pipeline. Deploy once, increment forever.**

## 它能干什么

把一个抖音博主的**全部内容**（视频 + 私信群聊）转化为一座可搜索、可自测、可视化的 Obsidian 知识库：

```
博主主页 ──→ 全量视频抓取 ──→ GPU 语音转写 ──→ AI 分析提炼 ──→ Obsidian 知识库
    │                                                              ↑
    └──→ 群聊 10,551 条全量历史 ──→ 168 组答疑 + 情报 + 金句 ──────┘
```

包含：
- **视频笔记**（每篇含摘要 + 核心观点 + 可勾选的问题清单）
- **总问题库**（全部问题 + 折叠答案，点击展开自测）
- **主题页**（7 大主题自动聚合）
- **网状图谱**（内容相似度互联 + 路径配色，`Ctrl+G` 查看）
- **群聊课堂**（服务器直连全量抓取，按周分段提炼）

## 实战战绩

| 指标 | 数据 |
|---|---|
| 视频全量抓取 | **111 条，0 失败**（含 post 接口漏掉的 6 条 + 增量 7 条） |
| GPU 转录 | RTX 4060 + faster-whisper large-v3，~6x 实时，500+ 分钟音频 |
| 问题库 | **553 个可勾选问题，521 个带折叠答案** |
| 群聊历史 | **10,551 条全量**（UI 只能看 340 条，服务器直连突破） |
| 群聊提炼 | 168 组群主答疑 + 130 条情报 + 110 条金句 |
| 踩坑实录 | **16 个坑**全部标注解法，照做可省数小时 |

## 快速开始

> **重建会删除现有输出。** `build_vault.py` 会先递归删除 `-o` / `--out` 指向的整个现有目录，再重新生成，不会保留手写笔记、勾选进度或 `.obsidian` 配置。请使用独立的生成目录，不要指向日常 Obsidian 库或输入数据目录。重跑前，把要保留的内容完整备份到输出目录之外。

```bash
# 0. 安装
git clone https://github.com/0xAlchemist-cs/douyin-vault-skill ~/.zcode/skills/douyin-vault

# 1. 用真实浏览器登录 douyin.com 抓博主视频列表为 videos.json
#    格式: [{id, desc, dur_ms, urls:[直链...], create, digg}]

# 2. 限速防封下载
python scripts/download.py videos.json -o D:/data/videos

# 3. GPU 转录 (先 pip install faster-whisper nvidia-cublas-cu12 nvidia-cudnn-cu12)
python scripts/transcribe.py D:/data/videos -o D:/data

# 4. AI 逐条分析 → analysis/{seq}_{id}.md (模板见 SKILL.md)

# 5. 组装 Obsidian vault（使用独立的生成目录）
python scripts/build_vault.py D:/data -o D:/douyin-vault-generated --themes themes.json

# 6. 增量更新完成后删除视频文件 (释放磁盘 + 防止重下)
rm -f D:/data/videos/*.mp4 D:/data/audio/*.wav
```

完整方法论与 **16 个踩坑实录**见 [SKILL.md](SKILL.md)。

## 16 个坑（每一个都是实战踩出来的）

| # | 坑 | 一句话解法 |
|---|---|---|
| 1 | post 接口漏最新视频 | DOM 对账 + detail 接口补 |
| 2 | 推荐流混入 DOM | 验 author.uid 才入库 |
| 3 | CDN 半速卡死 | curl --speed-limit + 断点续传 |
| 4 | HuggingFace 被墙 | HF_ENDPOINT=hf-mirror.com |
| 5 | CUDA 推理报 cublas 缺失 | ctypes.CDLL 预加载驻留 |
| 6 | PyAV 参数不兼容 | numpy 数组直喂 |
| 7 | obsidian:// 不认新库 | 写 vault 注册表 + 重启 |
| 8 | 重建会删除整个输出目录 | 使用独立生成目录，先把要保留的内容备份到输出目录之外 |
| 9 | scrollTop=0 不翻页 | 真实滚轮事件 |
| 10 | 侧栏混入 + 索引重置 | 容器内收集 + 文本去重 |
| 11 | DevTools 复制损坏二进制 | CDP getRequestPostData |
| 12 | IM 直连报 body empty | field8 里必须包 field301 |
| 13 | clearCookies 丢失登录态 | **永不主动清 Cookie** |
| 14 | mp4 清空后批量脚本重下全部 | 只下载新视频单独 curl |
| 15 | headless 不支持聊天页 | headless: false + persistentContext |
| 16 | 增量后忘删 mp4/wav | 转录完立即 rm，释放磁盘 |

## 防封原则

- 下载走 CDN 签名直链，**不带账号 cookie**，与账号完全脱钩
- 串行 + 随机间隔 4-9s + 失速自动断线续传 + 多镜像轮换
- 账号仅在扫码登录与列表分页阶段使用（个位数请求）
- IM 直连翻页限速 100-500ms/页，全量即停
- 安全 SDK 一拦截立即收手

## 脚本清单

| 脚本 | 用途 |
|---|---|
| `download.py` | 限速防封下载（curl 失速检测 + 续传 + 镜像轮换） |
| `transcribe.py` | ffmpeg 抽音频 + GPU large-v3 转录（CUDA DLL 预加载，断点续跑） |
| `build_vault.py` | videos.json + analysis + transcripts → Obsidian vault（相似度互联 + graph 预置；重建会删除整个输出目录） |
| `im_pb.py` | imapi protobuf 解码（消息抽取 / 游标定位） |

## 安装

```bash
# ZCode / Claude Code
git clone https://github.com/0xAlchemist-cs/douyin-vault-skill ~/.zcode/skills/douyin-vault

# 或复制到你的 agent 技能目录
# 提到"抖音博主知识库"、"抖音字幕"、"群聊提取"即自动路由
```

## License

MIT
