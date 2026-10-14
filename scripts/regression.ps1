<#
.SYNOPSIS
    智银 Agent 演示前回归保险（doc 05 §3.4 冻结规格，M4#1）。

.DESCRIPTION
    演示前最后一道保险，一键回放自动化验收套件并汇总绿/红报告：
      1. 确保 bank-core:8100 与 agent-service:8200 在线（不在线则启动并等待就绪）；
      2. bank-core pytest（预期 22 项，conftest 临时库隔离，任意库态可过）；
      3. 重置 bank 演示库（停 8100 → 删 bank.db* → 重启 bank-core → 就绪轮询）——令 agent
         E2E 套件在干净的"当日累计"状态下确定性全绿，同日可重复执行；
      4. agent-service pytest（预期 134 项，含渗透 66/66）；
      5. scripts/m3_im_smoke.py 实连冒烟（IM 降级通道转账确认全流程，自适应黄/红）；
      6. 汇总输出每套通过数/失败数，失败时列失败用例名；
      7. 退出码：全部通过 0，任一失败 1。

.NOTES
    PowerShell 5.1 兼容（不使用 ?? / ?. 等 7+ 语法）；文件以 UTF-8 with BOM 保存防中文乱码。
    沙箱代理会劫持本机 HTTP 请求，所有探测均显式禁用代理（$req.Proxy = $null）。
    agent-service 的 E2E 测试（test_m1_e2e / test_m3_transcripts）按设计写真实 bank 演示库；
    若不在 agent 套件前重置 bank 库，同日重复执行会因"当日累计转账 > ¥1,000 升红"导致
    test_flow_yellow_confirm 误报失败——第 3 步重置是同日可重复执行的关键。
    agent-service(8200) 全程不重启：其 pytest 库由 conftest（AGENT_DB_PATH 临时目录）隔离。
    回归执行后演示库仍含测试流水，正式演示前须再跑 scripts/reset_demo.ps1 重置数据。
    用法：powershell -ExecutionPolicy Bypass -File scripts/regression.ps1
#>
[CmdletBinding()]
param(
    # 单服务就绪轮询超时（秒）
    [int]$ReadyTimeoutSec = 30
)

Set-StrictMode -Version 2.0
# 注意：不能用 "Stop"——原生命令（pytest/python/git）经 2>&1 合并的 stderr 行会被提升为
# 终止性错误中断整个脚本；改为 "Continue"，关键路径各自 try/catch 兜底
$ErrorActionPreference = "Continue"

# 子进程（python/pytest/冒烟脚本）stdout 为 UTF-8 字节流；PS 5.1 默认按 OEM 代码页（936）
# 解码中文会乱码，这里把"父进程解码编码"与"子进程输出编码"统一为 UTF-8
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$env:PYTHONIOENCODING = "utf-8"

# ── 路径与端口常量 ──────────────────────────────────────────────────────────
$RepoRoot = Split-Path -Parent $PSScriptRoot          # scripts/ 的上一级即仓库根
# managed python venv（Windows venv 布局：Scripts/ 而非 bin/；Python 3.13.14）
$PythonExe = "C:/Users/14181/.workbuddy/binaries/python/envs/default/Scripts/python.exe"
$BankCoreDir = Join-Path $RepoRoot "bank-core"
$AgentSvcDir = Join-Path $RepoRoot "agent-service"

$BankCoreUrl = "http://127.0.0.1:8100"
$AgentSvcUrl = "http://127.0.0.1:8200"

# doc 08 验收报告实测基线（回归套件扩容时同步更新）
$ExpectedBankCore = 22
$ExpectedAgentSvc = 134

# ── 输出辅助 ────────────────────────────────────────────────────────────────

function Write-Step([string]$Text) {
    Write-Host "`n==> $Text" -ForegroundColor Cyan
}

function Write-Ok([string]$Text) {
    Write-Host "  [OK] $Text" -ForegroundColor Green
}

function Write-Bad([string]$Text) {
    Write-Host "  [FAIL] $Text" -ForegroundColor Red
}

# ── 服务就绪保障 ───────────────────────────────────────────────────────────

