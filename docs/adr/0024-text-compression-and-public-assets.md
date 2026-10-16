# ADR-0024：文本传输压缩与静态资源缓存

日期：2026-10-16。状态：采纳。依据：SPEC-006 LAN-PERF-01。

家庭LAN的页面资源此前没有传输压缩，前端JS约421KB、课程JSON约389KB，即使客户端声明gzip也传原文。在不增加依赖的前提下，使用锁定Starlette的GZipMiddleware压缩JS/CSS和API JSON，最小1024字节、压缩级别5。媒体与Range响应保持原始字节，避免Safari字节探测和seek语义被改变；声音内容、摘要检查与权限保留。

Vite带哈希JS/CSS可缓存一年，字体缓存一天，ETag/Last-Modified仍由文件响应提供。只对成功静态响应设置这些策略；HTML、家庭和访客API、声音继续no-store，不设置service worker或缓存学习数据。不压缩已压缩音频/字体，不新增CDN、统计或外部请求。

网络诊断优先区分实际链路与服务端处理。双网卡Mac可使用已绑定的有线HTTPS地址，证书已覆盖时不再安装证书；URL变化的浏览器Cookie独立，需要重新配对或访客对比。ICMP丢失和睡眠设备不响应不能等同实际网页丢包率，真机结果由用户实测补充。
