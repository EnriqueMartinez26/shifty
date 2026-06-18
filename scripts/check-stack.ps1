param(
    [string]$BackendBaseUrl = "http://127.0.0.1:8000",
    [string]$EnvFile = ".env",
    [string]$CorsOrigin = "http://localhost:5173"
)

$ErrorActionPreference = "Stop"

function Write-Pass([string]$Message) {
    Write-Host "[PASS] $Message" -ForegroundColor Green
}

function Write-Fail([string]$Message) {
    Write-Host "[FAIL] $Message" -ForegroundColor Red
}

function Write-Info([string]$Message) {
    Write-Host "[INFO] $Message" -ForegroundColor Cyan
}

function Get-EnvValue([string]$Path, [string]$Key) {
    if (-not (Test-Path $Path)) {
        return $null
    }

    $line = Get-Content $Path | Where-Object { $_ -match "^$Key=" } | Select-Object -First 1
    if (-not $line) {
        return $null
    }

    return ($line -replace "^$Key=", "").Trim()
}

function Parse-DatabaseUrl([string]$DatabaseUrl) {
    if (-not $DatabaseUrl) {
        return $null
    }

    $clean = $DatabaseUrl
    if ($clean -match "\?") {
        $clean = $clean.Split("?")[0]
    }

    $clean = $clean -replace "^postgresql\+asyncpg://", ""
    $pattern = "^(?<user>[^:]+):(?<password>[^@]+)@(?<host>[^:/]+)(:(?<port>\d+))?/(?<db>.+)$"
    $match = [regex]::Match($clean, $pattern)
    if (-not $match.Success) {
        return $null
    }

    [pscustomobject]@{
        User = $match.Groups["user"].Value
        Password = $match.Groups["password"].Value
        Host = $match.Groups["host"].Value
        Port = if ($match.Groups["port"].Value) { [int]$match.Groups["port"].Value } else { 5432 }
        Database = $match.Groups["db"].Value
    }
}

function Test-PortListening([int]$Port) {
    $listener = Get-NetTCPConnection -State Listen -ErrorAction SilentlyContinue | Where-Object { $_.LocalPort -eq $Port } | Select-Object -First 1
    if ($listener) {
        return [pscustomobject]@{
            IsListening = $true
            Pid = $listener.OwningProcess
            Address = $listener.LocalAddress
        }
    }

    return [pscustomobject]@{
        IsListening = $false
        Pid = $null
        Address = $null
    }
}

function Test-AsyncPgConnection([pscustomobject]$DbParts) {
    $pythonScript = @"
import asyncio
import asyncpg

async def main():
    try:
        conn = await asyncpg.connect(
            user=r'''$($DbParts.User)''',
            password=r'''$($DbParts.Password)''',
            database=r'''$($DbParts.Database)''',
            host=r'''$($DbParts.Host)''',
            port=$($DbParts.Port),
            timeout=5,
        )
        val = await conn.fetchval('select 1')
        await conn.close()
        print('OK', val)
    except Exception as e:
        print('ERR', type(e).__name__, str(e))

asyncio.run(main())
"@

    $output = $pythonScript | python -
    if ($LASTEXITCODE -ne 0) {
        return "ERR python_exit_$LASTEXITCODE"
    }

    return ($output -join "`n")
}

function Test-BackendRequest([string]$Url, [string]$Method, [string]$Origin, [string]$BodyJson = "") {
    try {
        if ($Method -eq "POST") {
            $response = Invoke-WebRequest -UseBasicParsing -Method Post -Uri $Url -Headers @{ Origin = $Origin } -Body $BodyJson -ContentType "application/json" -ErrorAction Stop
        } elseif ($Method -eq "OPTIONS") {
            $response = Invoke-WebRequest -UseBasicParsing -Method Options -Uri $Url -Headers @{
                Origin = $Origin
                "Access-Control-Request-Method" = "POST"
                "Access-Control-Request-Headers" = "content-type"
            } -ErrorAction Stop
        } else {
            $response = Invoke-WebRequest -UseBasicParsing -Method Get -Uri $Url -Headers @{ Origin = $Origin } -ErrorAction Stop
        }

        return [pscustomobject]@{
            StatusCode = [int]$response.StatusCode
            AllowOrigin = $response.Headers["Access-Control-Allow-Origin"]
            AllowCredentials = $response.Headers["Access-Control-Allow-Credentials"]
            AllowMethods = $response.Headers["Access-Control-Allow-Methods"]
            AllowHeaders = $response.Headers["Access-Control-Allow-Headers"]
            Body = $response.Content
            IsError = $false
        }
    }
    catch {
        $ex = $_.Exception
        $webResponse = $ex.Response
        if ($webResponse) {
            $statusCode = [int]$webResponse.StatusCode
            $allowOrigin = $webResponse.Headers["Access-Control-Allow-Origin"]

            $reader = New-Object System.IO.StreamReader($webResponse.GetResponseStream())
            $content = $reader.ReadToEnd()
            $reader.Close()

            return [pscustomobject]@{
                StatusCode = $statusCode
                AllowOrigin = $allowOrigin
                AllowCredentials = $webResponse.Headers["Access-Control-Allow-Credentials"]
                AllowMethods = $webResponse.Headers["Access-Control-Allow-Methods"]
                AllowHeaders = $webResponse.Headers["Access-Control-Allow-Headers"]
                Body = $content
                IsError = $true
            }
        }

        return [pscustomobject]@{
            StatusCode = 0
            AllowOrigin = $null
            AllowCredentials = $null
            AllowMethods = $null
            AllowHeaders = $null
            Body = $ex.Message
            IsError = $true
        }
    }
}

