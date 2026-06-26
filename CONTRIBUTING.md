# Contributing

本项目主要由个人维护，并会持续使用 Codex、Claude、ChatGPT 等 AI 工具辅助开发。这里固定一套简单、实用的 Git 规范，目标是让后续改动清晰、可 review、可回滚。

## Branches

主分支是 `main`。主分支保持稳定，日常开发不要直接在主分支提交。

每个功能、修复、重构或文档调整都从 `main` 新建独立分支：

| 分支前缀 | 用途 | 示例 |
| --- | --- | --- |
| `feature/xxx` | 新功能 | `feature/user-login` |
| `fix/xxx` | 修复问题 | `fix/order-status-null` |
| `refactor/xxx` | 代码重构 | `refactor/device-binding` |
| `docs/xxx` | 文档修改 | `docs/update-readme` |
| `chore/xxx` | 配置、依赖、工程化调整 | `chore/git-workflow` |

## Commits

Commit 使用简单的 Conventional Commits 风格：

```text
<type>(scope): <description>
```

常用类型：

| 类型 | 说明 |
| --- | --- |
| `feat` | 新功能 |
| `fix` | 修复问题 |
| `refactor` | 重构 |
| `docs` | 文档 |
| `test` | 测试 |
| `chore` | 配置、依赖、杂项 |
| `style` | 格式调整 |
| `perf` | 性能优化 |

示例：

```text
feat(auth): add login validation
fix(device): handle empty device list
refactor(api): simplify response handling
docs(git): add workflow guide
chore(deps): update dependencies
```

## AI Development Guidelines

- AI 可以修改业务代码。
- 每次修改前先明确本次任务目标。
- 一次提交只做一类事情。
- 避免把无关格式化、重构、功能开发混在一个提交里。
- 提交前需要检查代码是否能运行。
- 不提交 `.env`、密钥、token、账号密码等敏感信息。
- AI 生成代码不需要在 commit message 里特别标注，除非项目明确要求。
- 开发者最终需要 review AI 生成的代码。

## Recommended Workflow

```bash
git checkout main
git pull
git checkout -b feature/xxx

# 修改代码

git add .
git commit -m "feat(scope): description"
git push origin feature/xxx
```

然后通过 PR / MR 合并到 `main`。

## Before Commit

提交前建议至少完成：

- 确认本次改动范围聚焦。
- 运行相关测试或最小可行验证。
- 检查 `git status`，确认没有误提交日志、数据库、虚拟环境或本地 IDE 配置。
- 检查没有提交 `.env`、API key、飞书 webhook、token、账号密码等敏感信息。

