# SPEC-014：项目目录整理

2026-10-16，按用户要求减少根目录散落文件，使开发、测试与部署文件归类清晰。不调整产品功能、内容规则、依赖版本或运行数据位置。

- STRUCT-01：Vite、Vitest、ESLint、Playwright 配置集中在 `config/`；Dockerfile 与架构覆盖配置集中在 `deploy/docker/`。根目录保留 README、治理/许可文件、启动器、依赖清单/锁文件、工具自动发现文件、HTML 入口和默认 Compose 入口。
- STRUCT-02：现有 npm 命令、Mac 启动入口和 CI 继续可用；测试目录、结果和 HTML 报告仍以仓库根目录为基准，不能因配置迁移而漏跑测试。执行工程全量验证与资源发布检查；product/soak 配置另检查测试发现。
- STRUCT-03：默认 `docker compose` 命令继续可用，构建上下文仍为仓库根目录；显式 Docker build 与 amd64 覆盖命令同步路径，白名单包含迁移后的构建配置。检查两组 Compose 展开配置与 Docker 构建入口。本次路径整理不代表重新完成镜像运行、Windows/amd64或家庭真机验收。

README 提供目录职责导览。保留既有未提交修改、未追踪文件及本地模型、缓存、家庭数据；本次不清理用户资产。无新增依赖，不涉及跨模块架构决策。

## 验收记录（2026-10-16）

STRUCT-01～03的软件验证通过。根目录受 Git 管理的文件由34个减少到25个：7个工具配置迁入config，Dockerfile与amd64覆盖文件迁入deploy/docker；README提供目录导览。默认Compose入口、Mac启动入口、依赖和运行数据位置保留。

当前工作区执行 `npm run verify:all` 成功：66项前端/工具测试、326项服务端测试、30项本机视口测试及24项真实API/SQLite浏览器测试通过。沿用已记录的macOS27/Playwright1.63 Firefox例外，本机视口部分仍只验证五项目。`npm run validate:release`通过。默认六项目测试发现36项，product发现64项，soak发现2项；本次未执行product和soak用例。

两组Compose展开配置均通过，构建上下文保持仓库根目录，Dockerfile新路径有效，amd64构建和运行平台保持linux/amd64。`docker build --check -f deploy/docker/Dockerfile .`通过且无警告；`docker build --target web -f deploy/docker/Dockerfile .`实际完成锁定依赖安装、TypeScript检查、前端构建与内容结构验证，验证新白名单和COPY路径。文档格式、本地链接及Git差异检查通过。未新增或升级依赖。

本机证据位于忽略目录private中的structure-verify-all.log、structure-release.log、structure-compose.json、structure-compose-amd64.json、structure-docker-check.log及structure-docker-web.log。上述工作区含整理前已有的安装脚本等未提交修改；这些修改与未追踪PDF均保留，不纳入本次提交。

剩余门禁：本次未重建完整运行镜像、重跑容器离线烟测或验证Windows/amd64；移动真机、家庭HTTPS/LAN与家庭试用仍沿用SPEC-006/013未完成边界。
