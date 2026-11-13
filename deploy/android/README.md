# Android 独立离线版

Android 8.0（API 26）以上。固定工具链与授权流程见 [Android harness](../../docs/engineering/android-agent-harness.md)，实测范围见 [验收记录](../../docs/engineering/android-product-acceptance.md)。

```sh
./deploy/android/prepare.sh
./deploy/android/build.sh --offline
ANDROID_SERIAL=设备序列号 ./deploy/android/test-contracts.sh
```

产物：`deploy/android/app/build/outputs/apk/debug/app-debug.apk`。这是本机签名的侧载构建，不是应用商店发布包。首次构建需按固定 Wrapper/插件版本联网补齐缓存，后续可离线构建。不要删除调试签名密钥，否则后续不能直接覆盖安装；密钥不进仓库。

安装后课程、声音、练习、游戏与 SQLite 记录均在设备本机，无需连接 Mac 或网络。无 INTERNET、麦克风权限，无遥测。语音识别不可用时使用听读和人工确认，不生成识别分数。

家长管理可以通过系统文件选择器导出和恢复 Android v1 备份。恢复前预览并确认，要求内容版本一致；不支持与 Web/iOS 备份互导。**卸载 Android 应用会删除其私有学习记录，卸载前请导出备份；覆盖更新保留记录。**

真机自动验收使用 debug 专属 `verificationId` UUID 隔离 SQLite 与 WebView 数据，绝不清空家庭档案：

```sh
adb -s "$ANDROID_SERIAL" shell am force-stop org.lovepinyin.android
adb -s "$ANDROID_SERIAL" shell am start -n org.lovepinyin.android/.MainActivity --es verificationId 随机UUID
ANDROID_SERIAL=设备序列号 node deploy/android/verify-device.mjs games
```

`verify-device.mjs` 通过调试 WebView 操作实际手机，截图来自 ADB；不是桌面手机尺寸模拟。设备操作必须串行。`reading`、`games`、`audio` 分别验证声音与阅读、四种完整游戏、长录音定位与后台中断；系统文件选择器需继续在真实设备上完成。
