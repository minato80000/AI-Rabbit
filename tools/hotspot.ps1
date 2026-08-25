<#
.SYNOPSIS
    Windows のモバイルホットスポットを操作する（transport.link: hotspot 用）。

.DESCRIPTION
    WiFi ルータなしで PC とロボットを繋ぐとき、PC 自身を親機にする方法です。
    PC のインターネット接続は保たれるので、開発中はこれが一番楽です。

    PC の IP は **必ず 192.168.137.1** になります。ホットスポットは
    Windows の共有アダプタを使い、そのアドレスが固定されているためです。
    つまり ipconfig で調べてファームに書き直す作業が要りません。

    ルータもインターネットも無い場所へ持ち出すなら、ロボット自身を親機に
    する robot-ap を使ってください（docs/wireless-link.md）。

.PARAMETER Action
    Status    いまの状態と、secrets.local.h に書く値を表示する（既定）
    Start     ホットスポットを入れる
    Stop      ホットスポットを切る
    Band24    帯域を 2.4GHz に固定する（CoreS3 は 5GHz を受けられない）
    Firewall  受信ポートを開ける（**管理者権限が必要**）

.PARAMETER Port
    ファイアウォールで開けるポート。pc/config.yaml の transport.port と揃える

.EXAMPLE
    .\tools\hotspot.ps1
    .\tools\hotspot.ps1 -Action Start
    .\tools\hotspot.ps1 -Action Firewall     # 管理者の PowerShell で1回だけ

.NOTES
    Windows のモバイルホットスポットは「共有するインターネット接続」を
    必要とします。PC 自身がネットに繋がっていないと入れられません。
    その状況では robot-ap に切り替えてください。
#>
[CmdletBinding()]
param(
    [ValidateSet('Status', 'Start', 'Stop', 'Band24', 'Firewall')]
    [string]$Action = 'Status',

    [int]$Port = 8765
)

$ErrorActionPreference = 'Stop'

# ホットスポットの PC 側アドレス。Windows の共有アダプタが常にこれを使う
$HotspotIp = '192.168.137.1'
$FirewallRuleName = "AI-Rabbit CoreS3 (TCP $Port)"

# --- WinRT を Windows PowerShell から叩くための下ごしらえ -------------------
# WinRT の非同期メソッドは .NET の Task に変換しないと待てない
Add-Type -AssemblyName System.Runtime.WindowsRuntime | Out-Null

$asTaskGeneric = ([System.WindowsRuntimeSystemExtensions].GetMethods() | Where-Object {
        $_.Name -eq 'AsTask' -and
        $_.GetParameters().Count -eq 1 -and
        $_.GetParameters()[0].ParameterType.Name -eq 'IAsyncOperation`1'
    })[0]

function Wait-WinRt {
    param($Operation, $ResultType)
    $asTask = $asTaskGeneric.MakeGenericMethod($ResultType)
    $task = $asTask.Invoke($null, @($Operation))
    $task.Wait(-1) | Out-Null
    return $task.Result
}

# 結果を返さない非同期（IAsyncAction）用。上とは AsTask のオーバーロードが違う
$asTaskAction = ([System.WindowsRuntimeSystemExtensions].GetMethods() | Where-Object {
        $_.Name -eq 'AsTask' -and
        $_.GetParameters().Count -eq 1 -and
        $_.GetParameters()[0].ParameterType.Name -eq 'IAsyncAction'
    })[0]

function Wait-WinRtAction {
    param($Action)
    # パイプで渡すと PSObject に包まれて型変換に失敗するので、剥がしてから渡す
    if ($Action -is [System.Management.Automation.PSObject]) { $Action = $Action.BaseObject }
    $task = $asTaskAction.Invoke($null, @($Action))
    $task.Wait(-1) | Out-Null
}

