# 贡献指南

先读 [AGENTS.md](AGENTS.md) 和 [开发流程](docs/engineering/workflow.md)。本项目采用MIT，提交前确认你有权贡献代码、题目、音频或模型；第三方资产附独立许可与来源，不能把教材下载文件当作MIT素材。

运行 `npm ci`、`uv sync --locked`、`npx playwright install chromium firefox webkit`，然后 `npm run verify:all`。

新功能必须关联SPEC和验收编号；教学内容修改需要教师复核；评分算法必须附验证数据说明与版本，不能仅凭听感合入。严禁提交儿童个人信息和未授权声音。
