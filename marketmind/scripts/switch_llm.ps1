# Switch MarketMind's language model provider (docs/LLM_PROVIDER.md).
#   powershell -ExecutionPolicy Bypass -File marketmind\scripts\switch_llm.ps1 claude
#   powershell -ExecutionPolicy Bypass -File marketmind\scripts\switch_llm.ps1 deepseek
#   powershell -ExecutionPolicy Bypass -File marketmind\scripts\switch_llm.ps1 status
# Sets the user environment variable MARKETMIND_LLM. Scheduled runs pick it up on
# their next start; open a new terminal for manual runs.
param([Parameter(Position = 0)][ValidateSet("claude", "deepseek", "status")][string]$Provider = "status")

$current = [Environment]::GetEnvironmentVariable("MARKETMIND_LLM", "User")
if (-not $current) { $current = "deepseek" }

if ($Provider -eq "status") {
    Write-Output "MarketMind LLM provider: $current"
    $pro = [Environment]::GetEnvironmentVariable("MARKETMIND_CLAUDE_PRO_MODEL", "User")
    $flash = [Environment]::GetEnvironmentVariable("MARKETMIND_CLAUDE_FLASH_MODEL", "User")
    if (-not $pro) { $pro = "opus (default)" }
    if (-not $flash) { $flash = "sonnet (default)" }
    Write-Output "  Claude main pipeline model : $pro"
    Write-Output "  Claude other calls model   : $flash"
    exit 0
}

if ($Provider -eq "claude") {
    $claude = Get-Command claude -ErrorAction SilentlyContinue
    if (-not $claude) { Write-Error "Claude Code CLI not found on PATH; install it and log in first."; exit 1 }
    $probe = "Reply with the single word OK." | claude -p --model sonnet --output-format json --tools "" --no-session-persistence --setting-sources "" --strict-mcp-config --permission-prompts none 2>&1 | Out-String
    if ($probe -notmatch '"subtype"\s*:\s*"success"') {
        Write-Error "Claude test call failed; staying on $current. Output: $($probe.Substring(0, [Math]::Min(300, $probe.Length)))"
        exit 1
    }
    Write-Output "Claude test call OK."
}

[Environment]::SetEnvironmentVariable("MARKETMIND_LLM", $Provider, "User")
Write-Output "MarketMind LLM provider: $current -> $Provider (takes effect on the next run)"
