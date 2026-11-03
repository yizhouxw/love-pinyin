# ADR-0038：Windows 本地应用

2026-11-03，依据 SPEC-021。Windows x64 使用系统 Microsoft Edge 应用窗口承载现有同源页面，由桌面启动器管理回环 Python 服务与应用窗口。应用包内含 Windows Python 3.12.12、锁定 Python 依赖、前端和固定课程声音；Whisper 在家长设置中显式下载并校验，数据和浏览器配置存用户本地应用数据目录。系统需预装 Edge；无 Edge 时明确提示，不自动安装或下载。

Windows 安装包与 macOS 包由独立构建任务生成，统一发布任务等待两者并上传；运行时无需 Node、Git、Docker 或 Python。保留单独许可及现有备份迁移方式。Windows CI 验证不能替代真实家庭设备试用。

构建工具固定 Inno Setup 6.7.1，来源为 [Inno Setup 官方项目](https://jrsoftware.org/isinfo.php)，使用其 [Inno Setup License](https://jrsoftware.org/files/is/license.txt)；构建使用 GitHub Windows runner 已安装版本并检查版本，不随应用打包。启动器用 Windows 自带 .NET Framework 编译，浏览器为用户已安装的 Microsoft Edge，不新增 npm/uv 运行依赖。CPython 3.12.12 及所有 Python 包使用现有 uv 锁文件；实际 Windows 构建结果以 CI 为准。

Windows 缺少系统 IANA 时区数据库，新增仅 Windows 安装的 [tzdata 2026.2](https://pypi.org/project/tzdata/2026.2/)，Apache-2.0，固定于 `uv.lock` 并随 Python 依赖打包。首次 Windows 冒烟发现缺失时区数据，已加依赖；实装结果以后续 Windows 构建为准。
