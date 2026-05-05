param(
  [string]$SiteName = "sixram.editor",
  [string]$HostName = "sixram.editor",
  [int]$Port = 80,
  [int]$BackendPort = 8000,
  [string]$SitePath = "C:\inetpub\sixram.editor",
  [bool]$EnableLanAccess = $true,
  [string[]]$FirewallProfiles = @("Private", "Domain")
)

$ErrorActionPreference = "Stop"

function Assert-Administrator {
  $identity = [Security.Principal.WindowsIdentity]::GetCurrent()
  $principal = [Security.Principal.WindowsPrincipal]::new($identity)
  if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    throw "Run this script from an elevated PowerShell window: right-click PowerShell and choose 'Run as Administrator'."
  }
}

function Write-Step {
  param([string]$Message)
  Write-Host "==> $Message" -ForegroundColor Cyan
}

function Get-LanIpAddresses {
  try {
    return @(
      Get-NetIPAddress -AddressFamily IPv4 -ErrorAction Stop |
        Where-Object {
          $_.IPAddress -notlike "127.*" -and
          $_.IPAddress -notlike "169.254.*" -and
          $_.AddressState -eq "Preferred"
        } |
        Select-Object -ExpandProperty IPAddress -Unique
    )
  }
  catch {
    return @(
      [System.Net.Dns]::GetHostAddresses([System.Net.Dns]::GetHostName()) |
        Where-Object { $_.AddressFamily -eq [System.Net.Sockets.AddressFamily]::InterNetwork } |
        ForEach-Object { $_.IPAddressToString } |
        Where-Object { $_ -notlike "127.*" -and $_ -notlike "169.254.*" } |
        Select-Object -Unique
    )
  }
}

Assert-Administrator

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$ProjectRoot = Resolve-Path (Join-Path $ScriptDir "..\..")
$FrontendDir = Join-Path $ProjectRoot "frontend"
$BackendDir = Join-Path $ProjectRoot "backend"
$FrontendDist = Join-Path $FrontendDir "dist"
$PythonExe = Join-Path $BackendDir ".venv\Scripts\python.exe"
$AppCmd = Join-Path $env:windir "System32\inetsrv\appcmd.exe"
$RewriteDll = Join-Path $env:windir "System32\inetsrv\rewrite.dll"
$ArrDll = Join-Path $env:ProgramFiles "IIS\Application Request Routing\requestRouter.dll"
$TaskName = "$SiteName.backend"
$CurrentUser = [Security.Principal.WindowsIdentity]::GetCurrent().Name
$LanIpAddresses = Get-LanIpAddresses

if (-not (Test-Path $AppCmd)) {
  throw "IIS appcmd.exe was not found. Please enable IIS first."
}
if (-not (Test-Path $RewriteDll)) {
  throw "IIS URL Rewrite was not found. Install IIS URL Rewrite before publishing this app."
}
if (-not (Test-Path $ArrDll)) {
  throw "IIS Application Request Routing was not found. Install ARR before publishing this app."
}
if (-not (Test-Path $PythonExe)) {
  throw "Backend virtualenv Python was not found at $PythonExe."
}

Write-Step "Building frontend"
Push-Location $FrontendDir
try {
  npm run build
}
finally {
  Pop-Location
}

if (-not (Test-Path $FrontendDist)) {
  throw "Frontend build folder was not found at $FrontendDist."
}

Write-Step "Preparing IIS physical path: $SitePath"
$resolvedSiteParent = Resolve-Path (Split-Path -Parent $SitePath)
if (-not ($resolvedSiteParent.Path -like "C:\inetpub*")) {
  throw "Refusing to publish outside C:\inetpub. Requested path: $SitePath"
}
New-Item -ItemType Directory -Path $SitePath -Force | Out-Null
Get-ChildItem -LiteralPath $SitePath -Force | Remove-Item -Recurse -Force
Copy-Item -Path (Join-Path $FrontendDist "*") -Destination $SitePath -Recurse -Force

Write-Step "Writing IIS web.config"
$webConfig = @"
<?xml version="1.0" encoding="utf-8"?>
<configuration>
  <system.webServer>
    <security>
      <requestFiltering>
        <requestLimits maxAllowedContentLength="4294967295" />
      </requestFiltering>
    </security>
    <rewrite>
      <rules>
        <rule name="Proxy API to FastAPI" stopProcessing="true">
          <match url="^api/(.*)" />
          <action type="Rewrite" url="http://127.0.0.1:$BackendPort/api/{R:1}" />
        </rule>
        <rule name="Proxy Media to FastAPI" stopProcessing="true">
          <match url="^media/(.*)" />
          <action type="Rewrite" url="http://127.0.0.1:$BackendPort/media/{R:1}" />
        </rule>
        <rule name="React Router SPA fallback" stopProcessing="true">
          <match url=".*" />
          <conditions logicalGrouping="MatchAll">
            <add input="{REQUEST_FILENAME}" matchType="IsFile" negate="true" />
            <add input="{REQUEST_FILENAME}" matchType="IsDirectory" negate="true" />
          </conditions>
          <action type="Rewrite" url="/index.html" />
        </rule>
      </rules>
    </rewrite>
  </system.webServer>
</configuration>
"@
Set-Content -LiteralPath (Join-Path $SitePath "web.config") -Value $webConfig -Encoding UTF8

