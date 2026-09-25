# SPEC 驱动开发流程

## 从需求到交付

1. 读 PRD 需求编号 → 找对应 SPEC 的依赖与验收。
2. 在 `feat/spec-xxx-short-name` 分支选一个小切片，写出本次完成的验收编号。允许常规实现选择自主推进；改变已确认需求时先更新SPEC。
3. 定义/更新数据契约和失败行为，然后实现最小纵向功能。内容、界面、算法、平台API各自分层。
4. 对真实业务边界写测试：幂等、重复提交、回退、断网、音频取消、错误声调、权限拒绝、数据迁移。
5. 运行 `npm run verify:all`，根据变更运行 `audio:doctor` 和对应PoC。功能发布前还须 `validate:release` 与人工验收。
6. 更新SPEC状态、ADR、依赖/许可证、测试证据。提交应可独立理解、可回退。

## 完成定义

每个SPEC都有“已实现”和“已验证”两列，不能只勾页面出现。评分必须有真实样本及人类标注；教材内容需教师审查；设备兼容需真实设备证据。Mock与Playwright模拟不替代这些门禁。

人工资产依赖阻塞时，先完成不依赖它的接口、错误态和测试；把阻塞写入状态表，不能靠假音频/伪分数宣布功能完成。

## Git

- 主分支 `main`；本地已初始化，提交按 Conventional Commits，例如 `feat(SPEC-002): add lesson map`、`fix(SPEC-003): cancel local assessment on exit`。
- PR模板见 `.github/pull_request_template.md`。小PR宜覆盖一个SPEC切片；大任务先合并接口再实现适配器。
- 不提交node_modules、venv、构建物、私钥、数据库、原始声音、儿童测试集或商业SDK。
- 开源前检查历史中是否有秘密/个人信息、许可证、README链接与发布门禁。远程地址由项目维护者决定，本阶段不推送。
- 当前机器没有Git作者身份时，初始化提交使用项目署名 `Love Pinyin contributors <contributors@love-pinyin.local>`；不是用户真实身份。维护者可在后续提交配置自己的身份。

## 低成本模型任务模板

```text
阅读 AGENTS.md、README、docs/STATUS.md 和 SPEC-XXX。
仅实现验收 AC-... 到 AC-...；先检查依赖和真实资产状态。
遵守 docs/api-contract.md 与 content JSON Schema。
不得新增外部音频服务；不得用 ASR 或随机值冒充发音评分。
先说明本切片将改的文件，再实施并运行 npm run verify:all。
交付变更、验收证据、失败或未覆盖项；更新SPEC状态，不实现下一个切片。
```

每次附本切片相关文件即可，不需要把整个研究库塞给模型。目录、契约、验收先行能降低实现成本，但声学研究/教师判断仍需相应能力与人类证据。
