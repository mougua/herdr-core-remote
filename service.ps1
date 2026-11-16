#Requires -Version 5.1
param(
    [ValidateSet('start', 'stop', 'status', 'restart', 'url', 'test')]
    [string]$Action = 'status'
)
$ErrorActionPreference = 'Stop'
$python = (Get-Command python -CommandType Application -ErrorAction Stop).Source
if ($Action -eq 'test') {
    & $python -m unittest discover -s "$PSScriptRoot\tests" -v
} else {
    & $python "$PSScriptRoot\remote.py" $Action
}
exit $LASTEXITCODE
