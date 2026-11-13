# Android 离线应用

独立工作区按项目 agent harness 开发。固定 AGP 9.1.1、Gradle 9.3.1、JDK17、SDK36.1，最低 Android 8/API26；不包含网络或麦克风权限，无第三方 Android 运行时依赖。来源与许可见 Android harness；随包声音和字体保留原许可。

```sh
uv sync --locked
npm ci
./deploy/android/prepare.sh
./deploy/android/build.sh
```

资源准备复用既有离线资源校验，打包新版素材、14课、词语和每日练习、游戏及声音，不携带家庭数据库。当前构建仍需既有本机已准备声音源；资源目录和调试签名不进 Git。APK 在 `app/build/outputs/apk/debug/app-debug.apk`；构建产物不是正式发行包。

本机 SQLite 位于 App 私有数据库目录；卸载会清除，请先在家长管理导出 Android 学习备份。备份仅支持同内容版本的 Android v1 格式，暂不支持 Web/iOS 互导。识别暂不可用，听示范后人工确认。

无依赖的原生回归 runner 使用隔离数据库：

```sh
./deploy/android/build.sh :app:assembleDebugAndroidTest
adb install --no-streaming -r deploy/android/app/build/outputs/apk/debug/app-debug.apk
adb install --no-streaming -r deploy/android/app/build/outputs/apk/androidTest/debug/app-debug-androidTest.apk
adb shell am instrument -w org.lovepinyin.android.test/org.lovepinyin.android.ContractInstrumentation
```

安装系统确认由用户完成。自动回归不代替真实声音、触摸、文件选择、中断及家庭试用验收。
