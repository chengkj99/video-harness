# 工作流接口

以下 `vh` 代表 `python3 <本技能>/scripts/run.py`。Python 3.9+；媒体依赖放在外部后端 runtime，不在插件里下载。

```sh
vh import-editor --project /项目新目录 --from-project /旧剪辑工程 --backend /talking-head-editor/scripts/run.py --runtime /runtime.json
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

第一版不自动抓选题、不调用模型。当前 Codex 根据真实材料生成选题和文案，CLI 管理确定性状态和媒体执行。新素材转写复用 talking-head-editor；未配置该后端不可声称已完成剪辑。
