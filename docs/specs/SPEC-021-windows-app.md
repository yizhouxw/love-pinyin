# SPEC-021：Windows 本地应用

2026-11-03 用户要求增加 Windows 应用，沿用 SPEC-020 的本地运行和可选 Whisper。

- WIN-01：Windows x64 安装后启动本地应用窗口及仅回环后端，退出窗口停止其服务；缺少必要运行环境或端口占用明确提示。
- WIN-02：固定课程和标准音、Python 与后端随包，家庭数据与可选模型保存在用户目录；首次或更新不自动下载模型，家长在设置显式下载并校验；进度支持备份迁移。
- WIN-03：GitHub Actions 在 Windows 构建并验证安装包，标签发布，保留 macOS 包；不含家庭数据、儿童录音或密钥。标明签名状态。
- WIN-04：README 说明安装、依赖、数据与验证范围；不能将 Windows CI 或虚拟机视为家庭真实设备验收。

本机工程验证：`npm run verify:all` 通过（180 项前端、549 项服务端、36 项视口及 54 项真实服务浏览器测试），`npm run validate:release` 通过；本机为 macOS，上述结果不证明 Windows 安装与界面运行。Windows 构建及服务冒烟以 GitHub Actions 结果为准。