Write-Info "Shifty Docker-first stack check started"

$projectRoot = Split-Path -Parent $PSScriptRoot
$envPath = Join-Path $projectRoot $EnvFile
Write-Info "Using env file: $envPath"
Write-Info "Using CORS origin: $CorsOrigin"

$databaseUrl = Get-EnvValue -Path $envPath -Key "DATABASE_URL"
if ($databaseUrl) {
    Write-Pass "DATABASE_URL found"
} else {
    Write-Fail "DATABASE_URL missing in $envPath"
    exit 1
}

$dbParts = Parse-DatabaseUrl -DatabaseUrl $databaseUrl
if (-not $dbParts) {
    Write-Fail "DATABASE_URL could not be parsed"
    exit 1
}
Write-Info "DB target => $($dbParts.Host):$($dbParts.Port)/$($dbParts.Database) (user: $($dbParts.User))"

$services = @("postgresql-x64-16", "postgresql-x64-18")
foreach ($serviceName in $services) {
    $svc = Get-Service -Name $serviceName -ErrorAction SilentlyContinue
    if (-not $svc) {
        Write-Info "$serviceName not installed"
        continue
    }

    if ($svc.Status -eq "Running") {
        Write-Pass "$serviceName is running (Startup: $($svc.StartType))"
    } else {
        Write-Info "$serviceName status: $($svc.Status) (Startup: $($svc.StartType))"
    }
}

$portsToCheck = @(5432, 5433, 6379, 8000, 8001)
foreach ($port in $portsToCheck) {
    $portState = Test-PortListening -Port $port
    if ($portState.IsListening) {
        Write-Pass "Port $port listening (PID $($portState.Pid), Address $($portState.Address))"
    } else {
        Write-Info "Port $port not listening"
    }
}

$dbConnResult = Test-AsyncPgConnection -DbParts $dbParts
if ($dbConnResult -like "OK*") {
    Write-Pass "Database connection successful ($dbConnResult)"
} else {
    Write-Fail "Database connection failed ($dbConnResult)"
}

$health = Test-BackendRequest -Url "$BackendBaseUrl/" -Method "GET" -Origin $CorsOrigin
if ($health.StatusCode -eq 200) {
    Write-Pass "Backend health reachable at $BackendBaseUrl/"
} else {
    Write-Fail "Backend health check failed (status $($health.StatusCode)): $($health.Body)"
}

$loginBody = '{"email":"noexiste@demo.com","password":"bad"}'
$login = Test-BackendRequest -Url "$BackendBaseUrl/auth/login" -Method "POST" -Origin $CorsOrigin -BodyJson $loginBody
if ($login.StatusCode -eq 401) {
    Write-Pass "Login endpoint reachable and returns expected 401"
} elseif ($login.StatusCode -eq 200) {
    Write-Pass "Login endpoint reachable and returned 200"
} else {
    Write-Fail "Login endpoint returned status $($login.StatusCode): $($login.Body)"
}

if ($login.AllowOrigin) {
    Write-Pass "CORS header present on login response (Access-Control-Allow-Origin: $($login.AllowOrigin))"
} else {
    Write-Fail "CORS header missing on login response"
}

$preflight = Test-BackendRequest -Url "$BackendBaseUrl/auth/login" -Method "OPTIONS" -Origin $CorsOrigin
if ($preflight.StatusCode -eq 200 -or $preflight.StatusCode -eq 204) {
    Write-Pass "CORS preflight succeeded for /auth/login"
} else {
    Write-Fail "CORS preflight failed (status $($preflight.StatusCode)): $($preflight.Body)"
}

if ($preflight.AllowOrigin -eq $CorsOrigin) {
    Write-Pass "CORS preflight allows expected origin ($CorsOrigin)"
} else {
    Write-Fail "CORS preflight did not allow expected origin (received: $($preflight.AllowOrigin))"
}

if ($preflight.AllowCredentials -eq "true") {
    Write-Pass "CORS preflight allows credentials"
} else {
    Write-Fail "CORS preflight missing Access-Control-Allow-Credentials: true"
}

Write-Info "Shifty stack check finished"
