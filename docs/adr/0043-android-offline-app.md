# ADR-0043：Android 离线容器与本机服务

2026-11-13，状态：实施中。验收见 SPEC-024。

使用 Kotlin、系统 WebView 和 SQLite，复用 React/content/声音；不移植 Python 服务，不复制前端页面。固定工具链沿用 Android harness。先实现无网络权限的固定 HTTPS 本地资源入口，拒绝远程导航、文件协议和路径穿越；没有桥接时不伪造学习 API。后续桥接采用版本化操作白名单、请求标识和主页面来源验证，写入事务提交后回执，SQLite 保存可恢复档案；以共享业务契约验证幂等、首答和游戏额度。

当前容器只是 ANDROID-01 的实现起点，尚不构成完整产品。正式包必须校验完整资产清单、声音及缺失错误；资源 MIME、长音频定位、生命周期声音停止与安全边界需测试后验收。Android 本地识别暂不可用，人工确认不能作为识别成绩。

不新增 Android 运行时第三方依赖。AGP 9.1.1、Gradle 9.3.1、JDK17 与 SDK 来源和许可沿用 Android harness；实装结果随切片记录。

桥接复用前端原生能力入口并显式识别 Android，不伪装 iOS。Kotlin 使用系统 org.json 和 SQLite，无第三方运行时库；业务数据由构建时既有 classroom_contract 生成。完整快照事务存储作为首版单窗口实现，写入失败保持原内存状态。原生文件选择与确认通过异步请求 ID 回传。备份使用 love-pinyin-android v1，严格限定当前内容版本；跨平台互导另行实现。
