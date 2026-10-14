<#
.SYNOPSIS
    智银 Agent 演示数据一键重置（doc 05 §3.3 冻结规格，M4#2）。

.DESCRIPTION
    30 秒内恢复演示数据，演示前必跑：
      1. 停止占用 8100/8200 端口的进程（Get-NetTCPConnection 定位，无进程时容错跳过）；
      2. 删除 bank-core/data/bank.db* 与 agent-service/data/agent.db*（含 -wal/-shm，
         删除 agent.db 即清空 audit/pending/mfa/breaker 全部运行时表与 checkpoints）；
      3. 以 managed python 重启两服务（Start-Process 新窗口：bank-core :8100 / agent-service :8200）；
      4. 轮询等待两服务就绪（GET /api/accounts 与 /health，超时 30s）；
      5. 输出演示数据检查清单（余额 ¥52,300 / 通讯录 8 人含两个李磊 / 订阅 / 理财 12 产品）。

.NOTES
    PowerShell 5.1 兼容（不使用 ?? / ?. 等 7+ 语法）；文件以 UTF-8 with BOM 保存防中文乱码。
    沙箱代理会劫持本机 HTTP 请求，所有探测均显式禁用代理（$req.Proxy = $null）。
    用法：powershell -ExecutionPolicy Bypass -File scripts/reset_demo.ps1
#>
[CmdletBinding()]
param(
    # 两服务就绪轮询超时（秒），doc 05 §3.3 规格为 30s
    [int]$ReadyTimeoutSec = 30
)

Set-StrictMode -Version 2.0
$ErrorActionPreference = "Stop"

# ── 路径常量 ────────────────────────────────────────────────────────────────
$RepoRoot = Split-Path -Parent $PSScriptRoot          # scripts/ 的上一级即仓库根
# managed python venv（Windows venv 布局：Scripts/ 而非 bin/；Python 3.13.14）
$PythonExe = "C:/Users/14181/.workbuddy/binaries/python/envs/default/Scripts/python.exe"
$BankCoreDir = Join-Path $RepoRoot "bank-core"
$AgentSvcDir = Join-Path $RepoRoot "agent-service"
$BankDbPath = Join-Path $BankCoreDir "data\bank.db"
$AgentDbPath = Join-Path $AgentSvcDir "data\agent.db"

$BankCoreUrl = "http://127.0.0.1:8100"
$AgentSvcUrl = "http://127.0.0.1:8200"

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

# ── 步骤 1：停止占用指定端口的进程 ─────────────────────────────────────────

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
                # 容错：进程已退出/无权限时跳过，不阻断重置流程
                Write-Host "  - 停止 PID=$procId 失败（容错跳过）：$($_.Exception.Message)"
            }
        }
    }
    # 等待端口释放（TIME_WAIT 清理），避免重启绑定冲突
    Start-Sleep -Milliseconds 800
}

# ── 步骤 2：删除演示数据库（含 -wal/-shm/-journal） ─────────────────────────

function Remove-DemoDatabases {
    $deleted = 0
    foreach ($dbFile in @($BankDbPath, $AgentDbPath)) {
        $pattern = "$dbFile*"
        $files = @(Get-ChildItem -Path $pattern -ErrorAction SilentlyContinue)
        if ($files.Count -eq 0) {
            Write-Host "  - $(Split-Path -Leaf $dbFile) 不存在，跳过"
            continue
        }
        foreach ($f in $files) {
            try {
                Remove-Item -LiteralPath $f.FullName -Force -ErrorAction SilentlyContinue
                Write-Host "  - 已删除 $($f.Name)"
                $deleted++
            } catch {
                Write-Host "  - 删除 $($f.Name) 失败（容错跳过）：$($_.Exception.Message)"
            }
        }
    }
    return $deleted
}

# ── 步骤 3：重启两服务（新窗口） ────────────────────────────────────────────

