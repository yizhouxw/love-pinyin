# 验证策略

当前已有本机 B/S 业务预览。自动化覆盖无音频视觉练习、家长管理、SQLite 事务/API 和跨视口浏览器交互；下表区分自动化证据与尚缺的人工、真机或外部验收，不把开发预览描述成发布完成。

## 分层

| 层        | 自动检查                                                   | 关键人工检查                           |
| --------- | ---------------------------------------------------------- | -------------------------------------- |
| 内容      | Schema、ID、引用、先修DAG、选项答案、NFC、题目知识点覆盖   | 教师核对发音/音节合法性/字形/课标差异  |
| 领域      | Vitest掌握函数；API幂等、双设备并发、复习、迁移与事务回滚  | 是否适合课堂节奏、完整算法验收         |
| API       | 26项隔离SQLite认证、会话、家庭数据、备份和恢复校验         | WAN断网仅LAN运行、实际灾备恢复演练     |
| UI        | 10项Chromium/WebKit桌面/平板/手机模拟，键盘/触摸、错误态   | 真机手指操作、可读字形、声音与打断行为 |
| 评分      | 合成信号仅验证DSP依赖安装；音素/声调评分尚未接入           | 教师盲标、儿童不同音域/噪声/易混音     |
| 安全/隐私 | 配对/撤销、CSRF/Origin、无第三方音频代码路径、私有文件权限 | WAN隔离抓包、证书信任、家长同意说明    |

## 设备矩阵

开发基线目标：桌面Chrome/Edge120+、Firefox121+、Safari17+；iPadOS/iOS17+ Safari；Android Chrome120+。这是项目拟支持下限，不代表所有历史版本已验证。生产构建明确使用相应target。

Playwright覆盖当前随锁文件安装的Chromium/Firefox/WebKit、iPad/iPhone/Pixel视口。真实发布至少覆盖：Mac键鼠；Windows Chrome/Edge；iPad Safari横竖屏+触摸；iPhone Safari；Android Chrome。真实测试记录OS/浏览器精确版本、日期、设备、结果；不能把WebKit模拟称为iOS真机。

### 当前主机的 Firefox 例外

本机macOS27.0 + Playwright1.63.0的Firefox155启动立即报`Could not find profile folder`，显式新建profile和更换TMPDIR仍失败。症状与[Playwright #42768](https://github.com/microsoft/playwright/issues/42768)、[Mozilla #2060476](https://bugzilla.mozilla.org/show_bug.cgi?id=2060476)一致；没有改系统权限或降低安全设置。该上游报告本身记录其他Playwright版本，本机1.63结论来自实际复现，不能混淆。

`npm run test:e2e`始终运行完整6项目，当前主机会重现Firefox启动失败。`npm run test:e2e:local`只在macOS27且精确Playwright1.63、非CI时明确打印原因并运行另外5项目；其他环境仍全跑。`verify:all`使用这个本机命令。Linux CI使用完整命令，不能把本机5/5写成完整跨浏览器验收。升级Playwright后本机命令自动恢复Firefox测试；真实Firefox与真机仍是发布门禁。

最低必测：320px无横向滚动、200%缩放、触摸目标≥48px、仅键盘可完成、拖拽替代、减少动画、音频播放释放、LAN断开、Mac重启、iPad证书信任。

## 发布门禁

`validate:release` 当前应失败：草稿未教师批准、音频未制作、最新课标条文差异未审、每知识点题库需扩展。首版已暂缓发音评测，不再以评分模型/儿童样本门禁阻塞发布。

发音样本指标和设备预算以 SPEC-000 为准，性能预算是验收目标而非实测结论。持权样本保存在私有测试位置，不进入开源仓库；只入库匿名聚合结果与脚本。
