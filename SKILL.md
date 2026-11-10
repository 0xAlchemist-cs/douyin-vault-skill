---
name: douyin-vault
description: >
  抖音博主全量知识库流水线：视频列表抓取（登录墙/分页陷阱）、防封限速下载、GPU large-v3 转录、
  AI 分析提炼问题、Obsidian vault 生成（相似度互联+图谱配色）、网页版私信/群聊历史深挖。
  Use when the user mentions 抖音博主, 抖音视频下载, 抖音字幕, 抖音转录, 抖音私信, 抖音群聊,
  视频转文字, whisper 抖音, or wants a creator's full works turned into an Obsidian knowledge base.
---

# 抖音博主 → Obsidian 知识库 全流程

一次实战验证过的完整管线：104 个视频全量抓取（0 失败）→ GPU 转录 → 516 个问题提炼 → 网状图谱知识库 + 群聊全量历史挖掘。下面每一步都标注了**踩过的坑**，照做可省数小时。

## 总体流程

```
登录浏览器 → 抓视频列表(videos.json) → 限速下载(download.py)
→ GPU 转录(transcribe.py) → AI 分析(analysis/*.md) → 组装 vault(build_vault.py) → Obsidian 打开
（可选）群聊深挖: 真滚轮翻虚拟列表 + protobuf 游标验证
```

## 第一步：抓视频列表（最大的坑在这里）

**必须用真实浏览器**（Playwright 等）：分享页 SSR 数据被风控、yt-dlp 403 要 cookie、老 iesdouyin API 全灭。

1. 打开 `douyin.com/user/<sec_uid>`，未登录只能看第一屏——**需要用户扫码登录一次**（`登录后查看更多作品` 消失即成功）
2. 分页接口 `/aweme/v1/web/aweme/post/` 由页面滚动触发，用 `page.on('response')` + `resp.json()` 接；或事后从 DevTools Network 逐个导出响应体
3. ⚠️ **坑 1：post 接口会漏视频**。实测漏了 6 条最新视频（含置顶附近的）。收尾必须**对账**：把页面滚到底收集 DOM 里所有 `/video/{id}` 链接，与 API 结果做差集；漏掉的用 detail 接口逐条补：
   ```
   fetch('/aweme/v1/web/aweme/detail/?device_platform=webapp&aid=6383&aweme_id=<ID>&pc_client_type=1&version_code=170400&platform=PC', {credentials:'include'})
   ```
   登录态下此接口可裸调（无需 a_bogus 签名），返回 desc/duration/play_addr(3 镜像)/create_time/digg_count
4. ⚠️ **坑 2：DOM 差集里的假阳性**。滚到底后抖音会混入"推荐"视频（其他博主）。按卡片文案/标签风格人工判别，别盲目全抓
5. 产物 `videos.json`：`[{id, desc, dur_ms, urls:[3个镜像], create, digg}]`，按 create 倒序

**翻页 UI 技巧**：用户页是内层容器滚动（不是 window）。找 `overflow-y: auto/scroll && scrollHeight > clientHeight` 的最大元素滚它。MCP 单次调用有 30s 上限时，把滚动循环拆成多次调用。

## 第二步：防封下载（download.py）

原则：**你的账号只在列表阶段用过，下载阶段与账号完全脱钩。**

- 串行不并发，每文件随机间隔 4-9s（`SystemRandom`）
- 只走 CDN 签名直链（play_addr 的 url_list），**不带任何 cookie**，仅 UA + Referer
- ⚠️ **坑 3：CDN 会失速**。纯 urllib 会挂在半速连接上——用 curl `--speed-limit 30000 --speed-time 30`（低于 30KB/s 持续 30s 自动断），`-C -` 断点续传，多镜像轮换重试
- 安全基线：https + 域名白名单 + `getaddrinfo` 解析后阻断私网/环回/链路本地 IP + 禁自动重定向 + 文件名 `^\d{3}_\d{8,25}\.mp4$` 正则锁定

## 第三步：GPU 转录（transcribe.py）

RTX 4060 + large-v3 实测 **14x 实时**（small）/~6x（large-v3），453 分钟音频几十分钟跑完。

- `pip install faster-whisper nvidia-cublas-cu12 nvidia-cudnn-cu12`
- ⚠️ **坑 4：HF 直连被拒** → `HF_ENDPOINT=https://hf-mirror.com`；模型也可 curl 直下到本地目录后传路径
- ⚠️ **坑 5：模型能 load 但推理报 `cublas64_12.dll not found`** → ctranslate2 内部 LoadLibrary 不走 `os.add_dll_directory`。**必须 `ctypes.CDLL()` 预加载驻留**（cublas64_12 / cublasLt64_12 / cudnn64_9）
- ⚠️ **坑 6：faster-whisper 1.2.1 与新版 PyAV 的 `metadata_errors` 参数冲突** → 别传文件路径，wave 读进 numpy 数组直喂
- manifest 断点续跑：每条落 `transcripts/{id}.txt + .srt` + manifest.json，重跑自动跳过

