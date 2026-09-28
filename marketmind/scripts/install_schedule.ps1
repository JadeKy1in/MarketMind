# Register MarketMind's scheduled tasks for the current user (docs/AUTOMATION.md).
#   powershell -ExecutionPolicy Bypass -File marketmind\scripts\install_schedule.ps1
# Re-running replaces the tasks. Remove them with uninstall_schedule.ps1.
#
# Tasks (folder \MarketMind\):
#   Daily      two daily triggers at the local times of 08:45 New York during US
#              daylight time (12:45 UTC) and standard time (13:45 UTC); the Python
#              wrapper runs only once per day and only from 08:25 New York on.
#   Weekend    Saturday and Sunday 12:00 local: settle + crypto shadows.
#   Dashboard  at logon: the white-box dashboard on http://127.0.0.1:8520
# All run only while this user is logged on (no stored password), wake the
# computer from sleep, and catch up after a missed start.
$ErrorActionPreference = "Stop"

$Root = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$Python = (Get-Command python -ErrorAction Stop).Source
$PythonW = Join-Path (Split-Path $Python) "pythonw.exe"
if (-not (Test-Path $PythonW)) { $PythonW = $Python }
$Wrapper = Join-Path $Root "marketmind\scripts\scheduled_run.py"
$Server = Join-Path $Root "marketmind\api_server.py"
$User = "$env:USERDOMAIN\$env:USERNAME"
$Folder = "\MarketMind\"

function LocalTimeOfUtc([int]$h, [int]$m) {
    $utc = [DateTime]::SpecifyKind([DateTime]::UtcNow.Date.AddHours($h).AddMinutes($m), "Utc")
    return [TimeZoneInfo]::ConvertTimeFromUtc($utc, [TimeZoneInfo]::Local)
}

$principal = New-ScheduledTaskPrincipal -UserId $User -LogonType Interactive -RunLevel Limited
$runSettings = New-ScheduledTaskSettingsSet -WakeToRun -StartWhenAvailable `
    -ExecutionTimeLimit (New-TimeSpan -Hours 2) -MultipleInstances IgnoreNew `
    -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries

# Daily pre-open run
$daylight = LocalTimeOfUtc 12 45
$standard = LocalTimeOfUtc 13 45
$daily = New-ScheduledTaskAction -Execute $Python -Argument "`"$Wrapper`" --slot weekday" -WorkingDirectory $Root
Register-ScheduledTask -TaskPath $Folder -TaskName "Daily" -Action $daily -Principal $principal `
    -Settings $runSettings -Force `
    -Trigger @((New-ScheduledTaskTrigger -Daily -At $daylight), (New-ScheduledTaskTrigger -Daily -At $standard)) `
    -Description "MarketMind pre-open run (08:45 New York). Wrapper runs once per day." | Out-Null

# Weekend crypto run
$weekend = New-ScheduledTaskAction -Execute $Python -Argument "`"$Wrapper`" --slot weekend" -WorkingDirectory $Root
Register-ScheduledTask -TaskPath $Folder -TaskName "Weekend" -Action $weekend -Principal $principal `
    -Settings $runSettings -Force `
    -Trigger (New-ScheduledTaskTrigger -Weekly -DaysOfWeek Saturday, Sunday -At "12:00") `
    -Description "MarketMind weekend: settle ledger + crypto shadows." | Out-Null

# Dashboard server at logon (no time limit)
$dashSettings = New-ScheduledTaskSettingsSet -ExecutionTimeLimit ([TimeSpan]::Zero) `
    -MultipleInstances IgnoreNew -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
$dash = New-ScheduledTaskAction -Execute $PythonW -Argument "`"$Server`"" -WorkingDirectory $Root
Register-ScheduledTask -TaskPath $Folder -TaskName "Dashboard" -Action $dash -Principal $principal `
    -Settings $dashSettings -Force -Trigger (New-ScheduledTaskTrigger -AtLogOn -User $User) `
    -Description "MarketMind white-box dashboard on http://127.0.0.1:8520" | Out-Null

Write-Output "Registered in Task Scheduler folder $Folder for $User"
Write-Output ("  Daily     {0:HH:mm} and {1:HH:mm} local (08:45 New York in US daylight / standard time)" -f $daylight, $standard)
Write-Output "  Weekend   Sat, Sun 12:00 local"
Write-Output "  Dashboard at logon"
Write-Output "Python: $Python"
