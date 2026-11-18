---
name: polymer-identity
description: 使用 Codex gpt-6.1-sol/xhigh 从文献或来源结构生成聚合物化学身份与最可能 IUPAC 名称，并从封存后的工具缺口提炼、验证和发布通用命名能力扩展。
---

# Polymer Identity

这是聚合物身份与命名技能，调用 Polymer Identity App 的现有 Kernel/create_passport/NamingService；运行化学内核为0.9.0。技能保存通用方法和已验证路线，不保存论文答案库，不训练模型权重。

## 输入求解

用户指定原PDF、来源文本或结构及需要执行的数量时，按 [求解方法](references/solve.md) 处理。宿主在项目目录开发或安排执行前读取README.md及docs/STATUS.md，确认当前实现与授权；这两个文件含历史案例，不能提供给论文核心或中性能力验证会话。核心读取自己任务的AGENTS.md、implementation.json、skill-method.md、naming-guide.md、来源及当前状态。在项目目录由宿主使用配置中的Python启动：

```text
python resources/polymer-identity/scripts/identity_skill.py preflight
python resources/polymer-identity/scripts/identity_skill.py run --pdf <原PDF绝对路径>
```

在其他目录调用安装的技能脚本时加 `--app <项目绝对路径>`。每篇使用一个持续gpt-6.1-sol/xhigh/workspace-write会话，逐篇串行，默认原60分钟截止，同SID恢复不延长。只处理本次明确指定的输入，不启动旧队列。主会话只读自己的中性来源、当前状态、通用求解资料和领域工具；人工JSON、其他论文及历史化学答案不进入求解。

如果当前目录已经有本任务run.json、AGENTS.md和run_tool.py，就在已有任务与截止内调用run_tool.py；不再调用技能脚本的run或preflight启动另一个会话。中性维护会话只读取其AGENTS.md明确列出的通用资料、代码和本地中性输入；不得读取应用README/STATUS、历史报告或其他任务答案。封存后来源回查只能读取宿主为本次回查单独分阶段提供的原文与候选包，不能据此扩大访问范围。

输出最可能且有依据的名称、实际适用范围、来源、假设与保留问题。区分模型结构名候选、图名一致、来源型名称、优选名认证和实物身份。证据不足时给出可成立的较宽名称或显式可行假设，不把工具缺口当化学错误，也不凭合理性改写原文。最可能假设需要比较真实备选及来源理由。

## 能力提升闭环

用户要求优化，或本次授权批次完成后需要整理反馈时，读取 [能力提升方法](references/improve.md)。执行器在封存后自动生成只读绑定反馈；用以下命令汇总一般工具缺口和实际路线：

```text
python resources/polymer-identity/scripts/identity_skill.py collect
```

在没有活动论文的批次边界，由Codex gpt-6.1-sol/xhigh能力维护会话审阅反馈、查询权威IUPAC规则，提出可复用的规则/工具改进。候选扩展须通过中性变体、反例、历史回放、同型号模型复审及真实CLI检查，再显式发布到下一批。新论文不会自动改写运行中的技能或工具；候选反馈不会自动成为命名规则。

模型复核和工程检查分别记录，不称人工审核或独立化学认证。完整论文交付不等于新命名路线已实际使用，更不等于科学准确率证明。所有版本、撤回和封存证据保持可回放。
