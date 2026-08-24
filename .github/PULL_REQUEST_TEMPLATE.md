## 本次改动

<!-- 说明问题、改动目标和范围。一个 PR 只处理一个主题。 -->

## 影响范围

- [ ] 抽取 Stage / Agent
- [ ] Prompt / 模型配置
- [ ] Schema / 对象关系
- [ ] Web API
- [ ] 前端页面
- [ ] `batch_results`
- [ ] 部署配置
- [ ] 文档或测试

## 兼容性

<!-- 说明旧 candidate、旧批次、旧 API 或 Strict/Preview 是否受影响。 -->

## 验证结果

- [ ] `python -m pytest extraction/tests -q`
- [ ] `python -m pytest ocr/tests -q`
- [ ] `python -m pytest preview/tests -q`
- [ ] `python -m pytest web_api/tests -q`
- [ ] `python preview/validate_published_batches.py batch_results`
- [ ] `npm ci && npm run lint && npm test && npm run build`（`web_portal`）
- [ ] 已完成论文 → 聚合物 → 样品 → 性质的端到端页面检查

## 数据与科学语义

- [ ] 对象 ID 和跨对象引用有效
- [ ] 无法唯一绑定的数据保留为 unresolved，没有猜测绑定
- [ ] 性质、工艺和表征均保留证据关系
- [ ] 没有把冻结测试集答案写入 Prompt、规则或生产代码
- [ ] 新批次使用不可变目录并记录生成代码 SHA（不适用时勾选并说明）

## 安全与发布

- [ ] 不包含 `.env`、API Key、SSH 私钥、服务器密码或用户凭据
- [ ] 不包含无公开分发权限的 PDF 或模型原始响应
- [ ] 不包含本机绝对路径、运行缓存或临时文件
- [ ] 已说明 API 成本、并发、超时或重试变化
- [ ] 已提供风险和回滚方式

## 页面截图或结果摘要

<!-- 页面改动附桌面/移动截图；算法或数据改动附关键指标与失败样例。 -->

## 回滚方式

<!-- 说明如何恢复到合并前行为或上一批次。 -->
