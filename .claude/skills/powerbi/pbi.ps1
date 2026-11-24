param(
  [Parameter(Mandatory = $true)][ValidateSet("open", "query", "shot", "close")][string]$Action,
  [string]$Pbip, [int]$Port, [string]$InFile, [string]$OutFile, [string]$Shot, [int]$ProcId, [int]$EngineId
)
# Helper for the /powerbi skill (called by check.py). Talks only to the Power BI Desktop it started itself.
#   open   start Power BI Desktop with the .pbip, wait until the model is loaded, print JSON {pid, engine, port}
#          refuses (exit 2) if any Power BI Desktop is already open, so it never touches the user's work
#   query  run DAX / DMV / TMSL items from -InFile (JSON list of {id, kind, text}) and write results to -OutFile
#   shot   capture ONLY the Power BI window's own content (PrintWindow), never other windows
#   close  stop exactly the given Power BI process and its engine
$ErrorActionPreference = "Stop"

function Get-Adomd {
  $loc = (Get-AppxPackage -Name "Microsoft.MicrosoftPowerBIDesktop").InstallLocation
  if (-not $loc) { throw "Power BI Desktop (Microsoft Store version) not found" }
  try { Add-Type -Path "$loc\bin\Microsoft.PowerBI.AdomdClient.dll" -ErrorAction Stop } catch { }
}

