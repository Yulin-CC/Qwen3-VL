用户说「批量生成描述 / caption」「跑 generate」「续跑 draft」时，Agent 按同目录 `SKILL.md` 执行：

1. 用填空题确认：数据集目录、规则场景、模型服务、规模、是否 force
2. 探测本包 `model/server.json` 的 vLLM 连通性
3. 先 `--limit 1` 看短语形态，再全量；产物只进 `draft/`

新场景规则走 `standard-rules`，不要在本 Skill 里改 md。
