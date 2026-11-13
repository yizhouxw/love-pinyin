# Android agent harness

先遵守 [项目 Agent harness](agent-harness.md)：独立 worktree/分支开发，同一 Android 真机安装和验收串行。

## 范围与执行方式

用户于 2026-11-13 授权继续实现 Android 设备版本。先读 README、实施计划、[Android SPEC](../specs/SPEC-024-android-app.md)、ADR-0039 及相关最新 ADR；复用 React、content 与声音资产，先完成独立离线安装、真实声音、作答持久化和重启恢复，再覆盖完整功能。测试工程通过不等于 Android 产品已交付。不要把 iOS 的识别能力自动视为 Android 已支持。

agent 可直接创建工程、配置构建、执行 Gradle、安装 APK、运行 ADB 和检查日志，不必反复让用户代操作 Android Studio。手机解锁、USB 调试信任、系统安装确认仍由用户在设备上完成；不得绕过系统授权。后续先检查设备连接状态，再决定是否需要用户协助。

## 已验证工具链（2026-11-13 实测）

| 项目                  | 实测值                                                                                       |
| --------------------- | -------------------------------------------------------------------------------------------- |
| Mac                   | Apple Silicon / arm64                                                                        |
| SDK                   | `/Users/chad/Library/Android/sdk`                                                            |
| JDK                   | Temurin 17.0.19，`/Users/chad/Library/Java/JavaVirtualMachines/temurin-17.jdk/Contents/Home` |
| Android Gradle Plugin | 固定 9.1.1，使用内置 Kotlin 支持                                                             |
| Gradle                | 固定 9.3.1，使用 Wrapper，官方 SHA-256 校验                                                  |
| 编译 SDK              | 已安装的 Android 16 / API 36.1                                                               |
| Build Tools           | 36.0.0                                                                                       |
| Platform Tools        | 37.0.1                                                                                       |
| 真机                  | OnePlus PJZ110，arm64-v8a，系统报告 Android 16 / API 36                                      |
| WebView               | com.google.android.webview 156.0.8078.47                                                     |

用户最初提供版本为 15.0，以 ADB 实测 Android 16 / API 36 为准。以上路径和版本是本机记录，后续应重新查询，不能当成其他机器的固定配置。不要使用 Android Studio 自带 JBR 25 的存在来推定正式工程兼容性；本次编译实际使用 JDK 17。`cmdline-tools/latest` 是 SDK 管理器安装目录名，不是允许使用动态依赖版本。

## 关键环境冲突与复现

本机 `~/.gradle/init.gradle` 会注入 Aliyun 镜像仓库，与工程的 `FAIL_ON_PROJECT_REPOS` 冲突。保留用户全局配置，使用项目专属、Git 忽略的 `GRADLE_USER_HOME`。构建、Wrapper 及 `--stop` 都必须使用相同的 JDK 与 Gradle 用户目录，避免误用全局配置、重复下载或连接错误的 daemon。不移动仍在运行的 Gradle 分发目录；必要时先停止对应 daemon。

示例（正式工程按自身脚本位置设置路径，不复制本机绝对路径进可移植配置）：

```sh
export JAVA_HOME=/Users/chad/Library/Java/JavaVirtualMachines/temurin-17.jdk/Contents/Home
export ANDROID_HOME=/Users/chad/Library/Android/sdk
export GRADLE_USER_HOME="$PWD/.gradle-home"
./gradlew --console=plain assembleDebug lintDebug
./gradlew --offline --console=plain assembleDebug lintDebug
```

正式工程需固定插件/Wrapper 版本和分发校验和，记录依赖官方来源、许可证与实装结果。`local.properties`、SDK 路径、调试密钥、Gradle 缓存和构建产物不进 Git。不依赖全局 Gradle 安装，不改全局 `JAVA_HOME`。Android 设备版本与 compileSdk、targetSdk 是不同概念；连接 API 36 真机不强制只能使用相同编译 SDK。

## 真机安装与证据

