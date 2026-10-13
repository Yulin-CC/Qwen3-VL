# Agent-autodemo TODO

- **updated**: 2026-09-12 10:30
- **work_root**: 0-Agent-demo/_demo_train
- **slot**: _demo_train
- **phase**: confirm
- **current**: 等待确认 Customer.md
- **next**: 确认目的 / 权重 / 数据后开训
- **blocked**: 无

## Meta
- conda: qwen
- entry: bash 0-QuickStart/0-train.sh
- customer: Customer.md §202609
- spec: 无
- log_dir: 0-Agent-demo/_demo_train/logs
- results_dir: 0-Agent-demo/_demo_train/0-results

## Checklist
- [x] §0.1 工作目录门禁（完备 / 构建 / 跳过）
- [ ] §2 确认 / 填写 Customer.md
- [x] §5 发现并冻结本仓库入口
- [ ] §4 检查环境与产物路径
- [ ] §4 执行（按单元一行）
- [ ] §4 写回 0-results
- [ ] §4 交付摘要

## Runs
| id | status | artifact | note |
| --- | --- | --- | --- |
| | pending | | |

## Notes
- 入口映射：0-QuickStart/0-train.sh → 0-QuickStart/scripts/train.py → Qwen/qwen-vl-finetune
