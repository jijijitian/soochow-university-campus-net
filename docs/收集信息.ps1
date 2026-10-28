# 一键收集启动问题信息
#
# 用法（在解压目录里）：
#   右键本文件 →「使用 PowerShell 运行」
#   或在 PowerShell 里执行：
#     powershell -NoProfile -ExecutionPolicy Bypass -File .\收集信息.ps1
#
# 执行完会在本目录生成「诊断报告.txt」，请把这个文件发给开发者。

$ErrorActionPreference = 'SilentlyContinue'
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$out = Join-Path $here '诊断报告.txt'
Set-Content -LiteralPath $out -Value '' -Encoding UTF8

function Line($text) { Add-Content -LiteralPath $out -Value ([string]$text) -Encoding UTF8 }
function Section($title) {
    Line ''
    Line ('=' * 60)
    Line $title
    Line ('=' * 60)
}

Section '一、基本环境'
Line ("时间          : " + (Get-Date -Format 'yyyy-MM-dd HH:mm:ss'))
Line ("系统          : " + (Get-CimInstance Win32_OperatingSystem).Caption)
Line ("版本号        : " + [System.Environment]::OSVersion.Version)
Line ("架构          : " + $env:PROCESSOR_ARCHITECTURE)
Line ("PowerShell    : " + $PSVersionTable.PSVersion)
Line ("解压目录      : " + $here)
Line ("用户名        : " + $env:USERNAME)
Line ("OneDrive 路径 : " + ($here -like '*OneDrive*'))
Line ("含中文路径    : " + ($here -match '[^\x00-\x7F]'))

$exe = Join-Path $here '校园网自动登录.exe'

Section '二、文件完整性'
Line ("exe 存在      : " + (Test-Path $exe))
if (Test-Path $exe) {
    $info = Get-Item $exe
    Line ("exe 大小      : " + [math]::Round($info.Length / 1MB, 2) + ' MB')
    Line ("exe 版本      : " + $info.VersionInfo.FileVersion)
    Line ("exe 完整路径  : " + $info.FullName)

    $bytes = [System.IO.File]::ReadAllBytes($exe)
    $peOffset = [BitConverter]::ToInt32($bytes, 0x3C)
    $subsystem = [BitConverter]::ToUInt16($bytes, $peOffset + 24 + 68)
    Line ("PE 子系统     : $subsystem   (2=GUI 无黑框, 3=Console 有黑框)")
}

$internal = Join-Path $here '_internal'
Line ("_internal     : " + (Test-Path $internal))
if (Test-Path $internal) {
    $files = Get-ChildItem $internal -Recurse -File
    Line ("  文件数      : " + $files.Count)
    Line ("  总大小      : " + [math]::Round((($files | Measure-Object Length -Sum).Sum) / 1MB, 2) + ' MB')
    foreach ($name in @('python313.dll', '_tcl_data', '_tk_data', 'assets')) {
        Line ("  $name : " + (Test-Path (Join-Path $internal $name)))
    }
}

# 配置文件是否存在（v1.0.3 及更早，缺此文件会导致程序直接退出）
$cfg = Join-Path $here 'config.ini'
$cfgExample = Join-Path $here 'config.example.ini'
Line ("config.ini    : " + (Test-Path $cfg))
Line ("  config.example.ini : " + (Test-Path $cfgExample))
if (Test-Path $cfg) {
    $csize = (Get-Item $cfg).Length
    Line ("  config.ini 大小    : " + $csize + ' 字节')
    $cfgText = Get-Content $cfg -Raw -Encoding UTF8 -ErrorAction SilentlyContinue
    if ($cfgText) {
        if ($cfgText -match '(?m)^\s*username\s*=\s*\S+') {
            Line '  账号已填写         : 是'
        } else {
            Line '  账号已填写         : 否（界面里还能再填）'
        }
    }
}

Section '三、来自网络标记（MOTW）'
if (Test-Path $exe) {
    $z = Get-Item $exe -Stream Zone.Identifier -ErrorAction SilentlyContinue
    Line ("exe 带标记    : " + [bool]$z)
}
# 显式枚举全部文件再按扩展名过滤，避免 -Include 配 -Recurse 的边界问题。
# 注意 onedir 包里真正的二进制只有 60 多个（其余是 tcl 脚本、编码表等），
# 所以 60~70 个是正常值，不代表解压不完整。
$marked = 0
$checked = 0
$totalFiles = 0
Get-ChildItem -LiteralPath $here -Recurse -File -ErrorAction SilentlyContinue | ForEach-Object {
    $totalFiles++
    $ext = $_.Extension.ToLower()
    if ($ext -in @('.exe', '.dll', '.pyd')) {
        $checked++
        if (Get-Item $_.FullName -Stream Zone.Identifier -ErrorAction SilentlyContinue) {
            $marked++
        }
    }
}
Line ("目录文件总数  : " + $totalFiles)
Line ("二进制文件数  : " + $checked + "   （60~70 为正常）")
Line ("带标记文件数  : " + $marked)
if ($checked -gt 0 -and $checked -lt 100) {
    Line '（提示：二进制文件数偏少，可能解压不完整）'
}