function Get-TetheringManager {
    [void][Windows.Networking.Connectivity.NetworkInformation, Windows.Networking.Connectivity, ContentType = WindowsRuntime]
    [void][Windows.Networking.NetworkOperators.NetworkOperatorTetheringManager, Windows.Networking.NetworkOperators, ContentType = WindowsRuntime]

    $connection = [Windows.Networking.Connectivity.NetworkInformation]::GetInternetConnectionProfile()
    if ($null -eq $connection) {
        Write-Host ''
        Write-Host '  この PC に「共有できるインターネット接続」がありません。' -ForegroundColor Yellow
        Write-Host '  Windows のモバイルホットスポットは、共有する接続がないと入れられません。'
        Write-Host ''
        Write-Host '  対処は2つです:'
        Write-Host '    1. PC を WiFi か有線でネットに繋いでから、もう一度実行する'
        Write-Host '    2. ロボット自身を親機にする（ルータもネットも要りません）'
        Write-Host '         pc/config.yaml       transport.link: "robot-ap"'
        Write-Host '         firmware             pio run -e robot-ap -t upload'
        Write-Host '       詳しくは docs/wireless-link.md'
        Write-Host ''
        return $null
    }
    return [Windows.Networking.NetworkOperators.NetworkOperatorTetheringManager]::CreateFromConnectionProfile($connection)
}

function Show-Status {
    param($Manager)

    $state = $Manager.TetheringOperationalState
    Write-Host ''
    if ($state -eq 'On') {
        Write-Host "  ホットスポット: オン（接続中の機器 $($Manager.ClientCount) 台）" -ForegroundColor Green
    }
    else {
        Write-Host "  ホットスポット: $state" -ForegroundColor Yellow
        if ($state -eq 'Off') {
            # 繋がる機器が無い状態が続くと Windows が勝手に切る。
            # ロボットを焼き替えている間に切れて「戻ってこない」ことがある
            Write-Host '    -Action Start で入ります。'
            Write-Host '    機器が繋がっていないと Windows が自動で切るので、毎回困るなら'
            Write-Host '    設定 > モバイル ホットスポット の「電力を節約する」をオフに。'
        }
    }

    $ap = $Manager.GetCurrentAccessPointConfiguration()
    Write-Host ''
    Write-Host '  firmware/src/secrets.local.h に書く値:'
    Write-Host ''
    Write-Host ('    #define WIFI_SSID     "{0}"' -f $ap.Ssid)
    Write-Host ('    #define WIFI_PASSWORD "{0}"' -f $ap.Passphrase)
    Write-Host ''

    # CoreS3（ESP32-S3）の WiFi は 2.4GHz しか受けられない。5GHz で立てると
    # SSID がそもそも見えず、「設定は合っているのに繋がらない」になる。
    # Band は Windows 10 2004 以降にしか無いので、無くても止めない
    $band = $null
    try { $band = $ap.Band } catch { }
    if ($null -ne $band) {
        if ($band -eq 'TwoPointFourGigahertz') {
            Write-Host "  帯域: $band" -ForegroundColor Green
        }
        else {
            Write-Host "  帯域: $band" -ForegroundColor Yellow
            Write-Host '    CoreS3 は 2.4GHz しか受けられません。5GHz で立っていると'
            Write-Host '    SSID が見えず、設定が正しくても繋がりません。'
            Write-Host '    設定 > ネットワークとインターネット > モバイル ホットスポット'
            Write-Host '    の「使用する帯域」を 2.4 GHz にしてください。'
        }
        Write-Host ''
    }
    Write-Host "  PC_HOST は書かなくて構いません（既定が $HotspotIp で、"
    Write-Host '  ホットスポットのアドレスは常にこの値です）。'

    # 実際にそのアドレスが生えているか見る。オンでも出るまで数秒かかる
    $ip = Get-NetIPAddress -AddressFamily IPv4 -ErrorAction SilentlyContinue |
        Where-Object { $_.IPAddress -eq $HotspotIp }
    Write-Host ''
    if ($ip) {
        Write-Host "  $HotspotIp : あり（$($ip.InterfaceAlias)）" -ForegroundColor Green
    }
    else {
        Write-Host "  $HotspotIp : まだ生えていません" -ForegroundColor Yellow
    }

    $rule = Get-NetFirewallRule -DisplayName $FirewallRuleName -ErrorAction SilentlyContinue
    if ($rule -and $rule.Enabled -eq 'True') {
        Write-Host "  受信ポート $Port : 開いています" -ForegroundColor Green
    }
    else {
        # 実測（2026-08-25）では規則なしで繋がった。ホットスポットの仮想
        # アダプタには接続プロファイルが無く、プロファイル別の受信ブロックが
        # 当たらないため。まず何もせず試して、駄目なときだけ開ける
        Write-Host "  受信ポート $Port : 規則はありません（たいてい不要）"
        Write-Host '    ロボットは AP に繋がっているのに WebSocket が繋がらない、'
        Write-Host '    という状態のときだけ、管理者の PowerShell で:'
        Write-Host '      .\tools\hotspot.ps1 -Action Firewall'
    }
    Write-Host ''
}