Write-Step "Enabling ARR reverse proxy"
& $AppCmd set config -section:system.webServer/proxy /enabled:"True" /reverseRewriteHostInResponseHeaders:"False" /commit:apphost | Out-Host

Import-Module WebAdministration

Write-Step "Creating or updating IIS app pool"
if (-not (Test-Path "IIS:\AppPools\$SiteName")) {
  New-WebAppPool -Name $SiteName | Out-Null
}
Set-ItemProperty "IIS:\AppPools\$SiteName" -Name managedRuntimeVersion -Value ""
Set-ItemProperty "IIS:\AppPools\$SiteName" -Name processModel.identityType -Value "ApplicationPoolIdentity"

Write-Step "Creating or updating IIS site"
if (-not (Test-Path "IIS:\Sites\$SiteName")) {
  New-Website -Name $SiteName -PhysicalPath $SitePath -Port $Port -HostHeader $HostName -ApplicationPool $SiteName | Out-Null
}
else {
  Set-ItemProperty "IIS:\Sites\$SiteName" -Name physicalPath -Value $SitePath
  Set-ItemProperty "IIS:\Sites\$SiteName" -Name applicationPool -Value $SiteName
  $binding = Get-WebBinding -Name $SiteName -Protocol "http" | Where-Object { $_.bindingInformation -eq "*:$Port`:$HostName" }
  if (-not $binding) {
    New-WebBinding -Name $SiteName -Protocol "http" -Port $Port -HostHeader $HostName | Out-Null
  }
}

Write-Step "Adding hosts file entry"
$hostsPath = Join-Path $env:windir "System32\drivers\etc\hosts"
$hostsContent = Get-Content -LiteralPath $hostsPath -ErrorAction SilentlyContinue
if (-not ($hostsContent | Where-Object { $_ -match "^\s*127\.0\.0\.1\s+$([regex]::Escape($HostName))(\s|$)" })) {
  Add-Content -LiteralPath $hostsPath -Value "127.0.0.1 $HostName"
}

if ($EnableLanAccess) {
  Write-Step "Configuring LAN access for mobile and tablet devices"
  $lanAccessUrls = @()
  foreach ($lanIp in $LanIpAddresses) {
    $bindingInfo = "$($lanIp):$Port`:"
    $existingLanBinding = Get-WebBinding -Name $SiteName -Protocol "http" | Where-Object { $_.bindingInformation -eq $bindingInfo }
    if (-not $existingLanBinding) {
      try {
        New-WebBinding -Name $SiteName -Protocol "http" -IPAddress $lanIp -Port $Port -HostHeader "" | Out-Null
      }
      catch {
        Write-Warning "Could not add IIS LAN binding for http://$($lanIp):$Port/. Another IIS site may already own that binding. Details: $($_.Exception.Message)"
      }
    }

    if ($Port -eq 80) {
      $lanAccessUrls += "http://$lanIp/"
    }
    else {
      $lanAccessUrls += "http://$($lanIp):$Port/"
    }
  }

  if ($FirewallProfiles.Count -gt 0) {
    $firewallRuleName = "$SiteName HTTP $Port"
    $existingFirewallRule = Get-NetFirewallRule -DisplayName $firewallRuleName -ErrorAction SilentlyContinue
    if (-not $existingFirewallRule) {
      New-NetFirewallRule -DisplayName $firewallRuleName -Direction Inbound -Action Allow -Protocol TCP -LocalPort $Port -Profile $FirewallProfiles | Out-Null
    }
    else {
      Set-NetFirewallRule -DisplayName $firewallRuleName -Enabled True -Profile $FirewallProfiles
    }

    $publicProfiles = Get-NetConnectionProfile -ErrorAction SilentlyContinue | Where-Object {
      $_.IPv4Connectivity -ne "Disconnected" -and $_.NetworkCategory -eq "Public"
    }
    if ($publicProfiles) {
      Write-Warning "Your active network profile is Public. If tablet/mobile access is still blocked, set this Wi-Fi network to Private or rerun with -FirewallProfiles Any."
    }
  }
}

Write-Step "Registering backend scheduled task"
$action = New-ScheduledTaskAction -Execute $PythonExe -Argument "-m uvicorn app.main:app --host 127.0.0.1 --port $BackendPort" -WorkingDirectory $BackendDir
$trigger = New-ScheduledTaskTrigger -AtLogOn
$principal = New-ScheduledTaskPrincipal -UserId $CurrentUser -LogonType Interactive -RunLevel Highest
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -ExecutionTimeLimit ([TimeSpan]::Zero) -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1)
if (Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue) {
  Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
}
Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger -Principal $principal -Settings $settings | Out-Null

Write-Step "Starting backend task and IIS site"
Start-ScheduledTask -TaskName $TaskName
Start-Website -Name $SiteName

Write-Host ""
Write-Host "Published successfully." -ForegroundColor Green
Write-Host "Open: http://$HostName/"
if ($EnableLanAccess -and $lanAccessUrls.Count -gt 0) {
  Write-Host "From tablet/mobile on the same Wi-Fi, open one of:"
  $lanAccessUrls | ForEach-Object { Write-Host "  $_" }
  Write-Host "To use http://$HostName/ from tablet/mobile, add a DNS/router entry that points $HostName to this PC's LAN IP."
}
Write-Host "Backend: http://127.0.0.1:$BackendPort/api/health"
