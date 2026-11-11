# 爱拼音 iPhone / iPad

本工程对应 [SPEC-023](../../docs/specs/SPEC-023-ios-app.md)。可离线使用课堂练习、天天练拼音、词语天天练和四款拼音游戏。答题、进度和游戏时长存放在当前设备。到期复习和跨端备份分别由 GitHub Issue [#36](https://github.com/yizhouxw/love-pinyin/issues/36) 和 [#37](https://github.com/yizhouxw/love-pinyin/issues/37) 跟踪。

在 iOS 或 iPadOS 17 及以上，可在「家长管理 → 本地语音识别模型」主动下载 Qwen3-ASR 0.6B MLX 8-bit 权重，约 1.01 GB。下载及校验完成后，天天练拼音和小卖部在设备内录音和识别，独立于家庭 Mac。安装包只带下载清单，缺少模型时可人工确认。

## 准备和构建

家庭调试版安装两套练习。首次使用默认新版资料，可从「家长管理 → 高级设置 → 学习素材」切换到行知小学和原词语练习。家庭版先显式准备旧练习用的 PinYinSound：

```sh
npm ci
uv sync --locked
uv run --locked python -m scripts.sync_standard_audio
deploy/ios/prepare.sh
open deploy/ios/LovePinyin.xcodeproj
```

家庭资源位于 `build/ios/Resources`，供 Xcode Debug 使用。公开版随附新版练习（含两版共用的课序和词表）、公开授权标准音和原创课程音频，构建不需要下载旧音库。准备公开资源后才能生成 Release Archive：

```sh
deploy/ios/prepare.sh --public
```

编译 MLX 的 Metal 着色器需要 Xcode 对应的 Metal Toolchain。若未安装，在 Xcode 的 Components 设置中安装，或运行 `xcodebuild -downloadComponent MetalToolchain`。

公开资源位于 `build/ios/PublicResources`。两种构建分别校验实际引用及音频摘要。课程与练习生成命令见下方。正式分发按 [SPEC-024](../../docs/specs/SPEC-024-ios-content-distribution.md) 和上架 Issue 验收。

修改稿件后，用已显式下载的固定本地模型生成音频：

```sh
uv run --locked --group voice-build python -m scripts.build_ios_lesson_audio
uv run --locked --group voice-build python -m scripts.build_ios_practice_audio
```

已提交的标准音可以用固定来源重建。运行 `uv run --locked python -m scripts.prepare_ios_standard --chen-repo /path/to/audio-cmn`，指定清单固定的 audio-cmn 修订。构建程序核对录音标签与许可，登记原始摘要、裁切参数和输出摘要。

可选 `deploy/ios/prepare.sh --trial-aac` 将中文引导和词语的 WAV 试编码为 64 kbps AAC，重新解码检查采样率和帧数，原文件与派生摘要均登记。输出独立存放在 `build/ios/TrialAAC`，供后续听感、逐字时间轴和体积验证。

仅验证编译时可构建未签名 arm64 测试包：

```sh
xcodebuild -project deploy/ios/LovePinyin.xcodeproj -scheme LovePinyin \
  -destination 'generic/platform=iOS' -derivedDataPath build/ios/Xcode \
  CODE_SIGNING_ALLOWED=NO build
```

## 真机

1. 在 Xcode 的 Settings → Apple Accounts 登录普通 Apple 账号。可使用免费 Personal Team。
2. 为 LovePinyin target 选择该 Team 并使用自动签名。若需要保持工程文件原样，将团队 ID 写入本机忽略文件 `deploy/ios/Signing.local`，格式为 `DEVELOPMENT_TEAM = 团队ID`。
3. 解锁已连接的 iPhone 或 iPad，按系统提示信任 Mac 并启用开发者模式。选该设备为运行目标，点击 Run。免费签名七天到期，届时用 Xcode 重新签名安装。
4. 如果首次打开提示开发者不受信任，先保持设备联网，在「设置 → 通用 → VPN 与设备管理」选择当前「开发者 App」的签名账号，按系统提示完成信任，再尝试打开爱拼音。
5. 首次打开成功后，断开 USB、关闭 Wi-Fi 和蜂窝。分别在 iPhone 和 iPad 上冷启动，确认显示 14 课，分别打开课堂听写、天天练拼音和词语天天练。检查拼音字形、笔顺、标准音、词语连播和逐字高亮，试播课程录音并拖动播放进度。完成一道有声客观题后关闭 App，再打开确认能继续同一轮练习。切换横竖屏和 iPad 窗口大小，离开前台时验证停止播放。单独记录两台设备结果。

参考 [Apple 真机运行说明](https://developer.apple.com/documentation/xcode/running-your-app-on-simulated-or-physical-devices)和 [Personal Team 限制](https://developer.apple.com/help/account/basics/about-your-developer-account/)。

运行 `deploy/ios/test-classroom.sh` 可在 Mac 上用随包课程验证 Swift/SQLite 存储、作答恢复和与 Python 的规则对照。脚本从登记的课程与声音 ID 生成契约数据，无需准备声音文件。

运行 `deploy/ios/test-games.sh` 检查四款游戏的选题、关卡和计分，以及暂停、额度用完和重开恢复。Xcode 的 `testOfflineGameScenes` 使用临时档案测试游戏入口、触控和暂停恢复。

## 真机自动化

准备资源后，解锁设备并在 Xcode 的 LovePinyin scheme 执行 Product → Test。若手机显示「为 XCTest 输入 iPhone 密码」，请在手机上完成系统确认后继续。也可以通过终端运行，同一份测试依次用于 iPhone 与 iPad。

```sh
xcodebuild -project deploy/ios/LovePinyin.xcodeproj -scheme LovePinyin \
  -destination "id=$LP_IOS_DEVICE_ID" -parallel-testing-enabled NO \
  -allowProvisioningUpdates -resultBundlePath build/ios/classroom-ui.xcresult test
```

使用目标设备的 ID 设置 `LP_IOS_DEVICE_ID`。每次运行指定一个新的结果路径。Debug 测试使用独立 SQLite 与临时 WebKit 存储。测试检查可触达的主要按钮、听题后可作答、旋转保留当前题、重开恢复第二题和只保存一条作答。Xcode 测试报告保留首页、横屏和恢复后的截图。

在「家长管理 → 此设备学习记录」可通过系统「文件」导出和恢复当前课程版本的 iOS 学习档案。导入会显示来源、日期、版本和记录数，确认后替换；可在 iPhone 与 iPad 之间手动迁移。家长应将备份保存到 App 沙盒之外。Web/macOS 的家庭备份是独立格式。
