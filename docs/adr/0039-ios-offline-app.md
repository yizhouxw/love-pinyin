# ADR-0039：iOS 通用应用与本地学习服务

2026-11-07，状态：提议。产品边界和验收见 [SPEC-023](../specs/SPEC-023-ios-app.md)。

## 决策

在 `deploy/ios/` 建立 Swift Xcode 工程，通用 target 同时支持 iPhone 和 iPad。复用 Vite/React 页面、内容目录、音频登记及现有交互代码。通过系统 WKWebView 加载应用包内的前端，通过 Swift 和系统 SQLite 持久化本机家庭数据。B/S 和 macOS App 继续使用现有 FastAPI、SQLite 和同源 HTTP 路径。首版各端的数据以版本化备份为交换边界。

直接加载家庭 Web 服务会把安装后的首次使用、学习和播放绑定到 Mac 与家庭网络。全面重写 SwiftUI 会复制课堂、词语练习、游戏与无障碍交互。随包移植桌面的 Python/FastAPI 服务则需要新的 iOS 运行时、原生依赖和服务生命周期。选择复用界面并实现窄范围的本机学习服务，主要成本在服务端业务规则的双端一致性，以下面的契约验证控制该成本。

## 页面、业务和文件边界

| 层         | B/S 与 macOS                    | iOS                                                                |
| ---------- | ------------------------------- | ------------------------------------------------------------------ |
| 静态页面   | 同源 HTTP                       | WKURLSchemeHandler 读取应用包登记的 HTML、JS、CSS、图片与字体      |
| 学习 API   | 现有 fetch、会话 Cookie 与 CSRF | TypeScript 平台适配器经 WKScriptMessageHandlerWithReply 调用 Swift |
| 学习数据   | FastAPI 现有 SQLite             | Swift 本地服务，独立 SQLite 与数据库迁移                           |
| 资源与文件 | HTTP 音频与既有文件操作         | 包内短音频、原生长音频、系统文件导入和导出                         |

入口明确注入 iOS 平台能力，生产构建用注入与桥接状态识别 iOS，禁止用 UA 或 URL 参数开启本机家长路径。统一 API 客户端错误及取消语义，收拢每日跟读、词语等直连 JSON fetch。B/S 的访客及权限分支留在 HTTP 适配器。iOS bootstrap 直接建立本机家庭档案，家长操作限当前沙盒；配对、设备管理、模型、识别和麦克风入口按能力过滤。没有局域网监听器，运行所需资源均为随包文件。

桥接消息采用版本化的操作、请求 ID 和有限 JSON 参数，回复带结构化数据或现有业务错误码；校验来源主 frame、固定包内 URL、操作白名单、字段和大小。限制导航与子资源来源，拒绝路径穿越、远程 URL 和桥接访问任意文件。查询可取消，已提交写入仍可按同一作答 ID 查询回执；WebKit 重载不会被当成业务重置。SQLite 写入在串行事务中完成，失败回滚。存储满、损坏、未知迁移或桥接异常应显示本机错误与恢复入口，禁止默默清库。

SQLite 放在应用沙盒的 Application Support，界面临时状态与可恢复学习状态分开。冻结题单、选项与内容版本；同题首答、幂等回执、revision、Asia/Shanghai 业务日、历史内容、时钟回拨与游戏短租期沿用现有契约。退后台以原生生命周期暂停声音和本机游戏租期，回前台恢复会话并重新授权。时长结算以持久化的最近有效授权为上界，进程被杀后仍可恢复。家长文件操作使用系统文件选择与分享接口，先校验并预览既有 schema 5 备份及其支持的 v2～v4 迁移，再按文件摘要与 revision 在事务内确认替换。应用数据目录启用系统文件保护，排除系统自动备份；备份由家长显式导出到其选择的位置，临时文件及时清理。

Swift 实现当前 Python API 的 iOS 子集，题目、标准答案、声音 ID 和游戏配置仍以同一 `content/` 为源。按现有 [API 契约](../api-contract.md) 对公开投影、选题、首次作答、掌握度、复习、游戏额度和备份建立共享输入/输出样例。样例由固定内容、时钟、初始档案和已知期望组成，Python 与 Swift 都执行；验证连续操作及失败时数据库结果，标准化随机 ID 与动态时间。新业务规则变更需同步更新两端契约与样例，不能以 React 中第二套判断代替。iOS 数据库内部 schema 可独立演进，测试用的备份格式是跨端交换契约。

## 音频和构建

