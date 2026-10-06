# 贡献指南

先读 [AGENTS.md](AGENTS.md)、[README](README.md)、[实施计划](docs/implementation-plan.md)、本次SPEC与相关ADR。代码、文档和原创题目采用MIT；外部素材需独立来源和许可记录。不得提交家庭数据库、儿童信息、证书私钥、模型权重或私有声音。

使用锁定环境：`npm ci`、`uv sync --locked`，浏览器测试另运行 `npx playwright install chromium firefox webkit`。真实声音/完整工程验证前按README准备本机私有资源；CI视口测试不能替代这些资源与真机验收。

功能变更先写SPEC验收编号；架构变更补ADR；内容与教学规则集中在 `content/`，修改语义需升级内容版本并保留历史。标准音直接信任cmguo/PinYinSound，不设教师审批或审音工作流。首版无录音与发音评分，旧研究不得作为产品依赖重新引入。

业务变更覆盖真实边界并运行适用测试；工程门禁为 `npm run verify:all`，内容/声音发布另跑 `npm run validate:release`。纯文档改动检查格式、本地链接及与实现的一致性，不用重复GUI测试代替文档核查。每个提交对应一个清晰切片；可连续完成多个切片，不自动推送或公开发行。详见[开发流程](docs/engineering/workflow.md)。
