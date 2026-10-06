# ADR-0001：使用自有 Mac Studio B/S 架构

日期：2026-09-25；状态：B/S决定继续采纳，录音/评分部分已由[ADR-0004](0004-defer-pronunciation-assessment.md)取消。

采用React/Vite + FastAPI/SQLite，浏览器共享Mac保存的进度和本地资源。用户要求自有Mac服务，跨电脑/iPad/手机维护一套Web界面；单家庭无需Redis/Postgres、云账号或公网入口。本期不做原生工程或SSR。

初始选择Python还考虑本地声学研究；当前运行时不含评分worker，不录音。代价仍是Mac需开机、客户端需可达LAN及可信HTTPS，需要维护配对、备份与证书。“离线”指无互联网但LAN连通；断LAN不保证继续保存。当前实现见[架构](../architecture.md)。
