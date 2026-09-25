# ADR-0001：使用自有 Mac Studio B/S 架构

状态：接受；2026-09-25；依据：用户明确要求。

选 React/Vite + FastAPI/SQLite，Mac Studio 本地运行评分 worker。用户允许浏览器将录音经局域网API传入自己的 Mac，禁止发送第三方。录音处理后丢弃，学习记录以服务器为主。

选择原因：跨电脑/iPad/手机只维护一套 Web 界面，Python 适配本地声学计算，Mac 的统一硬件减少浏览器模型兼容性问题，后续 Capacitor 保留 API。简单家庭部署不需要 Redis/Postgres、Kubernetes、云账号或公网端口。

未采用：纯浏览器WASM评分（用户选B/S且设备约束更复杂）、云评分（违反录音边界）、原生先行（超出本期）、Next.js服务端渲染（主要是交互学习，无当前SEO需求且增加双后端复杂度）。

代价：Mac需开机且客户端处于可达LAN；iPad/手机麦克风需要可信HTTPS；需管理备份、会话和局域网证书。离线是断互联网仍可用，不能保证断LAN可评分。
