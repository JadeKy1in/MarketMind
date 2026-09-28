# Remove MarketMind's scheduled tasks (see install_schedule.ps1).
#   powershell -ExecutionPolicy Bypass -File marketmind\scripts\uninstall_schedule.ps1
$tasks = Get-ScheduledTask -TaskPath "\MarketMind\" -ErrorAction SilentlyContinue
if (-not $tasks) { Write-Output "No MarketMind tasks registered."; exit 0 }
foreach ($t in $tasks) {
    Unregister-ScheduledTask -TaskPath $t.TaskPath -TaskName $t.TaskName -Confirm:$false
    Write-Output "Removed $($t.TaskPath)$($t.TaskName)"
}
