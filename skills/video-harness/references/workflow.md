# 工作流接口

首次部署先读仓库内的 [工具准备指南](../../../docs/setup.md)。后端已内置；FFmpeg/ffprobe、Pillow、中文字体按指南安装；模型仅在转写时需要。先执行 `media doctor`（缺少必要依赖时退出非零），再做合成媒体试跑。模型目录存在不代表转写模型可用。

以下 `vh` 代表 `python3 <本技能>/scripts/run.py`。Python 3.9+；推荐媒体环境使用 Python 3.11；运行 configure 记录环境，插件不自动下载依赖。

```sh
vh import-editor --project /项目新目录 --from-project /旧剪辑工程 --runtime /runtime.json
vh status --project /项目目录
vh review --project /项目目录
vh serve --project /项目目录 --port 8765
vh edit --project /项目目录 --changes /修改.json --expected <script哈希>
vh approve --project /项目目录 topic --expected <topic哈希> --chat-confirmed --evidence '用户确认原话'
vh approve --project /项目目录 script --expected <script哈希> --chat-confirmed --evidence '用户确认原话'
vh compile --project /项目目录
vh render --project /项目目录 --draft
vh render --project /项目目录
vh approve --project /项目目录 film --expected <film哈希> --chat-confirmed --evidence '用户确认原话'
vh package --project /项目目录
```

`status`/`resume` 返回 gates 的当前哈希、是否已确认与 next。它不替用户确认；媒体缺失/源变更会失败，不要更新指纹消除错误。CLI 聊天确认依赖 Agent 真实记录人类回复，不是身份认证系统。

修改文件为数组：`[{"id":"C0001","text":"纠正识别文字"},{"id":"C0002","keep":false}]`。恢复删句设 keep=true；speaker 可改。保留原 ID；句内切割和重排不属于第一版。

可编辑配置：topic.json（选题）；story.json（删留、字幕和角色，推荐经 edit 修改）；style.json（后端视觉/音频配置）；copy.json（标题、描述、tags 数组、cover_lines 1–5 行、cover_size 宽高、platform）。直接手改也会被哈希检测，但建议用 edit 保留改稿快照。

原始快照在 original/；编译工程 builds/；执行日志 jobs/；packages/ 按版本新增。原始媒体只记录外部绝对路径。程序只做技术验证，semantic_review 仍为 not_asserted。

第一版不自动抓选题、不调用模型。当前 Codex 根据真实材料生成选题和文案，CLI 管理确定性状态和媒体执行。新素材转写使用内置媒体后端；依赖或模型未准备好时不可声称已完成转写或剪辑。

封面配置增加 `cover_sizes`：portrait=[1500,2000]、landscape=[1600,1200]。省略时使用双比例默认值；旧 cover_size 控制兼容主封面。设计与检查见 [covers.md](covers.md)。

## 面向陌生观众的审查产物

展示剪辑稿前按[审查规范](audience-editing.md)执行，使用[审查模板](../templates/audience-review.md)与[版本说明模板](../templates/revision-notes.md)，由 Agent 在仓库外工程中生成 audience-review.md 和 revision-notes.md；CLI 不自动生成这些文件。它们补充现有 review.md，不修改 story.json、审批哈希或命令接口，也不替代用户确认。

审查记录用字幕 ID 或源时间定位；编译后填实际成片位置，估计须标注。每次改版前保留旧记录，交付时一并提供当前审查与版本说明。现有 package 命令不会自动收录这两份文件，可作为交付包旁的配套文件提供，不改写已生成的包及其清单。不得把预计结构收益表述为已验证的流量改善。
