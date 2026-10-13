# Agent-autodemo TODO

- **updated**: 2026-09-12 10:30
- **work_root**: 0-Agent-demo/_demo_eval
- **slot**: _demo_eval
- **phase**: confirm
- **current**: 本仓库无 2-eval.sh
- **next**: 用户指定官方评测套件后再封装，或保持 skipped
- **blocked**: 无统一评测入口

## Meta
- conda: qwen
- entry: 本仓库暂无
- customer: Customer.md §202609
- spec: 无
- log_dir: 0-Agent-demo/_demo_eval/logs
- results_dir: 0-Agent-demo/_demo_eval/0-results

## Checklist
- [x] §0.1 工作目录门禁（完备 / 构建 / 跳过）
- [x] §2 确认 / 填写 Customer.md
- [x] §5 发现并冻结本仓库入口
- [ ] §4 检查环境与产物路径
- [ ] §4 执行（按单元一行）
- [ ] §4 写回 0-results
- [ ] §4 交付摘要

## Runs
| id | status | artifact | note |
| --- | --- | --- | --- |
| official-eval | skipped | | 无 2-eval.sh；官方脚本在 Qwen/evaluation/ |

## Notes
- 禁止编造 eval 命令。需要评测时从 MMMU / MathVision / RealWorldQA / VideoMME / ODinW-13 中指定一套再封装。