if ($Action -eq "open") {
  if (Get-Process PBIDesktop -ErrorAction SilentlyContinue) { Write-Output '{"error": "Power BI Desktop is already open"}'; exit 2 }
  $before = @(Get-Process msmdsrv -ErrorAction SilentlyContinue | ForEach-Object Id)
  $t0 = Get-Date
  Start-Process "$env:LOCALAPPDATA\Microsoft\WindowsApps\PBIDesktopStore.exe" -ArgumentList "`"$Pbip`""
  Get-Adomd
  $mine = $null; $engine = $null; $port = $null; $ready = $false
  for ($i = 0; $i -lt 100 -and -not $ready; $i++) {
    Start-Sleep -Seconds 3
    if (-not $mine) { $mine = Get-Process PBIDesktop -ErrorAction SilentlyContinue | Where-Object { $_.StartTime -ge $t0.AddSeconds(-5) } | Select-Object -First 1 }
    if (-not $engine) { $engine = Get-Process msmdsrv -ErrorAction SilentlyContinue | Where-Object { $before -notcontains $_.Id } | Select-Object -First 1 }
    if ($engine -and -not $port) { $port = (Get-NetTCPConnection -OwningProcess $engine.Id -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1).LocalPort }
    if ($port) {
      try {
        $c = New-Object Microsoft.AnalysisServices.AdomdClient.AdomdConnection("Data Source=localhost:$port"); $c.Open()
        $r = (New-Object Microsoft.AnalysisServices.AdomdClient.AdomdCommand('SELECT [CATALOG_NAME] FROM $SYSTEM.DBSCHEMA_CATALOGS', $c)).ExecuteReader()
        $db = $null; while ($r.Read()) { $db = $r.GetValue(0) }; $r.Close()
        if ($db) {
          $c.ChangeDatabase($db)
          $r = (New-Object Microsoft.AnalysisServices.AdomdClient.AdomdCommand('SELECT [Name] FROM $SYSTEM.TMSCHEMA_MEASURES', $c)).ExecuteReader()
          $n = 0; while ($r.Read()) { $n++ }; $r.Close()
          if ($n -gt 0) { $ready = $true }
        }
        $c.Close()
      } catch { }
    }
  }
  if (-not $ready) { Write-Output ('{"error": "model did not load", "pid": ' + [int]$mine.Id + ', "engine": ' + [int]$engine.Id + '}'); exit 3 }
  Start-Sleep -Seconds 5
  Write-Output ('{"pid": ' + $mine.Id + ', "engine": ' + $engine.Id + ', "port": ' + $port + '}')
}
elseif ($Action -eq "query") {
  Get-Adomd
  $items = Get-Content $InFile -Raw -Encoding UTF8 | ConvertFrom-Json
  $c = New-Object Microsoft.AnalysisServices.AdomdClient.AdomdConnection("Data Source=localhost:$Port"); $c.Open()
  $r = (New-Object Microsoft.AnalysisServices.AdomdClient.AdomdCommand('SELECT [CATALOG_NAME] FROM $SYSTEM.DBSCHEMA_CATALOGS', $c)).ExecuteReader()
  $db = $null; while ($r.Read()) { $db = $r.GetValue(0) }; $r.Close()
  $results = @()
  foreach ($it in $items) {
    $res = [ordered]@{ id = $it.id; ok = $true; rows = @(); error = $null }
    try {
      $text = $it.text.Replace("__DB__", "$db")
      if ($it.kind -ne "tmsl") { $c.ChangeDatabase($db) }
      $cmd = New-Object Microsoft.AnalysisServices.AdomdClient.AdomdCommand($text, $c); $cmd.CommandTimeout = 900
      if ($it.kind -eq "tmsl") { [void]$cmd.ExecuteNonQuery() }
      else {
        $rd = $cmd.ExecuteReader()
        while ($rd.Read()) {
          $row = [ordered]@{}
          for ($k = 0; $k -lt $rd.FieldCount; $k++) {
            $v = $rd.GetValue($k)
            if ($v -is [DBNull]) { $v = $null } elseif ($v -is [decimal] -or $v -is [double]) { $v = [string]$v } elseif ($v -is [datetime]) { $v = $v.ToString("yyyy-MM-dd") }
            $row[$rd.GetName($k)] = $v
          }
          $res.rows += $row
        }
        $rd.Close()
      }
    } catch { $res.ok = $false; $res.error = $_.Exception.Message }
    $results += $res
  }
  $c.Close()
  [ordered]@{ results = $results } | ConvertTo-Json -Depth 8 | Out-File $OutFile -Encoding utf8
}
elseif ($Action -eq "shot") {
  Add-Type -AssemblyName System.Drawing
  Add-Type @"
using System; using System.Runtime.InteropServices;
public class PbiWin { [DllImport("user32.dll")] public static extern bool GetWindowRect(IntPtr h, out RECT r);
 [DllImport("user32.dll")] public static extern bool PrintWindow(IntPtr h, IntPtr dc, uint flags);
 [DllImport("user32.dll")] public static extern bool ShowWindow(IntPtr h, int c);
 [DllImport("user32.dll")] public static extern bool SetProcessDPIAware();
 [StructLayout(LayoutKind.Sequential)] public struct RECT { public int L, T, R, B; } }
"@
  [PbiWin]::SetProcessDPIAware() | Out-Null
  $p = Get-Process -Id $ProcId -ErrorAction SilentlyContinue
  if (-not $p -or $p.MainWindowHandle -eq 0) { Write-Output "no window"; exit 4 }
  [PbiWin]::ShowWindow($p.MainWindowHandle, 3) | Out-Null
  Start-Sleep -Seconds 15
  $r = New-Object PbiWin+RECT; [PbiWin]::GetWindowRect($p.MainWindowHandle, [ref]$r) | Out-Null
  $bmp = New-Object System.Drawing.Bitmap ($r.R - $r.L), ($r.B - $r.T)
  $g = [System.Drawing.Graphics]::FromImage($bmp); $hdc = $g.GetHdc()
  [PbiWin]::PrintWindow($p.MainWindowHandle, $hdc, 2) | Out-Null   # 2 = this window's own content only
  $g.ReleaseHdc($hdc); $bmp.Save($Shot, [System.Drawing.Imaging.ImageFormat]::Png)
  Write-Output "saved $Shot"
}
elseif ($Action -eq "close") {
  foreach ($id in @($ProcId, $EngineId)) { if ($id) { Stop-Process -Id $id -Force -ErrorAction SilentlyContinue } }
  Write-Output "closed $ProcId $EngineId"
}