function Set-Tethering {
    param($Manager, [bool]$On)

    $state = $Manager.TetheringOperationalState
    if ($On -and $state -eq 'On') {
        Write-Host '  すでにオンです。'
        return
    }
    if ((-not $On) -and $state -eq 'Off') {
        Write-Host '  すでにオフです。'
        return
    }

    $resultType = [Windows.Networking.NetworkOperators.NetworkOperatorTetheringOperationResult]
    if ($On) {
        Write-Host '  ホットスポットを入れています...'
        $result = Wait-WinRt $Manager.StartTetheringAsync() $resultType
    }
    else {
        Write-Host '  ホットスポットを切っています...'
        $result = Wait-WinRt $Manager.StopTetheringAsync() $resultType
    }

    if ($result.Status -eq 'Success') {
        Write-Host '  OK' -ForegroundColor Green
    }
    else {
        Write-Host "  失敗: $($result.Status) $($result.AdditionalErrorMessage)" -ForegroundColor Red
    }
}

function Set-Band24 {
    param($Manager)

    $ap = $Manager.GetCurrentAccessPointConfiguration()
    $target = [Windows.Networking.NetworkOperators.TetheringWiFiBand]::TwoPointFourGigahertz
    $before = $ap.Band

    # IsBandSupported はマネージャではなく AP 設定側にある
    if (-not $ap.IsBandSupported($target)) {
        Write-Host '  この PC のアダプタは 2.4GHz のホットスポットに対応していません。' -ForegroundColor Red
        Write-Host '  CoreS3 は 5GHz を受けられないので、robot-ap に切り替えてください。'
        return
    }
    if ($before -eq $target) {
        Write-Host '  すでに 2.4GHz です。'
        return
    }

    $ap.Band = $target
    # ConfigureAccessPointAsync は IAsyncAction（結果なし）
    Wait-WinRtAction ($Manager.ConfigureAccessPointAsync($ap))

    $now = $Manager.GetCurrentAccessPointConfiguration().Band
    if ($now -eq $target) {
        Write-Host "  帯域を 2.4GHz に固定しました（元: $before）" -ForegroundColor Green
    }
    else {
        Write-Host "  変更できませんでした（いまは $now）" -ForegroundColor Red
    }
}

function Add-FirewallRule {
    $isAdmin = ([Security.Principal.WindowsPrincipal] [Security.Principal.WindowsIdentity]::GetCurrent()
        ).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
    if (-not $isAdmin) {
        Write-Host ''
        Write-Host '  管理者権限が要ります。PowerShell を「管理者として実行」で開き直してください。' -ForegroundColor Yellow
        Write-Host ''
        return
    }

    $existing = Get-NetFirewallRule -DisplayName $FirewallRuleName -ErrorAction SilentlyContinue
    if ($existing) {
        Enable-NetFirewallRule -DisplayName $FirewallRuleName
        Write-Host "  規則はすでにあります（有効にしました）: $FirewallRuleName" -ForegroundColor Green
        return
    }

    New-NetFirewallRule -DisplayName $FirewallRuleName `
        -Description 'ウサちゃんロボ CoreS3 からの WebSocket 接続を受ける' `
        -Direction Inbound -Action Allow -Protocol TCP -LocalPort $Port -Profile Any | Out-Null
    Write-Host "  受信ポート $Port を開けました: $FirewallRuleName" -ForegroundColor Green
}

# --- 本体 -------------------------------------------------------------------
if ($Action -eq 'Firewall') {
    Add-FirewallRule
    return
}

$manager = Get-TetheringManager
if ($null -eq $manager) { return }

switch ($Action) {
    'Start' { Set-Tethering $manager $true; Show-Status $manager }
    'Stop' { Set-Tethering $manager $false }
    'Band24' { Set-Band24 $manager; Show-Status $manager }
    'Status' { Show-Status $manager }
}