function Test-Endpoint([string]$Url, [int]$TimeoutMs) {
    # HttpWebRequest + Proxy=$null：绕过沙箱代理对本机请求的劫持
    try {
        $req = [System.Net.HttpWebRequest]::Create($Url)
        $req.Method = "GET"
        $req.Timeout = $TimeoutMs
        $req.Proxy = $null
        $resp = $req.GetResponse()
        $resp.Close()
        return $true
    } catch {
        return $false
    }
}

function Ensure-ServiceReady([string]$Name, [string]$WorkDir, [int]$Port, [string]$HealthUrl) {
    if (Test-Endpoint -Url $HealthUrl -TimeoutMs 2000) {
        Write-Ok "$Name 已在线（:$Port）"
        return $true
    }
    if (-not (Test-Path -LiteralPath $PythonExe)) {
        Write-Bad "managed python 不存在：$PythonExe"
        return $false
    }
    Write-Host "  - $Name 未在线，启动中（uvicorn app.main:app --port $Port）"
    $uvicornArgs = @("-m", "uvicorn", "app.main:app", "--port", "$Port")
    Start-Process -FilePath $PythonExe -ArgumentList $uvicornArgs `
        -WorkingDirectory $WorkDir -WindowStyle Normal

    $deadline = (Get-Date).AddSeconds($ReadyTimeoutSec)
    while ((Get-Date) -lt $deadline) {
        if (Test-Endpoint -Url $HealthUrl -TimeoutMs 2000) {
            Write-Ok "$Name 启动并就绪（:$Port）"
            return $true
        }
        Start-Sleep -Milliseconds 500
    }
    Write-Bad "$Name 等待超时（${ReadyTimeoutSec}s）：$HealthUrl"
    return $false
}

# ── pytest 套件执行与解析 ──────────────────────────────────────────────────

function Invoke-PytestSuite {
    param(
        [string]$Name,
        [string]$WorkDir,
        [int]$Expected
    )
    Write-Host "  - 执行：$PythonExe -m pytest tests -q -rf --tb=no（cwd=$WorkDir）"
    $psiArgs = @("-m", "pytest", "tests", "-q", "-rf", "--tb=no")
    # 2>&1 合并 stderr；Out-String 整体捕获后再逐行解析（PS 5.1 原生命令重定向安全写法）
    $raw = ""
    $exitCode = -1
    try {
        Push-Location $WorkDir
        $raw = & $PythonExe $psiArgs 2>&1 | Out-String
        $exitCode = $LASTEXITCODE
    } catch {
        $raw = "pytest 启动异常：$($_.Exception.Message)"
        $exitCode = -1
    } finally {
        Pop-Location
    }
    Write-Host $raw

    $passed = 0; $failed = 0; $errors = 0
    $m = [regex]::Match($raw, "(\d+) passed")
    if ($m.Success) { $passed = [int]$m.Groups[1].Value }
    $m = [regex]::Match($raw, "(\d+) failed")
    if ($m.Success) { $failed = [int]$m.Groups[1].Value }
    $m = [regex]::Match($raw, "(\d+) error")
    if ($m.Success) { $errors = [int]$m.Groups[1].Value }

    # 失败用例名：short test summary info 段的 FAILED 行（-rf 输出）
    $failedCases = @()
    foreach ($mm in [regex]::Matches($raw, "(?m)^FAILED\s+(\S+)")) {
        $failedCases += $mm.Groups[1].Value
    }

    $suiteOk = ($exitCode -eq 0)
    $status = if ($suiteOk) { "PASS" } else { "FAIL" }
    $color = if ($suiteOk) { "Green" } else { "Red" }
    Write-Host ("  [{0}] {1}：{2} passed / {3} failed / {4} error（预期 {5}，pytest 退出码 {6}）" -f `
        $status, $Name, $passed, $failed, $errors, $Expected, $exitCode) -ForegroundColor $color
    if (-not $suiteOk -and $passed -ne $Expected) {
        Write-Host "  [NOTE] 通过数与预期 $Expected 不一致，请确认套件是否有扩容/裁剪" -ForegroundColor Yellow
    }
    foreach ($case in $failedCases) {
        Write-Host "    - 失败用例：$case" -ForegroundColor Red
    }

    # 返回结构化结果（PS 5.1 用 PSCustomObject）
    return New-Object PSObject -Property @{
        Name       = $Name
        Ok         = $suiteOk
        Passed     = $passed
        Failed     = $failed
        Errors     = $errors
        Expected   = $Expected
        ExitCode   = $exitCode
        FailedCases = $failedCases
    }
}