Section '四、历史日志'
foreach ($f in @('startup-trace.log', 'startup-error.log', 'diagnose.txt', 'logs\auto_login.log')) {
    Line ''
    Line ("--- $f ---")
    $p = Join-Path $here $f
    if (Test-Path $p) {
        Get-Content $p -Encoding UTF8 -Tail 60 | ForEach-Object { Line $_ }
    } else {
        Line '(不存在)'
    }
}

Section '五、启动测试'
if (Test-Path $exe) {
    Line '启动程序，等待 12 秒...'
    $proc = Start-Process -FilePath $exe -WorkingDirectory $here -PassThru
    Start-Sleep -Seconds 12

    if ($proc.HasExited) {
        $code = $proc.ExitCode
        $hex = '0x{0:X8}' -f ($code -band 0xFFFFFFFF)
        Line '进程已退出    : 是'
        Line ("退出码        : $code ($hex)")
        Line ''
        Line '退出码含义参考:'
        Line '  0           正常'
        Line '  1           程序内部错误（看 startup-error.log）'
        Line '  -1073741819  0xC0000005 内存访问冲突'
        Line '  -1073741515  0xC0000135 找不到依赖 DLL'
        Line '  -1073741701  0xC000007B 位数不匹配或 DLL 损坏'
        Line '  -1           0xFFFFFFFF bootloader 失败'
    } else {
        Line '进程已退出    : 否（仍在运行）'
        Line ("PID           : " + $proc.Id)
        $gp = Get-Process -Id $proc.Id -ErrorAction SilentlyContinue
        if ($gp) {
            Line ("窗口标题      : '" + $gp.MainWindowTitle + "'")
            Line ("是否响应      : " + $gp.Responding)
            Line ("线程数        : " + $gp.Threads.Count)
            Line ("内存占用      : " + [math]::Round($gp.WorkingSet64 / 1MB, 1) + ' MB')
            Line ("CPU 累计      : " + [math]::Round($gp.TotalProcessorTime.TotalSeconds, 2) + ' 秒')
        }
        Line ''
        Line '（窗口标题为空 = 没有创建主窗口）'
        Stop-Process -Id $proc.Id -Force -ErrorAction SilentlyContinue
    }

    Start-Sleep -Seconds 2
    Line ''
    Line '--- 启动后的日志 ---'
    foreach ($f in @('startup-trace.log', 'startup-error.log')) {
        Line "--- $f ---"
        $p = Join-Path $here $f
        if (Test-Path $p) {
            Get-Content $p -Encoding UTF8 -Tail 40 | ForEach-Object { Line $_ }
        } else {
            Line '(不存在)'
        }
    }
} else {
    Line '找不到 exe，跳过启动测试'
}

Section '六、安全软件状态'
Line 'Windows Defender:'
$mp = Get-MpComputerStatus -ErrorAction SilentlyContinue
if ($mp) {
    Line ("  实时防护      : " + $mp.RealTimeProtectionEnabled)
    Line ("  防病毒启用    : " + $mp.AntivirusEnabled)
    Line ("  签名版本      : " + $mp.AntivirusSignatureVersion)
} else {
    Line '  (无法获取)'
}

$threats = Get-MpThreatDetection -ErrorAction SilentlyContinue | Select-Object -Last 5
if ($threats) {
    Line '最近的威胁检测:'
    foreach ($t in $threats) {
        Line ("  " + $t.InitialDetectionTime + "  " + ($t.Resources -join '; '))
    }
} else {
    Line '  无威胁检测记录'
}

Line ''
Line '第三方安全软件:'
$avs = Get-CimInstance -Namespace root\SecurityCenter2 -ClassName AntiVirusProduct -ErrorAction SilentlyContinue
if ($avs) {
    foreach ($a in $avs) { Line ("  " + $a.displayName + "  state=" + $a.productState) }
} else {
    Line '  (无)'
}

Line ''
Line '受控文件夹访问:'
Line ("  " + (Get-MpPreference -ErrorAction SilentlyContinue).EnableControlledFolderAccess)

Section '七、智能控制 / SmartScreen'
$sac = (Get-ItemProperty -Path 'HKLM:\SYSTEM\CurrentControlSet\Control\CI\Policy' -ErrorAction SilentlyContinue).VerifiedAndReputablePolicyState
Line ("智能控制状态  : $sac   (0=关闭, 1=强制, 2=评估)")
$ss = (Get-ItemProperty -Path 'HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Explorer' -ErrorAction SilentlyContinue).SmartScreenEnabled
Line ("SmartScreen   : $ss")

Line ''
Line ('=' * 60)
Line '收集完成'
Line ('=' * 60)
Line ("报告文件: " + $out)

Write-Host ''
Write-Host '  收集完成！' -ForegroundColor Green
Write-Host ("  报告文件: " + $out) -ForegroundColor Cyan
Write-Host ''
Write-Host '  请把「诊断报告.txt」发给开发者。' -ForegroundColor Yellow
Write-Host ''
Read-Host '按回车键关闭'
