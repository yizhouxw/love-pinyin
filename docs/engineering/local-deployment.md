# Mac Studio 本地部署与开发

当前应用提供家长配对、同源会话认证、CSRF/来源校验和 SQLite 持久化。局域网命令要求显式指定 HTTPS 证书；这仍是开发/家庭试用部署，不代表通过儿童产品发布门禁。本仓库不会开放公网、安装系统根证书或自动配置 launchd。

## 开发与统一B/S预览

运行 `npm run dev:api` 和 `npm run dev` 可热更新；Vite代理API，前端不需要CORS通配。运行 `npm run build` 后 `npm run serve:local`，FastAPI同源提供整个 `dist/` 和 `/api/v1`。

部署只需Mac、同一局域网和浏览器，不需要Docker、公网IP或云账号。路由器给Mac保留固定LAN地址；客户端输入该地址或Mac的 `.local` 主机名。不要把127.0.0.1发给iPad，那会指向iPad自己。

## HTTPS与麦克风

远程LAN的普通HTTP不是浏览器安全上下文，不能据本机localhost录音成功推断iPad可录。[MDN getUserMedia要求](https://developer.mozilla.org/en-US/docs/Web/API/MediaDevices/getUserMedia)

家庭开发证书使用mkcert（BSD-3-Clause）；参考[官方安装与移动设备信任说明](https://github.com/FiloSottile/mkcert)。在自家设备上安装信任根是维护者明确操作；本仓库不自动更改系统信任。示例：

```sh
brew install mkcert
mkcert -install
mkdir -p certs
# 将示例主机名和IP换成你的实际Mac地址
mkcert -cert-file certs/lan.pem -key-file certs/lan-key.pem mac-studio.local 192.168.1.20 localhost 127.0.0.1
```

用 `mkcert -CAROOT` 找到 `rootCA.pem`，仅将公有根证书导入自家iPad/iPhone，并在系统证书信任设置明确启用。**绝不分发 `rootCA-key.pem` 或 `lan-key.pem`**。Android/Windows等客户端也需信任相同根；若不信任，不以点击忽略浏览器警告作为验收通过。

按上文生成受信任证书后，设置证书文件路径并启动：

```sh
npm run build
export LOVE_PINYIN_TLS_CERT="$PWD/certs/lan.pem"
export LOVE_PINYIN_TLS_KEY="$PWD/certs/lan-key.pem"
npm run serve:lan
```

浏览器访问 `https://mac-studio.local:8443`。初次网络权限、防火墙弹窗由维护者批准；只开放家庭LAN，不配置路由器端口转发。静态资源自托管，不依赖字体CDN或Swagger CDN。若未来加反向代理，必须关闭音频上传请求的磁盘缓冲和body日志。

## 运行、备份与升级

- 当前先在终端前台运行服务，不需要 root。Mac需保持开机和网络可达；系统睡眠会使客户端显示服务器不可达。不要为了测试全局永久关闭用户电源管理。
- 升级或日常维护时运行 `npm run backup:local`。命令通过 SQLite online backup API 读取一致快照（包含已提交 WAL 内容），校验 `integrity_check` 与迁移表后原子写入 `private/backups/`，目录权限为 `0700`、文件权限为 `0600`，最多保留最近 7 份。它不会创建缺失数据库，也不会备份浏览器录音。需要每日备份时，可用 macOS LaunchAgent 在维护者选定的时刻执行该命令；本仓库不擅自安装或加载任务。
- **数据库恢复：**先停止本项目服务；选择一份备份并检查文件名/日期，然后把当前数据库及同名 `-wal`、`-shm` sidecar（若存在）改名留档。把备份复制到同目录的 `love-pinyin.sqlite3.restore`，设为 `0600` 并运行 `sqlite3 private/data/love-pinyin.sqlite3.restore 'PRAGMA integrity_check;'` 确认结果为 `ok`，最后在同一文件系统内将 `.restore` 原子改名为 `love-pinyin.sqlite3`。启动前确认没有旧的 WAL/SHM sidecar 留在正式文件名下，再用将要运行的应用版本启动，让其按迁移规则继续。若检查失败，恢复留档文件及 sidecar 并查明原因。备份含设备配对哈希和学习记录，必须像数据库一样保护，不能提交 Git 或放入公共同步目录。
- 版本升级前备份数据库，再构建新版：`npm ci`、`uv sync --locked`（依赖锁有变化时）、`npm run build`。应用只向前迁移；不要拿旧代码直接打开新版数据库。若需回滚程序，先检查该版本是否兼容当前 schema；不兼容时停止服务并同时恢复对应的升级前数据库备份。
- 家长页的家庭 JSON 导出是便携式学习数据备份，可在同版或支持的旧版 schema 间预览、迁移和恢复；SQLite 运维备份另含完整家庭服务状态。两者都不包含录音内容。
- 卸载时先停止服务，再按家长意愿分别保留或删除 `private/data/`、`private/backups/`；证书及其私钥按维护者自己的证书管理方式处理。不要把备份、家庭数据库或私钥混进公开仓库。
- 安装依赖和下载审核资产可联网；完成后断WAN、保持LAN，验证已实现课程与家庭数据访问仍可用。当前跟读/本地评分诚实显示未就绪，不能当作断网评分通过。禁止启动时自动下载模型。Mac离线SDK若要求联网激活，应单列维护行为，不含录音外传。

## 可移植性

`npm ci` + `uv sync --locked` 可在其他开发电脑重建。Mac Studio上的推理性能/本地SDK需单独实测；浏览器客户端不安装Python。未来原生壳仍访问该API，若要外出使用或服务器随身部署，另立需求，不暴露家庭评分端口到公网。
