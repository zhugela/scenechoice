# check.ps1 — 一键体检：测试 + 语法 + 静态检查（缺 ruff 时自动跳过）
# 位置：docs/harness/check.ps1。在项目根执行：powershell -File docs/harness/check.ps1
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
Set-Location $root

# 选解释器：优先项目内 .venv
$py = Join-Path $root ".venv\Scripts\python.exe"
if (-not (Test-Path $py)) {
    $py = "python"
}

Write-Host "1/3 pytest..." -ForegroundColor Cyan
& $py -m pytest tests/ -x -q

Write-Host "2/3 语法 (compileall app/)..." -ForegroundColor Cyan
& $py -m compileall -q app
if ($LASTEXITCODE -ne 0) { throw "compileall 失败" }

Write-Host "3/3 ruff..." -ForegroundColor Cyan
& $py -m ruff --version *> $null
if ($LASTEXITCODE -eq 0) {
    & $py -m ruff check app/
    if ($LASTEXITCODE -ne 0) { throw "ruff 发现问题" }
} else {
    Write-Host "    (未安装 ruff，跳过)" -ForegroundColor Yellow
}

Write-Host "OK 全部通过" -ForegroundColor Green
