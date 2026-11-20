# Android 本地识别验收

2026-11-20；SPEC-024 ANDROID-ASR-01～04，ADR-0044。工作区 `love-pinyin-android`，分支 `codex/android-local-asr`。OnePlus PJZ110，ADB 已授权，使用随机 verificationId 隔离学习档案；模型安装在此 App 的独立 noBackupFilesDir，不属于学习备份。

## 已实测

- 固定 sherpa-onnx 2.0.1 AAR 的 SHA-256 与官方发布一致；Kotlin、APK、lint 通过。lint 0错误、6警告，包括已有版本/资源/JavaScript提示和空间预检建议；未用忽略错误绕过构建。
- Hugging Face 在手机网络下载失败，界面保留重试。改用原导出者魔搭固定修订；六文件与固定 HF 清单的大小、SHA-256 全部一致。真机真实下载987015347字节并校验安装。下载约674MB时取消，重试继续已写完整分段，最终安装成功。未随 APK 分发权重。
- 原生 instrumentation 通过 `ANDROID_CONTRACT_OK`；新增有界 PCM、无模型、过期代次、损坏模型拒绝使用测试，使用测试目录。许可合成成人示范 `asr-tea.wav` 在真实手机返回 `爸爸喝茶。` 和 `bà bà hē chá.`，冷模型加载/推理共5533ms，输出 `ANDROID_ASR_MODEL_OK`。这不是儿童发音质量证据。
- 飞行模式开启并关闭 Wi-Fi，force-stop 后冷启动479ms，实际离线转写仍返回同一结果；随后恢复原飞行模式关闭、Wi-Fi开启。离线测试通过USB连接调试WebView，推理本身仅加载设备文件。
- 真实家长页显示 Qwen3-ASR 0.6B、约0.99GB、模型已安装、移除按钮；未通过修改页面状态伪造模型就绪。
- 用户在系统弹窗允许麦克风，ADB确认 granted=true。AudioRecord实际启动、音量读取、停止返回有界 WAV；验证只读取内存长度，不保存或输出录音内容。重新采音后按HOME退后台，再回应用，旧录音快照为null。
- 天天练真实页面展开录音比较，点击录音、停止，出现回放并可清除；页面接入原生采音通过。
- `npm run verify:all`：224项前端、564项服务端、36项本机浏览器、88项真实服务浏览器回归通过；新增慢推理超时回归后单元测试225项通过。`npm run validate:release`通过14课、785每日条目、38词语课；最终格式、lint通过。WebKit/Chromium桌面回归不当作Android真机证据。

## 边界

尚未证明实际儿童语音准确率、声调质量、低内存/旧Android的推理性能或家庭长期使用效果。识别不评价实际四声，不返回专业发音分数；模型或麦克风不可用时继续人工确认。仅Android10以上arm64、至少4GB总内存提供模型支持；首次加载可用内存不足时返回不可用。取消使运行中结果失效，底层单次CPU解码结束后才释放推理资源，不声称可强制中止底层内核。
