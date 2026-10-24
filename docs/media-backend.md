# 内置媒体后端与兼容接口

媒体代码迁入自 `chengkj99/kj-skills` 的 `skills/talking-head-editor`，保留其 MIT 版权声明（`video_harness/media_backend/LICENSE`）。本仓库维护内置版本，原仓库文件不改动。FFmpeg、Pillow、faster-whisper 等由各自发行渠道安装，遵循各自许可证；不分发工具二进制、字体或模型权重。

入口为 `video-harness media --help`。支持 doctor、init、prepare、transcribe、map-captions、patch-caption、preview、render、verify。媒体工具是底层工程接口，不代替工作流的选题、稿件和成片确认；正式交付仍使用顶层 render/package。

工程的 project.json 声明 source ID、路径与探测元数据；plan.json 指定 width/height/fps、title、clips、chapters。每个 clip 包含 id、source_id、start/end（源秒数）、framing（fit/crop）；时间线按 clips 顺序拼接。map-captions 将完整转写的源时间映射为时间线字幕，保存 source_id/edit_id/start/end 源锚点。调整时间线必须先重新核对映射，不能修改既有字幕源锚点掩盖不同步。

新导入工程存储 backend=builtin，运行时定位安装包内后端；可选 --backend 保留外部脚本兼容。原项目保持原配置，不自动迁移。工作流对媒体脚本和显式 runtime 做版本校验；更新后旧成片需要复核。运行环境、模型及工程均保存在仓库外。

技能所需的长素材处理、字幕校对和样式指南同步内置于 skills/video-harness/references/；来源仓库名称仅用于归属说明，不是安装或运行依赖。