```sh
"$ANDROID_HOME/platform-tools/adb" devices -l
"$ANDROID_HOME/platform-tools/adb" shell getprop ro.build.version.release
"$ANDROID_HOME/platform-tools/adb" shell getprop ro.build.version.sdk
"$ANDROID_HOME/platform-tools/adb" shell dumpsys webviewupdate
"$ANDROID_HOME/platform-tools/adb" install --no-streaming -r path/to/app-debug.apk
"$ANDROID_HOME/platform-tools/adb" shell am start -W -n package.name/.MainActivity
```

多设备时显式选择目标设备。`unauthorized` 表示需要手机确认调试信任，不是 SDK 缺失。ADB 安装长时间无响应时，检查设备上的系统安装器及确认弹窗；本次普通安装等待后，改用 `--no-streaming` 推送，并在用户允许后成功。不要反复并发安装或自动点击设备安全确认。日志按应用 PID 或专属 tag 过滤，避免采集无关私人数据。

## 已有验证证据及边界

独立测试工程位于本机 `/Users/chad/dev/android-environment-check`，不属于产品仓库；可读其 `check-build.sh`、`VALIDATION.md`、构建及 lint 报告。工程使用独立包名 `org.lovepinyin.envcheck`，没有儿童数据、产品课程或网络权限。

- Kotlin APK 首次 `assembleDebug lintDebug` 成功，1 分 25 秒。
- 固定 Wrapper 的缓存离线复构建成功，约 7 秒。
- lint 为 0 错误、7 警告：版本更新建议、备份属性弃用、测试文案本地化；另有 SDK 元数据与 Gradle 弃用提示。构建成功不等于没有警告。
- APK 844006 字节，用户允许系统安装后 ADB 返回 Success。
- 真机冷启动返回 Status ok / COLD，TotalTime 234 ms；前台 Activity 和进程均确认，应用日志 `ENVIRONMENT_CHECK_OK api=36`。

这些只证明 Kotlin、SDK、Gradle、签名打包、ADB 安装及原生活动启动。未证明 React/WebView、标准音、课程定位、逐字高亮、SQLite 学习闭环、游戏触控、文件备份、飞行模式冷启动或家庭试用通过，正式开发必须逐项补验。

## 来源与许可

- [AGP 9.1.1 官方兼容表](https://developer.android.com/build/releases/agp-9-1-0-release-notes)：Gradle 9.3.1、Build Tools 36.0.0、JDK 17。AGP 为 Apache-2.0。
- [Gradle 固定分发](https://services.gradle.org/distributions/gradle-9.3.1-bin.zip)及同地址 `.sha256` 校验；Gradle 为 Apache-2.0。
- [Eclipse Temurin](https://adoptium.net/temurin/)：JDK 为 GPLv2 with Classpath Exception。
- Android SDK 适用独立 Android SDK 许可；用户已通过安装流程配置所需组件。
- [Android 本地 WebView 资源说明](https://developer.android.com/develop/ui/views/layout/webapps/load-local-content)：正式离线容器可评估 WebViewAssetLoader，不把普通远程网页包装当作独立离线实现。

## 正式 Android 工程首轮结果（2026-11-13）

工作区 `love-pinyin-android`，分支 `codex/android-offline`。`deploy/android/prepare.sh` 复用离线打包校验；`build.sh --offline :app:assembleDebugAndroidTest` 完成 APK 与隔离回归包构建，lint 0 错误、5 警告。依赖固定且沿用上表来源/许可，无新增 Android 运行时第三方库。

OnePlus 上普通安装成功、冷启动 Status ok（563ms）；实际截图确认 React 首页、当前课和各练习入口加载。原生 instrumentation 返回 `ANDROID_CONTRACT_OK`，覆盖首次作答投影、同键回执、重新打开数据库恢复、无效备份拒绝及恢复、四款游戏路线冻结、暂停授权。测试使用随机目录隔离数据库，不读写家庭档案。前端 206 项单元测试与类型检查通过，发布内容校验覆盖14课、785每日条目、38词语课。

以上不证明实际听感、飞行模式冷启动、触摸完整流程、系统文件导入导出、真实进程被杀恢复或家庭试用通过。主线仍有其他任务未提交改动，尚未合并或替换本机 Mac/Web 服务。构建缓存不能在 Gradle 进程运行时复制，首次隔离缓存应联网按固定版本补齐；避免造成 metadata 损坏。
