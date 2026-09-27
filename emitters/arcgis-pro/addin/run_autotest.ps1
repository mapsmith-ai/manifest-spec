# End-to-end check of the Provenance Manifest add-in, with nobody at the keyboard.
#
#   powershell -ExecutionPolicy Bypass -File run_autotest.ps1 -PristineProject C:\path\to\empty-project
#
# Copies the project folder you give (any ArcGIS Pro project with a map; it is
# never modified) to a scratch folder, starts ArcGIS Pro on the copy with the
# autotest switch, waits for Pro to exit (killing it after the timeout), then
# checks every manifest the run wrote with the specification's validator.
param(
    [Parameter(Mandatory = $true)][string]$PristineProject,
    [int]$TimeoutSeconds = 900   # with the map view open each tool waits for a redraw: 25-50 s on a locked session
)

$here = Split-Path -Parent $MyInvocation.MyCommand.Path

# The build calls RegisterAddIn and ignores its exit code, and when the tool is
# not on PATH it installs nothing: Pro then loads the previous add-in and the
# test checks a binary nobody just built. Compare the installed copy with the
# build output before starting.
$built = Get-ChildItem (Join-Path $here 'bin\Release') -Recurse -Filter ProvenanceManifest.esriAddinX | Sort-Object LastWriteTime | Select-Object -Last 1
if (-not $built) { throw 'no build output: run "dotnet build -c Release" first' }
$docs = [Environment]::GetFolderPath('MyDocuments')
$installed = Get-ChildItem (Join-Path $docs 'ArcGIS\AddIns\ArcGISPro') -Recurse -Filter ProvenanceManifest.esriAddinX -ErrorAction SilentlyContinue
if (-not $installed -or ((Get-FileHash $installed[0].FullName).Hash -ne (Get-FileHash $built.FullName).Hash)) {
    throw "the installed add-in is not the build output: run `"C:\Program Files\ArcGIS\Pro\bin\RegisterAddIn.exe`" `"$($built.FullName)`" /s"
}
$work = Join-Path $env:TEMP 'provenance-manifest-autotest'
Remove-Item -Recurse -Force $work -ErrorAction SilentlyContinue -Confirm:$false
Copy-Item -Recurse $PristineProject $work
$aprx = Get-ChildItem $work -Filter *.aprx | Select-Object -First 1
if (-not $aprx) { throw "no .aprx in $PristineProject" }

$root = Join-Path $env:LOCALAPPDATA 'ProvenanceManifest'
Remove-Item (Join-Path $root 'addin.log') -ErrorAction SilentlyContinue -Confirm:$false
Remove-Item -Recurse (Join-Path $root 'captures') -ErrorAction SilentlyContinue -Confirm:$false

$pro = (Get-ItemProperty 'HKLM:\SOFTWARE\ESRI\ArcGISPro' -ErrorAction SilentlyContinue).InstallDir
if (-not $pro) { $pro = 'C:\Program Files\ArcGIS\Pro\' }
$start = Get-Date
$p = Start-Process -FilePath (Join-Path $pro 'bin\ArcGISPro.exe') -ArgumentList "/provenance-manifest-autotest `"$($aprx.FullName)`"" -PassThru
if ($p.WaitForExit($TimeoutSeconds * 1000)) {
    "PRO EXITED after $([int]((Get-Date) - $start).TotalSeconds)s"
} else {
    Stop-Process -Id $p.Id -Force -Confirm:$false
    "PRO TIMEOUT after $TimeoutSeconds s: killed PID $($p.Id)"
}
& (Join-Path $pro 'bin\Python\envs\arcgispro-py3\python.exe') (Join-Path $here 'check_manifests.py') $work
exit $LASTEXITCODE
