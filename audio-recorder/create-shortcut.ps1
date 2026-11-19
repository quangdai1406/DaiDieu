param(
    [string]$Device = "cuda",
    [string]$Model = "small.en",
    [string]$Name = "Meeting Recorder",
    [switch]$Console
)
$ErrorActionPreference = "Stop"

$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$exeName = if ($Console) { "python.exe" } else { "pythonw.exe" }
$exe = Join-Path $here ".venv\Scripts\$exeName"
if (-not (Test-Path $exe)) {
    throw "Cannot find $exe. Create the environment first: python -m venv .venv, then .\.venv\Scripts\python -m pip install -r requirements-gpu.txt"
}

$desktop = [Environment]::GetFolderPath("Desktop")
$link = Join-Path $desktop "$Name.lnk"
$icon = Join-Path $here "recorder\app.ico"

$shell = New-Object -ComObject WScript.Shell
$shortcut = $shell.CreateShortcut($link)
$shortcut.TargetPath = $exe
$shortcut.Arguments = "-m recorder gui --device $Device --model $Model"
$shortcut.WorkingDirectory = $here
$shortcut.Description = "Record speakers and microphone, then transcribe"
if (Test-Path $icon) { $shortcut.IconLocation = $icon }
$shortcut.Save()

Write-Host "Created: $link"
Write-Host "It runs: $exe $($shortcut.Arguments)"
Write-Host "Recordings are saved in: $([Environment]::GetFolderPath('MyDocuments'))\Meeting Recorder  (or Documents\Meeting Recorder)"
if (-not $Console) {
    Write-Host "No console window is shown; if the app does not open, errors are in: $env:LOCALAPPDATA\Meeting Recorder\last-run.log"
}