function Start-DemoServices {
    if (-not (Test-Path -LiteralPath $PythonExe)) {
        throw "managed python 不存在：$PythonExe（请检查 venv 路径）"
    }
    $services = @(
        @{ Name = "bank-core";     Dir = $BankCoreDir; Port = 8100 },
        @{ Name = "agent-service"; Dir = $AgentSvcDir; Port = 8200 }
    )
    foreach ($svc in $services) {
        if (-not (Test-Path -LiteralPath $svc.Dir)) {
            throw "$($svc.Name) 目录不存在：$($svc.Dir)"
        }
        # doc 05 §3.3 口径：uvicorn app.main:app --port <端口>，新窗口独立进程
        $uvicornArgs = @("-m", "uvicorn", "app.main:app", "--port", "$($svc.Port)")
        Write-Host "  - 启动 $($svc.Name)（端口 $($svc.Port)，工作目录 $($svc.Dir)）"
        Start-Process -FilePath $PythonExe -ArgumentList $uvicornArgs `
            -WorkingDirectory $svc.Dir -WindowStyle Normal
    }
}

# ── 步骤 4：轮询等待服务就绪 ───────────────────────────────────────────────

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

function Wait-EndpointReady([string]$Name, [string]$Url, [int]$TimeoutSec) {
    $deadline = (Get-Date).AddSeconds($TimeoutSec)
    while ((Get-Date) -lt $deadline) {
        if (Test-Endpoint -Url $Url -TimeoutMs 2000) {
            Write-Ok "$Name 就绪：$Url"
            return $true
        }
        Start-Sleep -Milliseconds 500
    }
    Write-Bad "$Name 等待超时（${TimeoutSec}s）：$Url"
    return $false
}

# ── 步骤 5：演示数据检查清单 ───────────────────────────────────────────────

function Get-EndpointJson([string]$Url, [int]$TimeoutMs = 5000) {
    $req = [System.Net.HttpWebRequest]::Create($Url)
    $req.Method = "GET"
    $req.Timeout = $TimeoutMs
    $req.Proxy = $null
    $resp = $req.GetResponse()
    $reader = New-Object System.IO.StreamReader($resp.GetResponseStream())
    $text = $reader.ReadToEnd()
    $reader.Close()
    $resp.Close()
    return ConvertFrom-Json $text
}

function Show-DemoChecklist {
    param([string]$BankUrl)
    Write-Step "演示数据检查清单（doc 02 §3.1 演示锚点）"
    $allOk = $true

    # ① 张三活期余额 ¥52,300.00
    try {
        $accounts = Get-EndpointJson -Url "$BankUrl/api/accounts"
        $checking = @($accounts.items | Where-Object { $_.type -eq "checking" } | Select-Object -First 1)
        if ($checking.Count -gt 0 -and [math]::Abs([double]$checking[0].balance - 52300.0) -lt 0.005) {
            Write-Ok ("余额：¥{0:N2}（活期 6222020200006688）" -f [double]$checking[0].balance)
        } else {
            Write-Bad ("余额异常：期望 ¥52,300.00，实际 {0}" -f $checking[0].balance)
            $allOk = $false
        }
    } catch {
        Write-Bad "余额查询失败：$($_.Exception.Message)"
        $allOk = $false
    }

    # ② 通讯录 8 人，含两个李磊（同名消歧演示锚点）
    try {
        $contacts = Get-EndpointJson -Url "$BankUrl/api/contacts"
        $leilei = @($contacts.items | Where-Object { $_.name -eq "李磊" })
        if ($contacts.total -eq 8 -and $leilei.Count -eq 2) {
            Write-Ok ("通讯录：{0} 人，含两个李磊（尾号 {1} / {2}）" -f `
                $contacts.total, $leilei[0].account_no_tail, $leilei[1].account_no_tail)
        } else {
            Write-Bad ("通讯录异常：期望 8 人且李磊×2，实际 {0} 人、李磊×{1}" -f `
                $contacts.total, $leilei.Count)
            $allOk = $false
        }
    } catch {
        Write-Bad "通讯录查询失败：$($_.Exception.Message)"
        $allOk = $false
    }

    # ③ 订阅管理（doc 05 M3#3：识别 5 个订阅，含"遗忘"的云存储）
    try {
        $subs = Get-EndpointJson -Url "$BankUrl/api/subscriptions"
        if ($subs.total -ge 5) {
            Write-Ok ("订阅：{0} 条生效中，月支出约 ¥{1:N2}" -f $subs.total, [double]$subs.monthly_cost)
        } else {
            Write-Bad ("订阅异常：期望 ≥5 条，实际 {0} 条" -f $subs.total)
            $allOk = $false
        }
    } catch {
        Write-Bad "订阅查询失败：$($_.Exception.Message)"
        $allOk = $false
    }

    # ④ 理财 12 产品（doc 03 §9.3：R1×2 / R2×3 / R3×3 / R4×2 / R5×2）
    try {
        $products = Get-EndpointJson -Url "$BankUrl/api/wealth/products"
        if ($products.total -eq 12) {
            Write-Ok ("理财产品：{0} 只（R1-R5 全风险等级）" -f $products.total)
        } else {
            Write-Bad ("理财产品异常：期望 12 只，实际 {0} 只" -f $products.total)
            $allOk = $false
        }
    } catch {
        Write-Bad "理财查询失败：$($_.Exception.Message)"
        $allOk = $false
    }

    return $allOk
}

# ── 主流程 ─────────────────────────────────────────────────────────────────

$sw = [System.Diagnostics.Stopwatch]::StartNew()
$exitCode = 0
try {
    Write-Step "步骤 1/5：停止 8100/8200 端口进程"
    Stop-PortProcesses -Ports @(8100, 8200)

    Write-Step "步骤 2/5：删除演示数据库（bank.db* / agent.db*）"
    $removed = Remove-DemoDatabases
    Write-Host "  - 共删除 $removed 个数据库文件"

    Write-Step "步骤 3/5：重启 bank-core(:8100) 与 agent-service(:8200)"
    Start-DemoServices

    Write-Step "步骤 4/5：等待两服务就绪（超时 ${ReadyTimeoutSec}s）"
    $bankReady = Wait-EndpointReady -Name "bank-core" -Url "$BankCoreUrl/api/accounts" -TimeoutSec $ReadyTimeoutSec
    $agentReady = Wait-EndpointReady -Name "agent-service" -Url "$AgentSvcUrl/health" -TimeoutSec $ReadyTimeoutSec
    if (-not $bankReady -or -not $agentReady) {
        throw "服务启动超时，请查看新开窗口中的 uvicorn 日志排查"
    }

    $checklistOk = Show-DemoChecklist -BankUrl $BankCoreUrl
    if (-not $checklistOk) { $exitCode = 1 }
} catch {
    Write-Bad "重置流程异常：$($_.Exception.Message)"
    $exitCode = 1
}
$sw.Stop()

if ($exitCode -eq 0) {
    Write-Host ("`n演示数据已就绪（耗时 {0:N1}s）。演示入口：web-app `npm run dev` 或 agent-service /demo 页" -f $sw.Elapsed.TotalSeconds) -ForegroundColor Green
} else {
    Write-Host "`n演示数据重置未完成，请按上方 [FAIL] 项排查" -ForegroundColor Red
}
exit $exitCode