# ── 渗透报告防污：agent pytest 会重写报告时间戳，跑完还原（QA 报告 §2.4 口径） ──

function Restore-PentestReport {
    $reportDir = Join-Path $AgentSvcDir "tests\security\report"
    Push-Location $RepoRoot
    try {
        $dirty = & git status --porcelain -- $reportDir 2>&1
        if ($dirty) {
            & git checkout -- $reportDir 2>&1 | Out-Null
            Write-Host "  - 渗透报告时间戳已被 pytest 重写，已 git checkout 还原（内容其余不变）"
        }
    } catch {
        Write-Host "  - [NOTE] 渗透报告还原跳过：$($_.Exception.Message)"
    } finally {
        Pop-Location
    }
}

# ── bank 演示库重置（同日重复执行的确定性保障） ──────────────────────────────

function Stop-PortProcesses([int[]]$Ports) {
    foreach ($port in $Ports) {
        $conns = @(Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue)
        if ($conns.Count -eq 0) {
            Write-Host "  - 端口 $port 无监听进程，跳过"
            continue
        }
        $procIds = $conns | Select-Object -ExpandProperty OwningProcess -Unique
        foreach ($procId in $procIds) {
            try {
                $proc = Get-Process -Id $procId -ErrorAction SilentlyContinue
                if ($proc -eq $null) { continue }
                Write-Host "  - 停止端口 $port 进程 PID=$procId ($($proc.ProcessName))"
                Stop-Process -Id $procId -Force -ErrorAction SilentlyContinue
            } catch {
                # 容错：进程已退出/无权限时跳过，不阻断流程
                Write-Host "  - 停止 PID=$procId 失败（容错跳过）：$($_.Exception.Message)"
            }
        }
    }
    # 等待端口释放（TIME_WAIT 清理），避免重启绑定冲突
    Start-Sleep -Milliseconds 800
}

