# 验证策略

自动化覆盖语音引导的实际桌面练习、家长管理、SQLite事务/API、真实文件和跨视口交互。下表区分实际产品用例与模拟边界、人工和真机验收；最新数量与未完成项见 [STATUS](../STATUS.md)。

## 分层

| 层        | 自动检查                                                   | 关键人工检查                           |
| --------- | ---------------------------------------------------------- | -------------------------------------- |
| 内容      | Schema、ID、引用、先修DAG、选项答案、NFC、题目知识点覆盖   | 教师核对发音/音节合法性/字形/课标差异  |
| 领域      | Vitest掌握函数；API幂等、双设备并发、复习、迁移与事务回滚  | 是否适合课堂节奏、完整算法验收         |
| API       | 隔离SQLite认证、会话、家庭数据、备份和恢复校验             | WAN断网仅LAN运行、实际灾备恢复演练     |
| UI        | Chromium/WebKit真实桌面产品与模拟视口，键盘/触摸、错误态   | 真机手指操作、可读字形、声音与打断行为 |
| 声音      | 实际WAV/MP3解码、内容脚本覆盖、同源播放和故障重试          | 准确单音、耳听清晰度与教学审校         |
| 安全/隐私 | 配对/撤销、CSRF/Origin、无第三方音频代码路径、私有文件权限 | WAN隔离抓包、证书信任、家长同意说明    |

## 设备矩阵

开发基线目标：桌面Chrome/Edge120+、Firefox121+、Safari17+；iPadOS/iOS17+ Safari；Android Chrome120+。这是项目拟支持下限，不代表所有历史版本已验证。生产构建明确使用相应target。

Playwright覆盖当前随锁文件安装的Chromium/Firefox/WebKit、iPad/iPhone/Pixel视口。真实发布至少覆盖：Mac键鼠；Windows Chrome/Edge；iPad Safari横竖屏+触摸；iPhone Safari；Android Chrome。真实测试记录OS/浏览器精确版本、日期、设备、结果；不能把WebKit模拟称为iOS真机。

### 当前主机的 Firefox 例外

本机macOS27.0 + Playwright1.63.0的Firefox155启动立即报`Could not find profile folder`，显式新建profile和更换TMPDIR仍失败。症状与[Playwright #42768](https://github.com/microsoft/playwright/issues/42768)、[Mozilla #2060476](https://bugzilla.mozilla.org/show_bug.cgi?id=2060476)一致；没有改系统权限或降低安全设置。该上游报告本身记录其他Playwright版本，本机1.63结论来自实际复现，不能混淆。

`npm run test:e2e`始终运行完整6项目，当前主机会重现Firefox启动失败。`npm run test:e2e:local`只在macOS27且精确Playwright1.63、非CI时明确打印原因并运行另外5项目；其他环境仍全跑。`verify:all`使用这个本机命令。Linux CI使用完整命令，不能把本机5/5写成完整跨浏览器验收。升级Playwright后本机命令自动恢复Firefox测试；真实Firefox与真机仍是发布门禁。

最低必测：320px无横向滚动、200%缩放、触摸目标≥48px、仅键盘可完成、拖拽替代、减少动画、音频播放释放、LAN断开、Mac重启、iPad证书信任。

## 发布门禁

`validate:release` 当前应失败：草稿未教师批准、逐目标标准音未就绪、最新课标条文差异未审、每知识点题库需扩展。已准备的中文指令和私有整课录音不能关闭标准音门禁。首版已暂缓发音评测，不再以评分模型/儿童样本门禁阻塞发布。

SPEC-000保留为已暂停的研究；其样本和性能目标不属于本期验收。

## 真实 B/S 桌面数据往返

`npm run test:e2e:live` 构建前端后，在 Chromium 和 WebKit 桌面浏览器分别执行 R-012-GUI-01：通过页面配对与作答、导出真实 JSON、拒绝损坏备份且保留已有记录、确认删除、预览并确认导入、刷新后再次导出并比较原始作答和会话。它不拦截或模拟 API；每个测试启动真实 FastAPI、独立 SQLite 临时目录和系统分配的 loopback 端口，结束后停止服务并清理该目录。已纳入 Mac 本机 `verify:all`。Linux CI 无家庭私有语音资源，不执行该产品流程，也不把模拟测试替代为产品验收。失败保留 Playwright trace 和截图到忽略的 `test-results/`，不记录家庭真实数据。此项与模拟 API 的跨视口测试互补，不是 LAN/真机验收。

## 真实语音产品验收

`npm run test:e2e:product` 必须先准备真实 `private/learning-audio/`；资源缺失会失败，不跳过也不填入测试音。测试独立SQLite，在Chromium/WebKit解码全部中文语音和14课映射录音，检查真实非静音样本/时长，通过界面开始听题、停止、重播及听中文选项，并核对无作答请求。媒体故障使用请求中断注入以验证失败与重试，成功路径没有mock API或Audio。另验证资源状态未知也不放开无声答题、退出后不留提示，以及错答后修正只存一次首次错误。解码成功证明技术播放，不等同逐拼音发音审校或人耳听感评价。此命令不在没有私有语音资源的Linux CI伪造通过；普通CI继续跑逻辑、接口和模拟浏览器边界测试。

## 私有标准音制作回归

`test_audio_review.py`的合成PCM仅验证裁切/完整性/准入。`npm run test:e2e:product`还需先执行本机审音台的显式源音导入；其review-server fixture从实际已准备PCM复制一份到临时目录，桌面Chromium/WebKit播放、裁切并保存草稿，销毁测试目录，不改变家庭素材与审核清单。缺少源音时失败，不跳过或替换成模拟声音。该用例不确认候选的拼音准确性。