## 第四步：AI 分析（模板化）

每个视频产出 `analysis/{seq}_{id}.md`，**按 id 匹配**（seq 会因补漏重排而漂移）：

```markdown
## 一句话摘要      （30-60字）
## 核心观点        （2-5条，保留原话关键表述）
## 提炼的问题      （3-6条具体可回答的问题 ← 用户要的核心交付）
## 主题            （从固定清单选 1-2 个，保证主题页可聚合）
```

- 主题清单先定死（如：出海求职/英语学习/非洲市场/销售技能/AI时代/认知心态/创业生意），多 agent 并行分析时才不会各写各的
- 逐字稿错字（whisper 常见：内罗毕/乞力马扎罗/简历/见龙在田）让分析者按上下文还原，不照抄
- 子代理额度触顶时：剩余条目主 agent 自己读稿手写，模板不变

## 第五步：Obsidian 组装（build_vault.py）

- MOC 首页 / `视频笔记/`（元信息+摘要+观点+问题勾选框+主题链接）/ `主题/` / `问题清单/总问题库` / `逐字稿/`
- **相似度互联**：分析文本字符二元组 TF 余弦 + 同主题加分 → 每篇自动链 3 篇"相关笔记"，图谱从星型变网状
- **graph.json 预置**：按路径配色（主题橙/笔记蓝/问题绿）+ `-path:"逐字稿"` 隐藏杂线
- ⚠️ **坑 7：`obsidian://open?path=` 只认已注册 vault**。新库直接弹 "Vault not found"。解法：写入 `%APPDATA%/obsidian/obsidian.json` 的 vaults 注册表（先备份），**重启 Obsidian**（运行中内存缓存不重读配置）
- ⚠️ **坑 8：build 脚本若整删 vault 重建会连 .obsidian 一起删**——先关 Obsidian 再 build，或 build 后重写配置

## 第六步（可选）：群聊/私信历史深挖

网页版私信是**虚拟列表**，三个坑：

1. ⚠️ **坑 9：`scrollTop = 0` 赋值不触发翻页，只有真实滚轮事件（`mouse.wheel(-N)`）才加载更早消息**
2. ⚠️ **坑 10：滚到底会混入左侧会话栏的行（它也是虚拟列表、也有 data-index）**——收集范围必须限定在消息面板容器内；且列表回顶后 **data-index 会整体重置**，跨阶段合并按文本去重，别信索引
3. 采集法：边滚边收集 `[data-index]` 的 innerText 到 Set；卡住（橡皮筋回弹、scrollTop 变负）就**先滚回底部再上翻**解 deadlock

**服务器级验证（到底有没有更早）**：DevTools 抓 `imapi.douyin.com/v1/message/get_by_conversation` 的请求体（二进制 protobuf）。内层结构：
`\n<convid> \x10\x02 \x18<convid varint> \x20\x01 \x28<游标µs时间戳> \x30<limit>`
把 field5 游标改成目标时间（µs），从页面上下文 `fetch(imapi..., {method:'POST', credentials:'include', headers:{'Content-Type':'application/x-protobuf'}, body: Uint8Array})` 重放。**响应 2 字节 = 该时间前无任何消息**（群创建时间的决定性证据）。
⚠️ 坑 11：DevTools "Copy" 会把二进制损坏成 UTF-8 替换符——用 CDP `Network.getRequestPostData` 拿干净 base64。重复重放会触发 secsdk 拦截，**拿到答案就停，别硬刚**。

## 防封红线（全程）

- 账号操作只发生在：扫码登录（1 次）+ 列表分页（个位数请求）+ 打开会话（个位数）
- 下载、转录、分析、建库全程零账号依赖
- 任何接口不并发、不重放轰炸；风控 SDK 一拦就收手

## 脚本清单（scripts/）

| 脚本 | 用途 |
|---|---|
| `download.py` | 限速防封下载（curl 失速检测+续传+镜像轮换） |
| `transcribe.py` | ffmpeg 抽音频 + GPU large-v3 转录（CUDA DLL 预加载，断点续跑） |
| `build_vault.py` | videos.json + analysis + transcripts → Obsidian vault（含相似度互联与 graph 预置） |
| `im_pb.py` | imapi protobuf 解码（消息抽取/游标定位） |

## 验收清单

- [ ] 视频数 = 主页作品数（DOM 对账，差集逐条补 detail）
- [ ] 下载 0 失败（失败 id 列表为空）
- [ ] transcripts 数 = 视频数（manifest 全 ok）
- [ ] analysis 数 = 视频数（按 id 匹配）
- [ ] vault 笔记数/问题数与 MOC 首页统计一致
- [ ] Obsidian 能打开，图谱有颜色分层和横向连线