1. 构建期复用现有内容和声音校验，显式准备固定 PinYinSound 资源。按清单打包当前内容及可恢复历史所需资产，保留来源、原始摘要、派生摘要、时长与许可。拒绝缺失资源和测试夹具混入，随包资源清单避免带入完整 `private/` 或桌面运行时。
2. 标准音与课程录音保留原有格式；引导和词语 WAV 试用 64～96 kbps AAC，使用 macOS 随附编码工具，记录工具版本与参数。逐字高亮使用原始时间基准，校验编码前后解码时间轴，必要时校正或为受影响片段保留 WAV。以实际解码、时长和人声清晰度检查决定是否采用。当前课程 MP3 约 97 MB，标准音约 9 MB，81 分钟的 WAV 按目标码率约为 39～59 MB，另计容器和文件开销。中文录音与标准音继续独立登记。
3. 短音频优先复用现有单播放器、缓冲池、拼接和时间轴，通过包内 scheme 按登记 ID 读取。长课程录音用 AVPlayer 读取本机文件并将进度、暂停、定位和播放结束回传给现有界面，避免长文件进入 JS Blob 池。两类声音由同一播放协调器互斥，切课、离开、来电或拔耳机停止，过期回调按播放 ID 丢弃。
4. 在首个可运行切片先验证真机上的 WebKit 模块、字体、短音频 fetch/解码及 AVPlayer seek。若 WebKit 的自定义 scheme 无法稳定读取短音频，通过桥接按登记 ID 提供有长度上限的短音频字节给现有解码层，并复用缓冲边界。此项通过后再扩展业务覆盖。
5. 用 Xcode 默认平台框架 WebKit、AVFoundation、UIKit 和 SQLite，现阶段不引入 npm、SwiftPM 或 Python 新依赖。工程固定产品 bundle ID，签名 team 用本地设置注入。Personal Team 通过 Xcode 真机安装，签名期满后重装测试构建。记录压缩与解包大小；可导出时用 Xcode App Thinning Size Report 区分 iPhone/iPad 的下载和安装体积，开发包或资源目录统计须注明测量口径。

Apple 参考：[WKWebView](https://developer.apple.com/documentation/webkit/wkwebview)、[WKURLSchemeHandler](https://developer.apple.com/documentation/webkit/wkurlschemehandler)、[带回复的脚本消息](https://developer.apple.com/documentation/webkit/wkscriptmessagehandlerwithreply)、[Personal Team](https://developer.apple.com/help/account/basics/about-your-developer-account/)、[App 体积报告](https://developer.apple.com/documentation/xcode/reducing-your-app-s-size)。

## 实施顺序

1. IOS-01 首次真机切片：创建通用工程，打包启动、能力注入、桥接和短/长声音探针。Xcode 检查本机签名，iPhone 13 安装并确认飞行模式启动和声音。探针只作工程验证。
2. IOS-02、IOS-03 学习闭环：接入全量课程与声音、本地事务、课堂与复习、家长和双向备份。用失败注入验证已保存回执和原档案恢复。
3. IOS-04 游戏及中断：完成额度、关卡恢复、前后台与时钟回拨，验证窄窗和不同输入方式。
4. IOS-05、IOS-06 交付：执行 `npm run verify:all`、`npm run validate:release` 与 iOS 原生测试，回归既有 B/S 与桌面包。按 iPhone 真机、iPad 真机、模拟器、包大小分别记录结果；补真实家庭试用证据。

## 首个课堂存储切片

IOS-03 首段采用 SQLite schema 1。课堂当前轮次、历史、作答回执与计数作为一份带类型的快照，由单窗口 Swift 服务串行写入；SQLite 提交后才替换内存状态并返回成功。关闭多窗口以维持单写入者，iPad 单窗口仍可旋转或调整宽度。后续补备份和历史查询时保留冻结题单及完整作答回执，若需要迁移内部存储，必须在保留档案的前提下引入新版 schema。该内部快照不作为跨端备份格式。

## iOS 界面尺寸与辅助功能

UIKit 继续约束 WebView 安全区并传入系统正文点数和辅助字号状态。网页按可用宽高重排，窄窗和大字号采用单列，宽且高的窗口在课堂详情旁显示课程侧栏。课程和题目由同一份 React 状态驱动。iOS 样式由现有原生平台标记启用。XCUITest 以仅 Debug 构建读取的 UUID 启动参数选择独立缓存档案，并使用临时 WebKit 存储。参见 [Apple 布局指南](https://developer.apple.com/design/human-interface-guidelines/layout)和[辅助功能指南](https://developer.apple.com/design/human-interface-guidelines/accessibility)。
