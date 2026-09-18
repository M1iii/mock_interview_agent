# dev.ps1 一键启动脚本 — 设计文档

日期：2026-09-19
状态：已批准（含 `-KeepDocker` 开关）
关联需求：在启动前后端服务时自动启动 Docker 检索容器（Qdrant / ES / TEI）

## 背景与目标

当前项目启动需手动三步：`docker compose up -d`（检索三件套）→ venv uvicorn（后端 :8000）→ `npm run dev`（前端 :5173）。本脚本将三步收敛为一条命令，并在退出时按用户选择决定是否一并停止 Docker 容器。

## 决策记录（用户已确认）

| 决策点 | 结论 |
|---|---|
| 交付形态 | 根目录一个 PowerShell 脚本 `dev.ps1`，一条命令启动全部 |
| 退出语义 | Ctrl+C 时停止前后端子进程；默认 `docker compose down` 连容器一起停；`-KeepDocker` 开关可保留容器 |
| 容错策略 | Docker 启动失败（daemon 未运行 / 镜像缺失）→ 黄色告警「检索服务未启动，知识库将降级」→ 继续启动前后端（与 PRD「缺失时降级不阻塞核心对话」一致） |
| 技术约束 | PowerShell 5 兼容（无 `??`、无三元运算符）；不新增依赖；子进程日志透传当前控制台 |

## 脚本流程

1. **前置检查**：`.venv\Scripts\python.exe` 与 `web\node_modules` 存在性。缺失 → 红色错误 + 安装提示 → 退出（硬依赖）。
2. **Docker 阶段**：项目根执行 `docker compose up -d`。失败 → `[WARN]` 提示后**继续**（不退出）。
3. **健康汇总**：探测 6333 / 9200 / 8081，打印 `UP/DOWN` 列表（DOWN 仅提示，不阻断）。
4. **后端**：`Start-Process -PassThru` 启动 venv `uvicorn app.main:app --host 127.0.0.1 --port 8000`，记录 PID，日志透传。
5. **前端**：cwd `web` 启动 `npm run dev`，记录 PID，日志透传。
6. **就绪轮询**：后端 `/health`（≤30s）、前端 5173（≤30s）；就绪后打印访问地址 `http://localhost:5173/`；探测失败仅告警并继续。
7. **Ctrl+C 清理**：注册 `[Console]::CancelKeyPress` →
   - `Stop-Process` 前端 / 后端子进程（幂等，容错忽略不存在 PID）
   - 默认 `docker compose down`；若 `-KeepDocker` 则跳过 down
   - 退出码 0

## 参数

| 参数 | 默认 | 说明 |
|---|---|---|
| `-SkipDocker` | 关 | 跳过 Docker 阶段与健康探测（第 2、3 步；无 Docker 环境 / 仅调试前后端） |
| `-KeepDocker` | 关 | 退出时保留 Docker 容器（下次启动更快，无需重新拉 ES/TEI） |
| `-Port` | 8000 | 后端端口，透传 `PORT` 环境变量（与 `web/vite.config.ts` 的 `API_PORT` 呼应） |

## 错误处理

- Docker 失败：告警降级，不退出（与决策一致）。
- 子进程启动失败（venv 缺失 / npm 失败）：红色错误，进入清理流程后退出 1。
- 探测超时：仅告警，不退出；访问地址仍打印（用户可手动刷新）。
- 所有清理操作幂等：`Stop-Process` 捕获「进程不存在」、`docker compose down` 捕获「容器不存在」。

## 验证方式

1. **Docker 正常路径**：`.\dev.ps1` → 三端口 UP、后端 `/health` ok、前端 200、访问地址正常打印；Ctrl+C 后 `docker compose ps` 为空（容器已停）。
2. **降级路径**：`.\dev.ps1 -SkipDocker`（或 Docker daemon 关闭）→ 前后端照常启动、`[WARN]` 告警出现、Ctrl+C 后无容器操作报错。
3. **保留容器路径**：`.\dev.ps1 -KeepDocker` → Ctrl+C 后 `docker compose ps` 容器仍在。

## 范围外（YAGNI）

- 不做跨平台（Linux/macOS 脚本）；本项目为单机 Windows 本地部署。
- 不做 Docker Desktop 自动拉起（GUI 应用，脚本不代劳）。
- 不接入 root package.json / concurrently（避免侵入前端工程）。
- 不新增依赖（仅 PowerShell 原生 + 现有 docker/venv/npm）。
