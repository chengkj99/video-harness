# Video Harness

面向中文口播、分享和访谈的本地视频生产工作流。先审选题和文字，再剪视频，最后交付封面、描述与标签。

v0.2：Codex 插件 + Python 状态内核 + 本地审阅页 + 内置本地媒体后端。不是独立非线性编辑器，也不自动发布。

## 第一次使用：先准备工具

请先阅读 [工具准备与首次试跑](docs/setup.md)，按步骤准备 Python、FFmpeg/ffprobe、中文字体和媒体环境，再安装 Codex 插件。已有环境可直接执行指南中的环境检查和合成视频试跑。

**媒体代码、技能步骤和剪辑参考均已内置，不依赖其他技能仓库，也不需要另找后端。**按指南创建 Python 环境、安装依赖，执行 `video-harness configure` 和合成试跑后即可使用。模型仅在转写时需要，首次下载必须显式开启。

## 使用

在 Codex 里调用：

> 使用 $video-harness 处理这组视频，先给选题和可修改剪辑稿，确认后制作成片及发布配套。

审阅页支持点击一句回听原片、改字幕、删留句子、明确确认当前版本。也可以直接给 Codex “C0012 删除”“C0003 的字幕改成……”的指令。

## 本地安装到 Codex

已在当前本机 Codex CLI 验证以下原生插件命令：

```sh
codex plugin marketplace add /绝对路径/video-harness --json
codex plugin add video-harness@video-harness-local --json
codex plugin list --marketplace video-harness-local --json
```

插件包含核心代码，安装后入口不依赖开发仓库位置。新会话可发现技能；当前会话的技能列表不保证热刷新。变更开发源码后重新安装，并核对安装缓存文件，不把“源码已改”视为“已安装版已更新”。

## 环境

- Python 3.9+，核心只用标准库；`python3 -m video_harness --help` 无需 pip 安装。
- `pip install ".[media]"` 安装渲染依赖；需要转写时使用 `".[transcribe]"`（Python 3.10+，推荐 3.11）。`video-harness configure` 生成仓库外的本机 runtime。
- PNG 封面使用媒体环境中的 Pillow；不可用时交付 SVG 并明确提示，不能冒充 PNG 已生成。
- 首版验证平台 macOS；项目锁使用 POSIX flock，Windows 暂不支持。
- 无静默云端上传、模型下载和全局依赖安装。

## 从已有工程开始

```sh
python3 -m video_harness import-editor \
  --project /本地项目/第三条 \
  --from-project /已有剪辑工程 \
  --runtime /本机配置/runtime.json
python3 -m video_harness serve --project /本地项目/第三条 --port 8765
```

打开命令返回的本地 URL。媒体文件只从明确声明的素材列表读取，服务仅监听 127.0.0.1。终端关闭后可重新运行 serve，使用新链接；不同启动之间令牌不复用。

素材移动时：`--source-map /映射.json`，文件内容为 `{"S001":"/新位置/原片.MP4"}`。大小、mtime 和首尾采样指纹必须相同；否则拒绝导入，不自动修改身份。原工程不会被改写。

新素材先使用 `video-harness media init` 和 `media transcribe`，由 Agent 分析选段并通过 `media map-captions` 生成源锚点字幕，再导入工作流。完整命令见安装指南；坏转写必须回听校对。旧工程的显式 `--backend` 配置继续受支持，不自动迁移或沿用过期成片确认。

## 工作流

1. Codex 读取材料，填写 `topic.json`；用户确认选题。
2. 审阅 `review.md` 或网页；用户修改并确认剪辑稿。
3. 编译源区间、字幕与章节，调用后端渲染和验证。
4. 用户看成片；确认后交付正式本地发布包。
5. 发布包包括 MP4、SRT、封面、描述、标签、文字稿和校验清单。发布是独立动作。

`render --draft` 和 `package --draft` 可供审阅；不能当成正式确认。选题/稿件/成片确认绑定内容版本，不能沿用过期审批。审批原话记录在本地项目，不是登录认证系统。

详细命令：[工作流接口](skills/video-harness/references/workflow.md)。设计：[设计文档](docs/design.md)。实施：[计划](docs/implementation-plan.md)。

## 修改与恢复

```sh
python3 -m video_harness status --project /项目
python3 -m video_harness resume --project /项目
python3 -m video_harness edit --project /项目 --changes /改动.json --expected 当前script哈希
```

哈希由 Agent 管理，用户不必输入。`original/` 保留导入快照；`history/` 保留改稿；`builds/` 保留编译版本；`jobs/` 保留执行日志；`packages/` 新增交付版本。项目和媒体必须在代码仓库外。

- 改错字只改字幕，不改声音；自由改写不等于已补录。
- 删句同步剪音视频，不自动吞掉句间笑声与停顿。
- 稿件改变使成片过期；封面/描述变化不使视频过期。
- 首版只支持句级删除，不支持可靠自动词级拖音删除或重排句子。
- 技术验证不证明原意完整或全片字幕正确；必须如实记录审听范围。

## 测试

```sh
python3 -m unittest discover -s tests -v
# 包括本机 HTTP 集成测试：
VH_HTTP_TESTS=1 python3 -m unittest discover -s tests -v
# 真实媒体后端测试（生成合成视频，不使用用户素材）：
python3 scripts/smoke_media.py --runtime /runtime.json --output /新的临时目录
```

测试仅使用合成数据，审批记录标为测试，不得迁移到真实项目。实际渲染验证见 `docs/validation.md`。真实素材及完整用户文字稿不纳入仓库。

## 封面交付规范

默认双比例：竖版 3:4（1500×2000），横版 4:3（1600×1200）。故事化拼贴使用真实讲者参考、相关场景与观众视角标题，两版分别排版，检查身份、手部与中文；不通过拉伸改变比例。视频画幅独立配置。内置打包器提供双比例文字草稿，人物故事化封面通过图像工具完成。完整步骤见[封面规范](skills/video-harness/references/covers.md)。

## 面向陌生观众的剪辑审查

展示剪辑稿前检查开场能否独立理解、标题承诺何时兑现、句段功能和删减保真；改版时解释具体删留与时间变化。优先减少不必要背景和功能重复，保留例子、情绪、限定与观点变化过程。不开启自动删句或重排，不设固定时长，不承诺流量提升。

完整步骤及内置模板见[审查规范](skills/video-harness/references/audience-editing.md)。Agent 在仓库外的视频工程生成 audience-review.md 和 revision-notes.md，与剪辑稿及版本交付配套；无需其他技能仓库。
