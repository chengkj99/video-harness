# 工具准备与首次试跑

媒体处理代码已内置。克隆本仓库即可获得完整代码，不需要获取其他技能或私有脚本。依赖安装需要网络；安装完依赖和模型后，剪辑在本机执行，不上传视频。系统工具、字体、模型权重和真实项目不随 Git 分发。

## 1. 准备工具

推荐 macOS + Python 3.11。Linux 提供安装命令和 CI 媒体测试；Windows 原生暂不支持（项目锁依赖 POSIX flock）。Codex 用于分析与交互，命令行媒体工具可以独立运行。

| 工具 | 用途 | 是否必需 |
|---|---|---|
| Git、Python 3.11、pip/venv | 获取代码和运行环境 | 是 |
| FFmpeg、ffprobe | 编解码、剪切、音频和验证 | 是 |
| Pillow、中文字体 | 字幕画面与 PNG 封面 | 是 |
| faster-whisper + 模型 | 本地语音转文字 | 需要转写时 |
| Codex App/CLI | 调用插件、分析选题与审稿 | 使用 Codex 工作流时 |

无需 ChatCut、GPU 或云端 API Key。磁盘需容纳原片、缓存和多个导出版本；工具执行媒体任务时会检查可用空间。

macOS：先按 [Homebrew 官方说明](https://brew.sh/) 安装 Homebrew，然后：

```sh
brew install git python@3.11 ffmpeg
```

使用系统自带中文字体；若找不到，可安装有授权的中文字体并设置 `THE_FONT` 为字体绝对路径。

Ubuntu/Debian（使用发行版提供的 Python 3.10+）：

```sh
sudo apt-get update
sudo apt-get install git python3 python3-venv python3-pip ffmpeg fonts-noto-cjk
```

## 2. 克隆并安装

macOS 下面使用 `python3.11`；Linux 可换成 `python3`。命令在同一个终端顺序运行：

```sh
mkdir -p "$HOME/work"
git clone https://github.com/chengkj99/video-harness.git "$HOME/work/video-harness"
cd "$HOME/work/video-harness"
python3.11 -m venv "$HOME/.local/share/video-harness/venv"
source "$HOME/.local/share/video-harness/venv/bin/activate"
python -m pip install --upgrade pip
python -m pip install '.[transcribe]'
```

如果已有带源时间戳的字幕，不做语音转写，可把最后一行换成 `python -m pip install '.[media]'`。核心审稿功能仅依赖标准库；媒体环境推荐 Python 3.11。安装失败时确认正在使用虚拟环境，不要使用 `sudo pip`。转写依赖参考 [faster-whisper 官方说明](https://github.com/SYSTRAN/faster-whisper)。

## 3. 检查并保存本机配置

```sh
video-harness configure
video-harness media doctor
# 安装转写依赖后可额外检查：
video-harness media doctor --transcription
```

`configure` 检查当前 Python、FFmpeg、ffprobe、Pillow 和字体，通过后将路径保存到 `~/.config/video-harness/runtime.json`（遵循 XDG_CONFIG_HOME）。不会安装工具、下载模型或覆盖已有配置。环境缺失时退出非零并报告原因。

`doctor` 必要媒体依赖缺失时退出非零；`--transcription` 还检查 faster-whisper。报告的 `model_ready: not_checked` 表示没有实际加载模型，目录存在不证明模型就绪。

自定义配置可用 `video-harness configure --output /绝对路径/runtime.json`，之后设置 `export THE_RUNTIME_CONFIG=/绝对路径/runtime.json`。自定义工具使用 `THE_FFMPEG`、`THE_FFPROBE`、`THE_FONT`、`THE_MODEL_DIR`；这些环境变量优先于配置。同名配置已存在时先检查内容，需切换环境则写新文件，不自动覆盖。

插件会通过 runtime 找到媒体 Python，不要求每次在 Codex 中激活 venv。请保留虚拟环境目录；移动或删除后需要重新配置。

## 4. 用合成视频试跑

回到仓库根目录，保持虚拟环境激活：

```sh
python scripts/smoke_media.py --output "$HOME/Movies/video-harness-smoke-01"
```

输出目录必须不存在。测试自动生成 6 秒色块及测试音频，删除 1 秒字幕对应区间，导出 5 秒视频，并检查字幕、完整解码、时长、审批阻断与发布包。最终 `passed: true` 才算通过；结果保存在输出目录的 `result.json`。不会读取你的真实视频，测试审批不能复制到真实工程。

## 5. 安装 Codex 插件

确认 Codex 已安装并登录，CLI 可执行：

```sh
codex plugin marketplace add "$HOME/work/video-harness" --json
codex plugin add video-harness@video-harness-local --json
codex plugin list --marketplace video-harness-local --json
```

开启新会话后使用 `$video-harness`。插件包含工作流和媒体代码；Python 依赖仍由前面配置的虚拟环境提供。更新源码后重新 `pip install '.[transcribe]'` 并重新执行插件安装命令，以刷新两份安装；必要时重启会话。

可以这样告诉 Codex：

> 使用 $video-harness 处理我指定的视频。先检查环境，再分析完整素材，给出选题候选。等我确认选题及逐句剪辑稿后制作；区分提问者与回答者，保留原意、逻辑和情绪。项目保存在仓库外，不上传素材。

## 6. 从原片开始

以下路径为占位符，换成自己的绝对路径。`media init` 只创建新/空目录，不改变原片：

```sh
video-harness media init --project /本地项目/素材工程 /原片/分享.mp4
video-harness media transcribe --project /本地项目/素材工程 --source S001 --model small --allow-download
```

第二条命令显式允许首次下载模型，需要网络和存储空间。CPU 使用 int8；首次加载和长视频转写可能较慢。后续去掉 `--allow-download` 即为仅使用本地模型；缺少模型会报错，不自动联网下载。可先加 `--limit 60` 测试 60 秒，完整转写再去掉该参数；样本结果不能冒充全文。

转写返回 `transcript` 的 JSON 路径。多段素材逐个使用 S001、S002 等 source ID 转写。Codex 阅读完整转写、选择源区间、修改 plan.json 后，再将转写映射到时间线：

```sh
video-harness media map-captions --project /本地项目/素材工程 /转写输出/merged.json
video-harness import-editor --project /本地项目/审稿工程 --from-project /本地项目/素材工程
video-harness serve --project /本地项目/审稿工程 --port 8765
```

多源转写可在 map-captions 后依次提供多个 JSON 路径。映射只允许初始化空字幕；已有字幕不要清空覆盖。具体选段及源锚点字段见 [媒体工程接口](media-backend.md)。自动转写仍需回听校对；说话人标签需根据原声确认，工具不自动辨认身份。

之后按插件引导依次确认选题、剪辑稿、成片，再生成交付包。视频比例、字幕样式、片尾均可配置；默认没有个人品牌或片尾关注文案。

## 兼容与排错

- 旧工程显式 `--backend /旧后端/scripts/run.py --runtime /旧配置/runtime.json` 仍支持；不自动改写旧工程或审批。新工程省略 backend 即使用内置代码。
- `ffmpeg/ffprobe unavailable`：检查安装和 PATH，或设置对应 THE_* 绝对路径后重新配置。
- Pillow 缺失：在媒体虚拟环境执行 `python -m pip install '.[media]'`；不要误装到另一个 Python。
- 字体错误/乱码：将 THE_FONT 指向支持中文的合法字体；重新生成配置并试跑。
- ASS 滤镜不可用：渲染 auto 模式回退 Pillow；无需为了此项安装另一个后端。
- 模型不可用：确认缓存和模型名称；只有显式 `--allow-download` 才允许下载。
- 原片无声轨：首版要求同时有视频和音频，需显式处理无声片，不能自动补造语音。
- 插件找不到依赖：检查 runtime 的 python 路径；安装插件不等于安装 Python 依赖。
- 环境改变后先重新 doctor 和 smoke；后端/工具变化可能使成片确认过期，不能绕过复核。

安装完成标准：doctor 通过、合成 smoke 通过、Codex 能发现技能；需要转写时再完成一次真实样本转写。没有完成的检查应明确标为未验证。
