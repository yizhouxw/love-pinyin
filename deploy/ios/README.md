# iPhone / iPad 工程验证

本工程对应 [SPEC-023](../../docs/specs/SPEC-023-ios-app.md) 的 IOS-01 和 IOS-02 听读切片。启动页标记为「离线听读验证版」，可打开课堂听写、天天练拼音和词语天天练。课堂作答、本地进度、家长备份及游戏将在后续接入。

## 准备和构建

在仓库根目录，按项目锁文件完成 npm 与 uv 安装，显式准备 PinYinSound：

```sh
npm ci
uv sync --locked
uv run --locked python -m scripts.sync_standard_audio
deploy/ios/prepare.sh
open deploy/ios/LovePinyin.xcodeproj
```

资源准备先构建共享 Vite 前端并运行内容发布检查。每条音频按源文件摘要验证并按实际文件去重。输出位于忽略目录 `build/ios/Resources`。Xcode 构建时将它复制到应用包。重新准备后再构建可以同步最新课程和音频。

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
4. 如果首次打开提示开发者不受信任，先保持设备联网，在「设置 → 通用 → VPN 与设备管理」选择当前「开发者 App」的签名账号，按系统提示完成信任，再尝试打开验证版。
5. 首次打开成功后，断开 USB、关闭 Wi-Fi 和蜂窝。分别在 iPhone 和 iPad 上冷启动，确认显示 14 课，分别打开课堂听写、天天练拼音和词语天天练。检查拼音字形、笔顺、标准音、词语连播和逐字高亮，试播课程录音并拖动播放进度。切换横竖屏和 iPad 窗口大小，离开前台时验证停止播放。单独记录两台设备结果。

参考 [Apple 真机运行说明](https://developer.apple.com/documentation/xcode/running-your-app-on-simulated-or-physical-devices)和 [Personal Team 限制](https://developer.apple.com/help/account/basics/about-your-developer-account/)。
