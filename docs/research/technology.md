# 技术选型与当前实现

本文保留仍影响产品的选型理由；2026-09-25的声学worker、录音传输及评分候选研究已退出首版，历史由Git保留。当前结构以[架构](../architecture.md)为准，版本/来源/许可由[依赖清单](../engineering/dependencies.md)维护。

| 决策                      | 原因与取舍                                                                      |
| ------------------------- | ------------------------------------------------------------------------------- |
| React + TypeScript + Vite | DOM控件适合点选、键盘、触摸与可访问性；构建静态文件由Mac提供                    |
| 不引入SSR或游戏引擎       | 当前无服务端渲染需求，也无持续物理/碰撞玩法，避免第二套后端或Canvas交互体系     |
| FastAPI + Python 3.12     | 已有内容、配对、进度、备份与资源实现；保留最初Python后端，但不运行声学任务      |
| SQLite标准库              | 单Mac单家庭，无PostgreSQL/Redis部署成本；通过事务、迁移、备份和幂等处理多客户端 |
| 本地静态声音              | 中文指令准备时生成，标准音固定来源，运行时无合成、模型、远程CDN或识别降级       |
| 同源B/S与显式LAN HTTPS    | 浏览器共享Mac进度，避免跨源配置；需要Mac开机与家庭证书信任                      |
| 暂不做PWA/原生壳          | 本期依赖Mac服务；service worker、Capacitor与脱离服务器学习均未实现              |

原选型资料（2026-09-25记录，非本次重新核验）：[React交互](https://react.dev/learn/adding-interactivity)、[Vite构建](https://vite.dev/guide/build)、[FastAPI部署](https://fastapi.tiangolo.com/deployment/)、[SQLite](https://www.sqlite.org/docs.html)。表中的复杂度与适配判断是项目决策，不是第三方性能结论。

## 实施约束

教学规则与答案在content；React只呈现/交互，进度在服务端纯函数。音频通过浏览器适配器协调，播放失败或Mac不可达不判孩子错误。会话冻结内容与选项顺序，导入旧备份只接受登记的历史内容，未知数据库版本拒绝启动。

配对与CSRF保护家庭记录；访客资源无配对访问是明确边界。当前没有CSP，不能把原设计要求当作已部署保护。详见[API](../api-contract.md)与[隐私](../engineering/privacy.md)。

## 跨端与后续工作

构建目标为Chrome/Edge120、Firefox121、Safari17，属于语法输出设置，尚未成为验证过的支持下限。实际Chrome/Safari、Playwright引擎及视口的证据分开；移动设备、屏幕阅读器、家庭HTTPS和断WAN仍需验收。操作目标48px、320px布局和200%文字是项目验收标准，不由构建器自动保证。

未来封装Android/iOS需另立SPEC，处理网络发现、权限、证书、后台和发行；保留Web主体不代表零改动上架。重启发音评测也须新立项，不能直接启用已暂停研究代码。
