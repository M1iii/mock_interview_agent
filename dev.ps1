# dev.ps1 - AI 面试官一键启动：Docker 检索容器 + 后端 :8000 + 前端 :5173
# 用法：
#   .\dev.ps1                    # 启动全部；Ctrl+C 时连容器一起停
#   .\dev.ps1 -SkipDocker        # 跳过 Docker（无 Docker 环境/仅调前后端）
#   .\dev.ps1 -KeepDocker        # 退出时保留 Docker 容器
#   .\dev.ps1 -Port 9000         # 后端换端口（前端代理同步）
#   .\dev.ps1 -AutoExitSeconds 20  # 测试钩子：全部就绪后 20s 自动走清理流程退出
[CmdletBinding()]
param(
    [switch]$SkipDocker,
    [switch]$KeepDocker,
    [int]$Port = 8000,
    [int]$AutoExitSeconds = 0
)

$ErrorActionPreference = 'Stop'
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$VenvPython = Join-Path $Root '.venv\Scripts\python.exe'
$WebDir = Join-Path $Root 'web'
$DockerStarted = $false
$script:Stopping = $false
$BackendProcId = $null
$FrontendProcId = $null

function Write-Info([string]$msg) { Write-Host "[INFO] $msg" -ForegroundColor Cyan }
function Write-Warn([string]$msg) { Write-Host "[WARN] $msg" -ForegroundColor Yellow }
function Write-Err([string]$msg) { Write-Host "[ERROR] $msg" -ForegroundColor Red }

function Test-Port([int]$p) {
    return [bool](Get-NetTCPConnection -LocalPort $p -State Listen -ErrorAction SilentlyContinue)
}

function Stop-ChildTree([int]$procId) {
    if (-not $procId) { return }
    # /T 终止进程树（npm 的 cmd -> node 子进程）
    & taskkill.exe /PID $procId /T /F 2>$null | Out-Null
}

function Invoke-Cleanup {
    Write-Info "正在停止服务..."
    Stop-ChildTree $FrontendProcId
    Stop-ChildTree $BackendProcId
    if ($DockerStarted -and -not $KeepDocker) {
        Write-Info "docker compose down（停止检索容器）..."
        Push-Location $Root
        & cmd /c "docker compose down 2>&1" | Out-Null
        Pop-Location
    } elseif ($DockerStarted) {
        Write-Info "保留 Docker 容器（-KeepDocker）"
    }
}

# --- Ctrl+C：取消默认终止，置停止标志，主循环负责清理 ---
# 非交互宿主（CI/工具沙箱）无 CancelKeyPress 事件，注册失败仅告警，不影响启动
try {
    $CtrlHandler = [ConsoleCancelEventHandler]{
        param($sender, $e)
        $script:Stopping = $true
        $e.Cancel = $true
    }
    [Console]::CancelKeyPress += $CtrlHandler
} catch {
    Write-Warn "Ctrl+C 钩子注册失败（非交互宿主）：$_"
}

