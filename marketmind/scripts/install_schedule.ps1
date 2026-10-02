# Register MarketMind's scheduled tasks for the current user (docs/AUTOMATION.md).
#   powershell -ExecutionPolicy Bypass -File marketmind\scripts\install_schedule.ps1
# Re-running replaces the tasks. Remove them with uninstall_schedule.ps1.
#
# Tasks (folder \MarketMind\):
#   Daily      three daily triggers at the local times of 12:45, 13:45 and 14:45 UTC
#              (Riyadh 15:45 / 16:45 / 17:45): 08:45 New York in US daylight and
#              standard time, plus a later retry. The Python wrapper decides from the
#              New York clock: not before 08:25 New York, at most two attempts and
#              one completed run per day.
#   Weekend    Saturday and Sunday 12:00 and 14:00 local (the second one retries a
#              failed run): settle + crypto shadows.
#   Watchdog   at logon and on wake from sleep (System log event
#              Microsoft-Windows-Power-Troubleshooter, Event ID 1), 15 minutes later:
#              pushes one notice per missed or failed day; catches up today's run
#              if it was interrupted or failed with an attempt left.
#   Dashboard  at logon: the white-box dashboard on http://127.0.0.1:8520
# Plus a Startup-folder shortcut "MarketMind task check" (ensure_tasks.py): at logon it
# re-runs this script if any of the four tasks is missing.
# All run only while this user is logged on (no stored password). Daily and
# Weekend wake the computer from sleep and catch up after a missed start.
$ErrorActionPreference = "Stop"

$Root = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$Python = (Get-Command python -ErrorAction Stop).Source
$PythonW = Join-Path (Split-Path $Python) "pythonw.exe"
if (-not (Test-Path $PythonW)) { $PythonW = $Python }
$Wrapper = Join-Path $Root "marketmind\scripts\scheduled_run.py"
$Watchdog = Join-Path $Root "marketmind\scripts\watchdog.py"
$Server = Join-Path $Root "marketmind\api_server.py"
$User = "$env:USERDOMAIN\$env:USERNAME"
$Folder = "\MarketMind\"

function LocalTimeOfUtc([int]$h, [int]$m) {
    $utc = [DateTime]::SpecifyKind([DateTime]::UtcNow.Date.AddHours($h).AddMinutes($m), "Utc")
    return [TimeZoneInfo]::ConvertTimeFromUtc($utc, [TimeZoneInfo]::Local)
}

$principal = New-ScheduledTaskPrincipal -UserId $User -LogonType Interactive -RunLevel Limited
# RunOnlyIfNetworkAvailable: a missed trigger waits for a network instead of starting
# (and failing) offline, e.g. after a lid-closed wake (owner, 2026-09-29).
$runSettings = New-ScheduledTaskSettingsSet -WakeToRun -StartWhenAvailable -RunOnlyIfNetworkAvailable `
    -ExecutionTimeLimit (New-TimeSpan -Hours 2) -MultipleInstances IgnoreNew `
    -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries

# Daily pre-open run (+ a later retry for US standard time, when 12:45 UTC is too early)
$daylight = LocalTimeOfUtc 12 45
$standard = LocalTimeOfUtc 13 45
$lateRetry = LocalTimeOfUtc 14 45
$daily = New-ScheduledTaskAction -Execute $PythonW -Argument "`"$Wrapper`" --slot weekday" -WorkingDirectory $Root
Register-ScheduledTask -TaskPath $Folder -TaskName "Daily" -Action $daily -Principal $principal `
    -Settings $runSettings -Force `
    -Trigger @((New-ScheduledTaskTrigger -Daily -At $daylight), (New-ScheduledTaskTrigger -Daily -At $standard),
               (New-ScheduledTaskTrigger -Daily -At $lateRetry)) `
    -Description "MarketMind pre-open run (08:45 New York). Wrapper runs once per day." | Out-Null

