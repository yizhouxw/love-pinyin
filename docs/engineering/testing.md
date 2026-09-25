# 验证策略

当前自动化仅验证工程基线、课程完整性保护和真实的未就绪状态。业务还未实现，没有假称完整应用已测试。

## 分层

| 层        | 自动检查                                               | 关键人工检查                           |
| --------- | ------------------------------------------------------ | -------------------------------------- |
| 内容      | Schema、ID、引用、先修DAG、选项答案、NFC、知识题目覆盖 | 教师核对发音/音节合法性/字形/课标差异  |
| 领域      | 时钟注入、幂等、选课限制、复习到期、迁移               | 是否适合课堂节奏                       |
| API       | 请求范围、配对/越权、WAV大小、取消、队列、事务回滚     | WAN断网仅LAN运行、数据恢复演练         |
| UI        | 键盘操作、触摸模拟、横向溢出、错误态                   | 真机手指操作、可读字形、声音与打断行为 |
| 评分      | 合成信号验证依赖；金标集准确性/拒判/性能报告           | 教师盲标、儿童不同音域/噪声/易混音     |
| 安全/隐私 | 无外部请求、录音不落盘、无敏感日志、断开释放           | 实际信任证书、家长同意说明             |

## 设备矩阵

开发基线目标：桌面Chrome/Edge120+、Firefox121+、Safari17+；iPadOS/iOS17+ Safari；Android Chrome120+。这是项目拟支持下限，不代表所有历史版本已验证。生产构建明确使用相应target。

Playwright覆盖当前随锁文件安装的Chromium/Firefox/WebKit、iPad/iPhone/Pixel视口。真实发布至少覆盖：Mac键鼠；Windows Chrome/Edge；iPad Safari横竖屏+触摸；iPhone Safari；Android Chrome。真实测试记录OS/浏览器精确版本、日期、设备、结果；不能把WebKit模拟称为iOS真机。

### 当前主机的 Firefox 例外

本机macOS27.0 + Playwright1.63.0的Firefox155启动立即报`Could not find profile folder`，显式新建profile和更换TMPDIR仍失败。症状与[Playwright #42768](https://github.com/microsoft/playwright/issues/42768)、[Mozilla #2060476](https://bugzilla.mozilla.org/show_bug.cgi?id=2060476)一致；没有改系统权限或降低安全设置。该上游报告本身记录其他Playwright版本，本机1.63结论来自实际复现，不能混淆。

`npm run test:e2e`始终运行完整6项目，当前主机会重现Firefox启动失败。`npm run test:e2e:local`只在macOS27且精确Playwright1.63、非CI时明确打印原因并运行另外5项目；其他环境仍全跑。`verify:all`使用这个本机命令。Linux CI使用完整命令，不能把本机5/5写成完整跨浏览器验收。升级Playwright后本机命令自动恢复Firefox测试；真实Firefox与真机仍是发布门禁。

最低必测：320px无横向滚动、200%缩放、触摸目标≥48px、仅键盘可完成、拖拽替代、减少动画、屏幕锁定/切后台恢复、蓝牙/有线/内置麦克风、拒绝/撤销权限、示范与录音不串音、LAN断开、Mac重启、iPad证书信任。

## 发布门禁

`validate:release` 当前应失败：草稿未教师批准、音频未制作、最新课标条文差异未审、每知识点题库需扩展、本地评分未通过。其失败不等于工程基线损坏；不得为了CI绿而删门禁。

发音样本指标和设备预算以 SPEC-000 为准，性能预算是验收目标而非实测结论。持权样本保存在私有测试位置，不进入开源仓库；只入库匿名聚合结果与脚本。