try {
    # --- 1. 前置检查 ---
    if (-not (Test-Path $VenvPython)) {
        Write-Err "未找到虚拟环境 Python：$VenvPython"
        Write-Err "请先执行：uv sync 或 pip install -r requirements.txt"
        exit 1
    }
    if (-not (Test-Path (Join-Path $WebDir 'node_modules'))) {
        Write-Err "未找到前端依赖：$WebDir\node_modules"
        Write-Err "请先执行：cd web && npm install"
        exit 1
    }

    # --- 2. Docker 阶段（失败降级，不阻塞） ---
    if ($SkipDocker) {
        Write-Info "已跳过 Docker（-SkipDocker）"
    } else {
        Write-Info "docker compose up -d（检索容器）..."
        Push-Location $Root
        # 经 cmd /c 捕获输出，避免 docker stderr 在 EAP=Stop 下被抛为终止异常
        $dockerOut = & cmd /c "docker compose up -d 2>&1"
        $dockerCode = $LASTEXITCODE
        Pop-Location
        if ($dockerCode -eq 0) {
            $DockerStarted = $true
            Write-Info "Docker 检索容器已启动"
        } else {
            Write-Warn "docker compose up -d 失败（退出码 $dockerCode）"
            Write-Warn "检索服务未启动，知识库功能将降级，核心对话不受影响"
            $dockerOut | Select-Object -Last 3 | ForEach-Object { Write-Warn "  $_" }
        }
    }

    # --- 3. 健康汇总（探测 6333/9200/8081） ---
    if (-not $SkipDocker) {
        foreach ($item in @(@{p=6333;n='Qdrant'}, @{p=9200;n='Elasticsearch'}, @{p=8081;n='Embedding(TEI)'})) {
            if (Test-Port $item.p) { Write-Info ("{0} :{1} UP" -f $item.n, $item.p) }
            else { Write-Warn ("{0} :{1} DOWN" -f $item.n, $item.p) }
        }
    }

    # --- 4. 后端 ---
    Write-Info "启动后端（uvicorn :$Port）..."
    $env:PORT = "$Port"
    $BackendProc = Start-Process -FilePath $VenvPython `
        -ArgumentList @('-m', 'uvicorn', 'app.main:app', '--host', '127.0.0.1', '--port', "$Port") `
        -WorkingDirectory $Root -NoNewWindow -PassThru
    $BackendProcId = $BackendProc.Id

    # --- 5. 前端 ---
    Write-Info "启动前端（vite :5173）..."
    $FrontendProc = Start-Process -FilePath 'cmd.exe' `
        -ArgumentList @('/c', 'npm run dev') `
        -WorkingDirectory $WebDir -NoNewWindow -PassThru
    $FrontendProcId = $FrontendProc.Id

    # --- 6. 就绪轮询 ---
    $backendOk = $false
    for ($i = 0; $i -lt 30; $i++) {
        try {
            $h = Invoke-RestMethod -Uri "http://127.0.0.1:$Port/health" -TimeoutSec 2
            if ($h.status -eq 'ok') { $backendOk = $true; break }
        } catch { }
        Start-Sleep -Seconds 1
    }
    if ($backendOk) { Write-Info "后端就绪：http://127.0.0.1:$Port" }
    else { Write-Warn "后端 30s 内未就绪，请手动检查" }

    $frontendOk = $false
    for ($i = 0; $i -lt 30; $i++) {
        if (Test-Port 5173) { $frontendOk = $true; break }
        Start-Sleep -Seconds 1
    }
    if ($frontendOk) { Write-Info "前端就绪：http://localhost:5173/" }
    else { Write-Warn "前端 30s 内未就绪，请手动检查" }

    if ($AutoExitSeconds -gt 0) {
        Write-Info ("自动退出测试钩子：{0}s 后走清理流程（-AutoExitSeconds）" -f $AutoExitSeconds)
        Start-Sleep -Seconds $AutoExitSeconds
        $script:Stopping = $true
    }

    # --- 7. 主等待循环（Ctrl+C 或子进程退出） ---
    Write-Info "全部启动完成。按 Ctrl+C 停止服务。"
    while (-not $script:Stopping) {
        $bAlive = $false; $fAlive = $false
        if ($BackendProcId) { $bAlive = [bool](Get-Process -Id $BackendProcId -ErrorAction SilentlyContinue) }
        if ($FrontendProcId) { $fAlive = [bool](Get-Process -Id $FrontendProcId -ErrorAction SilentlyContinue) }
        if (-not $bAlive -or -not $fAlive) {
            if (-not $bAlive) { Write-Warn "后端进程已退出" }
            if (-not $fAlive) { Write-Warn "前端进程已退出" }
            break
        }
        Start-Sleep -Milliseconds 500
    }
}
catch {
    Write-Err "脚本异常：$_"
    exit 1
}
finally {
    Invoke-Cleanup
}
exit 0
