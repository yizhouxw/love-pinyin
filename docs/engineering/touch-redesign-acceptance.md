# 2026-11-13 触屏游戏重设计与字音对齐验收

验收范围：SPEC-017 REDESIGN-01～04、SPEC-022 WORD-16/17、SPEC-012 READ-08；架构见 ADR-0042。本次没有新增依赖、数据库迁移或外部服务。

## 实际实现

四个标题分别实现横向跑跳摘果、二维绕礁救鸭与靠岸、鼓心/鼓边节奏模仿、带预览的轨迹投递。真实动作碰撞触发原有题目接口；错过、碰礁和投递未命中不判拼音错误。果树附近辅助仅减速，不停车或强迫摘果；被动弹起不能提交答案。碰礁后寻路与碰撞共用船体半径，允许脱离礁石并重新靠岸，路过其他码头不提交答案。保留已有难度、速度、有限题量、关卡和家庭额度；拖动都有点击替代，声音播放、暂停、切换后台及保存失败时停止动作。

词语拼读采用独立滚动词卡区，示意图、播放和快捷设置保留在滚动区外。连读及旋转只校准当前词在内层的位置，不抢焦点、不滚动整个页面；天天练列表和课文段落复用同一逻辑。极小视口允许页面滚动以保留操作入口。

词卡、听写揭晓、示意图说明、天天练词句与例词、拼音小铺统一逐字注音。一个音节与对应汉字共用一列，标点不参与居中，儿化组合来自集中内容表。长词换行时整个字音单元一起移动，卡片随内容增高；隐藏答案保留实际内容尺寸且从无障碍树隐藏，揭晓不会撑高卡片。

参考 [Apple Accessibility HIG](https://developer.apple.com/design/human-interface-guidelines/accessibility)：常用操作采用单指、直接点击与键盘替代，主要游戏触摸目标至少 44pt，语音同时配合视觉提示；这不是 Apple 官方认证。

## 自动化与真机证据

浏览器测试使用真实本机 API 与实际声音文件，覆盖首答记录、网络失败重试、恢复会话、设置、声音保护、减少动态效果、键盘、三题完整旅程、触摸拖动取消，以及 320px、横屏、200% 文字的字音对齐。几何检查逐列比较音节与汉字中心（容差 1px），并检查上下行不重叠及长词不越出卡片。

真实设备使用独立 UI 测试档案，不重置家庭学习数据。iPhone 13 的四游戏与词语工作区通过（`build/ios/redesign-iphone-final.xcresult`）；iPad Air 4 的四游戏与词语工作区通过（`build/ios/redesign-ipad-final-04.xcresult`）。两端均检查横竖屏、暂停、后台恢复及实际听写画面。iPad 曾因测试程序开发者信任失败，用户处理设备信任后重新通过。截图位于忽略目录 `private/redesign-{iphone-final,ipad-final-04}/`，听写字音已目视检查。

长词布局与隐藏答案高度的最终补充真机检查也已通过：`build/ios/redesign-iphone-word-final-05.xcresult` 与 `build/ios/redesign-ipad-word-final-05.xcresult`。浏览器专项初轮 28 项中 24 项通过；其余为测试探针在关卡完成后继续等待已卸载场景、以及 SVG 竖直轨迹零宽度误判，修正探针后相关 6 项在 Chromium/WebKit 全部通过（`/tmp/redesign-space-final.log`），最终 `npm run verify:all` 全部通过：217 项前端、563 项服务端、36 项本地页面与 82 项真实 API 页面测试；`npm run validate:release` 通过。日志为 `/tmp/redesign-verify-release.log` 与 `/tmp/redesign-release.log`。本次真机运行的是离线 App，不能据此扩大为家庭 LAN 故障验收；儿童实际趣味性与教学效果仍需家庭试用，不以自动化测试替代。

## REDESIGN-05 用户实测问题回归

跑酷停在错误果实前的问题来自辅助模式的零速度等待；改成非零减速，并把主动跳跃与碰树根的被动弹起分开。河湾碰礁后无法靠岸的问题来自寻路 15px、碰撞 13px 两套边界；改为集中船体半径，使碰礁停下的位置仍能计算逃离路径。手动航行只有目的地明确位于码头才允许提交，途经码头不算选择；自动投递只提交所选目的地，飞行中的按钮明确禁用。

`tests/e2e-product/game-motor-recovery.spec.ts` 使用实际鼠标/触摸等价指针操作，不注入物理状态：跑酷放过整轮果实后主动摘取；船只点击礁石撞停、按住拖离、松手停止、再次撞停、再点正确码头；鼓岛敲错后重新完成节奏。星际投递另检验按下、短距离拉动、取消、重新释放与实际到达。断言首答记录未被动作失误污染。Chromium/WebKit 共 26 项游戏专项通过，包含上述恢复路径、四款完整旅程、设置、暂停、刷新恢复和轨迹投递，日志 `/tmp/redesign-motor-recovery.log`，过程截图 `private/redesign-motor-recovery/`。

长词卡片在固定高度滚动网格中还需显式使用 `grid-auto-rows: max-content`，否则网格会把换行卡片压回最小高度。最终逐卡边界断言与实际点击在两引擎通过（`/tmp/word-card-containment-final.log`）。

卡住修复后的 iPad 两项真机套件通过（`build/ios/redesign-ipad-recovery.xcresult`）。浏览器三条实际操作路径另录制为手机尺寸录像，保存在 `private/redesign-proof/{runner-pass-fruit,boat-recovery,drum-retry}.webm`；未注入游戏状态，使用真实指针、碰撞和 API 记录。

卡住修复后的 iPhone 13 四游戏与词语工作区也已通过（`build/ios/redesign-iphone-recovery-04.xcresult`）。设备信任恢复后曾遇到 XCTest 自动化启动超时，显式重新启动测试程序后，两项套件实际执行并通过；未把启动失败计为功能通过。两台设备最终均安装本次修复。