# Weekend crypto run
$weekend = New-ScheduledTaskAction -Execute $PythonW -Argument "`"$Wrapper`" --slot weekend" -WorkingDirectory $Root
Register-ScheduledTask -TaskPath $Folder -TaskName "Weekend" -Action $weekend -Principal $principal `
    -Settings $runSettings -Force `
    -Trigger @((New-ScheduledTaskTrigger -Weekly -DaysOfWeek Saturday, Sunday -At "12:00"),
               (New-ScheduledTaskTrigger -Weekly -DaysOfWeek Saturday, Sunday -At "14:00")) `
    -Description "MarketMind weekend: settle ledger + crypto shadows." | Out-Null

# Missed-run watchdog: at logon and on wake from sleep, after a delay so that a
# catch-up run started on wake is already marked running.
# 2 hours: it may catch up today's interrupted run in-process (run timeout 60 minutes).
$wdSettings = New-ScheduledTaskSettingsSet -ExecutionTimeLimit (New-TimeSpan -Hours 2) `
    -MultipleInstances IgnoreNew -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
$atLogon = New-ScheduledTaskTrigger -AtLogOn -User $User
$atLogon.Delay = "PT15M"
$eventTrigger = Get-CimClass -ClassName MSFT_TaskEventTrigger -Namespace Root/Microsoft/Windows/TaskScheduler
$onWake = New-CimInstance -CimClass $eventTrigger -ClientOnly
$onWake.Enabled = $true
$onWake.Subscription = '<QueryList><Query Id="0" Path="System"><Select Path="System">' +
    "*[System[Provider[@Name='Microsoft-Windows-Power-Troubleshooter'] and (EventID=1)]]" +
    '</Select></Query></QueryList>'
$onWake.Delay = "PT15M"
$watch = New-ScheduledTaskAction -Execute $PythonW -Argument "`"$Watchdog`"" -WorkingDirectory $Root
Register-ScheduledTask -TaskPath $Folder -TaskName "Watchdog" -Action $watch -Principal $principal `
    -Settings $wdSettings -Force -Trigger @($atLogon, $onWake) `
    -Description "MarketMind missed-run watchdog: one notice per missed or failed day." | Out-Null

# Dashboard server at logon (no time limit)
$dashSettings = New-ScheduledTaskSettingsSet -ExecutionTimeLimit ([TimeSpan]::Zero) `
    -MultipleInstances IgnoreNew -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
$dash = New-ScheduledTaskAction -Execute $PythonW -Argument "`"$Server`"" -WorkingDirectory $Root
Register-ScheduledTask -TaskPath $Folder -TaskName "Dashboard" -Action $dash -Principal $principal `
    -Settings $dashSettings -Force -Trigger (New-ScheduledTaskTrigger -AtLogOn -User $User) `
    -Description "MarketMind white-box dashboard on http://127.0.0.1:8520" | Out-Null

# Task self-check at logon from the user's Startup folder, i.e. outside Task Scheduler:
# on 2026-10-02 every task under \MarketMind\ was deleted at once (360 Total Security
# suspected). ensure_tasks.py re-runs this script if any of the four is missing and
# pushes one notice. uninstall_schedule.ps1 removes the shortcut.
$Ensure = Join-Path $Root "marketmind\scripts\ensure_tasks.py"
$Shortcut = Join-Path ([Environment]::GetFolderPath("Startup")) "MarketMind task check.lnk"
$lnk = (New-Object -ComObject WScript.Shell).CreateShortcut($Shortcut)
$lnk.TargetPath = $PythonW
$lnk.Arguments = "`"$Ensure`""
$lnk.WorkingDirectory = $Root
$lnk.WindowStyle = 7
$lnk.Description = "MarketMind: re-register the scheduled tasks if they are missing"
$lnk.Save()

Write-Output "Registered in Task Scheduler folder $Folder for $User"
Write-Output ("  Daily     {0:HH:mm}, {1:HH:mm} and {2:HH:mm} local (08:45 New York in US daylight / standard time, then a later retry)" -f $daylight, $standard, $lateRetry)
Write-Output "  Weekend   Sat, Sun 12:00 and 14:00 local"
Write-Output "  Watchdog  15 minutes after logon and after wake from sleep"
Write-Output "  Dashboard at logon"
Write-Output "Task check at logon (Startup folder): $Shortcut"
Write-Output "Python: $Python"

