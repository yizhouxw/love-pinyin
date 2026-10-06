# 验证策略

自动化、真实声音、实际浏览器与家庭真机各自证明不同范围。最新已记录结果集中在[STATUS](../STATUS.md)，需求对应关系见[交付核对](delivery-audit.md)。

## 准备与命令

先用锁定环境安装依赖和Playwright浏览器。`test:e2e:live`、`test:e2e:product`、`test:e2e:soak`及包含live的 `verify:all` 都需要按README准备本机私有声音；缺资源应失败，不填入假音频。

| 命令                       | 覆盖与限制                                                        |
| -------------------------- | ----------------------------------------------------------------- |
| `npm run verify`           | 格式、lint、TS、Schema/内容、Vitest及构建                         |
| `npm run verify:server`    | Ruff与pytest：纯领域规则、实际SQLite/API、权限/迁移/并发/版本边界 |
| `npm run test:e2e`         | 六个引擎/视口项目，可使用API/Audio替身验证布局和故障              |
| `npm run test:e2e:local`   | 本机兼容选择，Firefox例外见下                                     |
| `npm run test:e2e:live`    | 独立真实服务/SQLite，家庭/访客数据、历史恢复、停服、灾备与小结    |
| `npm run test:e2e:product` | 实际WAV/MP3、完整游戏、讲解、书写/图片与资源失败恢复              |
| `npm run test:e2e:soak`    | 独立20分钟长测；不包含在verify:all中                              |
| `npm run verify:all`       | verify + verify:server + test:e2e:local + test:e2e:live           |
| `npm run validate:release` | 当前内容覆盖、课标证据与本机声音完整性，不含真机验收              |

Linux CI安装锁定依赖，执行工程/API、许可证清单检查和完整六视口项目。CI不带家庭私有声音，不执行live/product/soak或完整家庭发布验收。运行记录须注明命令、提交、环境和范围，不将本地结果写作远程CI通过。

## 回归证据组织

| 范围       | 核验方式                                                                                          |
| ---------- | ------------------------------------------------------------------------------------------------- |
| 内容       | 引用、NFC、先修、答案/目标、题量、中文语音与书写/图片结构；人工另核课程依据和字形                 |
| 进度       | Python纯函数与SQLite事务覆盖8条窗口、模式、业务日、并发去重、复习、时钟回退                       |
| 配对/备份  | 权限、CSRF、坏备份拒绝、预览revision、事务替换、删除与撤销；真实浏览器文件往返                    |
| 历史与顺序 | 登记快照、冻结题单/选项、旧答案判分、访客恢复；未知版本拒绝                                       |
| 声音       | 实际解码、非静音、播放/停止/重听、互斥、题前播放门槛与故障重试                                    |
| 游戏       | 四类玩法、提示/纠正只保留首答、拼读确认前不提交、跳过/休息/小结                                   |
| 书写/图片  | 逐笔及标调说明、图片加载门槛、语音互斥；课程活动不写伪成绩                                        |
| 服务故障   | RECOVERY-01实际stop/start；DISASTER-01仅损坏临时库并同版恢复；ROLLBACK-01未知schema拒绝且文件不变 |
| LAN工具    | 临时真实证书检验有效期/IP SAN/密钥匹配，独立HTTPS服务；不安装系统信任                             |

测试数据库、端口与声音资源访问须隔离于运行家庭服务。真实产品成功路径不mock API或Audio；请求中断可用于故障注入。复习/历史测试会在隔离库构造过去状态，应明确这不是孩子实际掌握或运行过旧二进制的证据。

## 浏览器与实际设备

Vite的Chrome/Edge120、Firefox121、Safari17是构建语法目标，产品支持下限待真机矩阵冻结。至少补齐Mac/Windows键鼠、iPad横竖屏与触摸、iPhone Safari、Android Chrome、Firefox、屏幕阅读器、320px/200%文字、48px目标和音频中断。

实际Mac操作证据分别见[Chrome](desktop-chrome-acceptance.md)与[Safari](desktop-safari-acceptance.md)。Playwright WebKit不等于原生Safari，iPad视口不等于iPad设备；本机服务停止不等于真实Wi-Fi故障。

### 本机Firefox例外

已记录macOS27.0 + Playwright1.63.0 Firefox启动报 `Could not find profile folder`。`test:e2e:local`只在这一精确组合且非CI时打印原因并选择另外五项目；`test:e2e`始终保留六项目，其他环境不跳过。既有调查关联[Playwright #42768](https://github.com/microsoft/playwright/issues/42768)及[Mozilla #2060476](https://bugzilla.mozilla.org/show_bug.cgi?id=2060476)，不将上游其他版本的报告当作本机测试。升级后须重验，不能把五项目通过写成Firefox通过。

## SOAK-01 长时观测

实际安装Chrome与Playwright WebKit分别在隔离服务中运行至少20分钟墙钟时间。`LOVE_PINYIN_SOAK_SECONDS=90 npm run test:e2e:soak`仅是烟测，不满足长测验收。全程真实题目与声音、UI答题和休息，导出记录数必须一致。

WeakRef追踪媒体，记录play到playing、切题延迟及轮末媒体/AudioContext/Blob URL；等待休息语音释放后活动资源归零。观测器v2要求每次标准音都有延迟样本，失败或中断即使满20分钟也不能算完成。Chrome轮末显式GC后的堆数据不是自然内存曲线；WebKit不填虚构堆值。详情和原始证据索引见[长测结果](audio-soak-results.md)。

## 文档变更

纯文档切片检查Prettier、本地链接、命令/路径/接口与代码一致性；有数量描述时从内容/资源生成结果核对。无需重跑与文字无关的GUI。修改验收要求不得删除尚未完成的门禁，历史报告的限制必须保留。
