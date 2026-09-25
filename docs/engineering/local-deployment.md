# Mac Studio 本地部署与开发

当前开发只监听127.0.0.1，没有开放公网、安装系统根证书或配置launchd。以下局域网部署在SPEC-001认证完成后执行；不要把未鉴权基线直接暴露成家庭正式服务。

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

认证和发布门禁完成后启动：

```sh
npm run build
uv run --locked uvicorn server.main:app --host 0.0.0.0 --port 8443 --ssl-certfile certs/lan.pem --ssl-keyfile certs/lan-key.pem --no-access-log
```

浏览器访问 `https://mac-studio.local:8443`。初次网络权限、防火墙弹窗由维护者批准；只开放家庭LAN，不配置路由器端口转发。静态资源自托管，不依赖字体CDN或Swagger CDN。若未来加反向代理，必须关闭音频上传请求的磁盘缓冲和body日志。

## 运行管理（SPEC-006实现）

- 登录后launchd启动而非要求root。LaunchAgent需绝对工作路径与`uv`路径，单API worker；评分子进程槽位受限。现阶段不装自启。
- Mac需保持开机和网络可达；系统睡眠会使客户端显示服务器不可达。不要为了测试全局永久关闭用户电源管理。
- 每日SQLite backup API导出一致备份到`private/backups/`，保留7个日备份。不要只复制正在写入的db而遗漏WAL。
- 恢复前关闭服务、保留旧库、验证schema版本，恢复后跑完整性检查。证书/凭据不混进学习JSON导出。
- 版本升级前备份DB，应用向前迁移；回滚需要相容schema或一并恢复备份。不要直接用旧代码读取新版数据库。
- 安装依赖和下载审核资产可联网；完成后断WAN保持LAN，验证全部课程/评分可用。禁止启动时自动下载模型。Mac离线SDK若要求联网激活，应单列维护行为，不含录音外传。

## 可移植性

`npm ci` + `uv sync --locked` 可在其他开发电脑重建。Mac Studio上的推理性能/本地SDK需单独实测；浏览器客户端不安装Python。未来原生壳仍访问该API，若要外出使用或服务器随身部署，另立需求，不暴露家庭评分端口到公网。