function Reset-BankDemoDatabase {
    param([int]$ReadyTimeoutSec = 30)
    # ① 停 8100 端口进程（uvicorn 持有 bank.db，必须先停后删）
    Stop-PortProcesses -Ports @(8100)

    # ② 删 bank.db*（含 -wal/-shm；bank-core 下次启动自动建表 + 幂等种子）
    $dbFile = Join-Path $BankCoreDir "data\bank.db"
    $deleted = 0
    $files = @(Get-ChildItem -Path "$dbFile*" -ErrorAction SilentlyContinue)
    foreach ($f in $files) {
        try {
            Remove-Item -LiteralPath $f.FullName -Force -ErrorAction SilentlyContinue
            Write-Host "  - 已删除 $($f.Name)"
            $deleted++
        } catch {
            Write-Host "  - 删除 $($f.Name) 失败（容错跳过）：$($_.Exception.Message)"
        }
    }
    if ($deleted -eq 0) {
        Write-Host "  - bank.db 不存在，跳过删除"
    }

    # ③ 重启 bank-core（agent-service:8200 不重启——其测试库由 conftest 隔离）
    if (-not (Test-Path -LiteralPath $PythonExe)) {
        throw "managed python 不存在：$PythonExe"
    }
    Write-Host "  - 重启 bank-core（uvicorn app.main:app --port 8100）"
    $uvicornArgs = @("-m", "uvicorn", "app.main:app", "--port", "8100")
    Start-Process -FilePath $PythonExe -ArgumentList $uvicornArgs `
        -WorkingDirectory $BankCoreDir -WindowStyle Normal

    # ④ 轮询就绪（GET /api/accounts 可返回即种子数据已写入）
    $deadline = (Get-Date).AddSeconds($ReadyTimeoutSec)
    while ((Get-Date) -lt $deadline) {
        if (Test-Endpoint -Url "$BankCoreUrl/api/accounts" -TimeoutMs 2000) {
            Write-Ok "bank-core 已重置并就绪（fresh seed）"
            return $true
        }
        Start-Sleep -Milliseconds 500
    }
    Write-Bad "bank-core 重置后等待超时（${ReadyTimeoutSec}s）：$BankCoreUrl/api/accounts"
    return $false
}

# ── 主流程 ─────────────────────────────────────────────────────────────────

$results = @()

Write-Step "步骤 1/5：确保两服务在线"
$bankOk = Ensure-ServiceReady -Name "bank-core" -WorkDir $BankCoreDir -Port 8100 -HealthUrl "$BankCoreUrl/health"
$agentOk = Ensure-ServiceReady -Name "agent-service" -WorkDir $AgentSvcDir -Port 8200 -HealthUrl "$AgentSvcUrl/health"
if (-not $bankOk -or -not $agentOk) {
    Write-Bad "两服务未就绪，回归终止（请查看新开窗口中的 uvicorn 日志排查）"
    exit 1
}

Write-Step "步骤 2/5：bank-core pytest（预期 $ExpectedBankCore 项）"
$results += Invoke-PytestSuite -Name "bank-core pytest" -WorkDir $BankCoreDir -Expected $ExpectedBankCore

Write-Step "步骤 3/5：重置 bank 演示库（保障同日重复执行的确定性）"
$bankResetOk = $false
try {
    $bankResetOk = Reset-BankDemoDatabase -ReadyTimeoutSec $ReadyTimeoutSec
} catch {
    Write-Bad "bank 演示库重置异常：$($_.Exception.Message)"
}
if (-not $bankResetOk) {
    Write-Bad "bank 演示库重置失败，回归终止（agent E2E 套件依赖干净的当日累计状态）"
    exit 1
}

Write-Step "步骤 4/5：agent-service pytest（预期 $ExpectedAgentSvc 项，含渗透 66/66）"
$results += Invoke-PytestSuite -Name "agent-service pytest" -WorkDir $AgentSvcDir -Expected $ExpectedAgentSvc
Restore-PentestReport

Write-Step "步骤 5/5：IM 通道实连冒烟（scripts/m3_im_smoke.py）"
$smokeOk = $false
try {
    # agent-service 部署标准端口 8200，通过环境变量告知冒烟脚本
    $env:AGENT_URL = $AgentSvcUrl
    $env:BANK_URL = $BankCoreUrl
    $smokeOut = & $PythonExe (Join-Path $RepoRoot "scripts\m3_im_smoke.py") 2>&1 | Out-String
    Write-Host $smokeOut
    if ($LASTEXITCODE -eq 0) {
        $smokeOk = $true
        Write-Ok "IM 冒烟通过（确认卡 + 回执 + 审计回放）"
    } else {
        Write-Bad "IM 冒烟失败（退出码 $LASTEXITCODE）"
    }
} catch {
    Write-Bad "IM 冒烟执行异常：$($_.Exception.Message)"
}
$results += New-Object PSObject -Property @{
    Name = "IM 冒烟（实连）"; Ok = $smokeOk; Passed = 0; Failed = 0; Errors = 0
    Expected = 1; ExitCode = $(if ($smokeOk) { 0 } else { 1 }); FailedCases = @()
}

# ── 汇总报告 ───────────────────────────────────────────────────────────────

Write-Step "回归汇总报告"
$allOk = $true
foreach ($r in $results) {
    $mark = if ($r.Ok) { "✅ PASS" } else { "❌ FAIL" }
    if (-not $r.Ok) { $allOk = $false }
    if ($r.Name -like "*pytest*") {
        Write-Host ("  {0}  {1}：{2} passed / {3} failed / {4} error（预期 {5}）" -f `
            $mark, $r.Name, $r.Passed, $r.Failed, $r.Errors, $r.Expected)
    } else {
        Write-Host ("  {0}  {1}" -f $mark, $r.Name)
    }
    foreach ($case in $r.FailedCases) {
        Write-Host "      - 失败用例：$case" -ForegroundColor Red
    }
}

if ($allOk) {
    Write-Host "`n回归全绿：3/3 套件通过，可以上台演示。" -ForegroundColor Green
    Write-Host "提醒：回归执行后演示库含测试流水（agent E2E 六场景 + IM 冒烟），正式演示前请执行 scripts/reset_demo.ps1 重置演示数据。" -ForegroundColor Yellow
    exit 0
} else {
    Write-Host "`n回归存在失败项，请按上方失败用例修复后再演示。" -ForegroundColor Red
    exit 1
}
