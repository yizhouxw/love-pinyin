# ADR-0037：Mac 应用容器与可选模型

2026-11-03，依据 SPEC-020。以 macOS 原生 WebKit 窗口承载已有同源应用，由应用管理仅监听回环的随包 Python 后端。静态前端、课程和固定标准音随包；可写家庭数据与可选模型位于用户应用支持目录。模型仅由本机家长主动触发下载，复用固定 URL、大小与 SHA-256 校验并原子安装。应用关闭时停止其启动的服务。保留现有 B/S 和 Docker 部署路径及其数据，应用不自动迁移旧数据；用户可用现有备份恢复。

发行包在创建版本标签后由 Actions 发布到现有仓库；用户于 2026-11-03 明确授权公开发布安装包。签名、公证及素材各自许可仍需如实说明。安装包不能冒充真实家庭及移动设备验收。

运行时使用 uv 0.12.5 管理的 [python-build-standalone](https://github.com/astral-sh/python-build-standalone) CPython 3.12.12；CPython 采用 Python Software Foundation License，发行运行时自带其许可文件。此为已锁定 Python 版本的打包方式，构建期用锁文件安装既有依赖；不新增应用 npm 或 Python 包。
