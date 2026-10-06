# 安全与隐私

当前已实现家庭配对、角色权限、CSRF、SQLite事务及备份恢复。应用面向自有 Mac 的家庭网络；其他设备使用可信 HTTPS，不作为公网服务部署。首版不录音、不提供发音评测接口。

访客模式不读取家庭进度，但无需配对即可访问已安装教学音频。因此不要把此服务开放到不受信任网络，也不要将课程资源接口理解为只有家长才能下载。当前保护及未完成项见[隐私边界](docs/engineering/privacy.md)和[交付核对](docs/engineering/delivery-audit.md)。

仓库为 [yizhouxw/love-pinyin](https://github.com/yizhouxw/love-pinyin)。发现问题请通过已有私下联系渠道向维护者提供复现步骤、影响版本和脱敏日志，不附儿童信息、数据库、Cookie或证书私钥。目前未在本项目文档中确认专用漏洞报告渠道；公开发布前须配置可用渠道，不能假设 GitHub 私密漏洞报告已启用。
