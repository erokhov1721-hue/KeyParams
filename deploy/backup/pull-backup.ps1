<#
Забрать хранилище резервных копий KeyParams с сервера на этот компьютер.

    powershell -ExecutionPolicy Bypass -File deploy\backup\pull-backup.ps1

- Хранилище restic (~/backups/keyparams-restic) скачивается целиком в новую
  папку restic-<дата>_<время> внутри C:\Users\Yerokhov_d\KeyParams_backups.
  Оно зашифровано: без пароля хранилища из него ничего не прочитать.
- Пароль SSH спрашивает сама программа ssh, один раз; скрипт его не видит и
  нигде не хранит. Всё забирается за одно подключение.
- Скачанное сверяется с сервером по числу файлов и общему размеру. Только
  если всё сошлось, удаляются копии старше четырёх последних.
- В конце — дата последнего успешного копирования на сервере и крупное
  предупреждение, если оно старше 48 часов.
#>
param(
    [string]$Server = "workai-27.mr-group.ru",
    [string]$User = "userai-27",
    [string]$Destination = "C:\Users\Yerokhov_d\KeyParams_backups",
    [int]$Keep = 4,
    [int]$MaxAgeHours = 48,
    # Программа ssh; по умолчанию — встроенная в Windows.
    [string]$Ssh = (Join-Path $env:SystemRoot "System32\OpenSSH\ssh.exe")
)

$ErrorActionPreference = "Stop"
$Prefix = "restic-"

function Write-Banner([string[]]$Lines, [string]$Color) {
    $width = ($Lines | Measure-Object -Property Length -Maximum).Maximum + 4
    $bar = "#" * $width
    Write-Host ""
    Write-Host $bar -ForegroundColor $Color
    foreach ($line in $Lines) {
        Write-Host ("# " + $line.PadRight($width - 4) + " #") -ForegroundColor $Color
    }
    Write-Host $bar -ForegroundColor $Color
    Write-Host ""
}

# То, что выполняется на сервере: дождаться конца копирования, если оно
# идёт (тот же замок, что у keyparams-backup.sh), записать опись хранилища и
# отдать всё одним tar-потоком.
$remote = @'
set -e
cd "$HOME/backups"
mkdir -p "$HOME/.config/keyparams-backup"
exec 9>"$HOME/.config/keyparams-backup/lock"
flock 9
M=pull-manifest.txt
{
  echo "files=$(find keyparams-restic -type f | wc -l)"
  echo "bytes=$(find keyparams-restic -type f -printf '%s\n' | awk '{s+=$1} END {printf "%.0f", s}')"
  if [ -f last-success ]; then echo "last_success=$(cat last-success)"; fi
  S=$(ls -t keyparams-restic/snapshots 2>/dev/null | head -n 1)
  if [ -n "$S" ]; then echo "snapshot_epoch=$(stat -c %Y "keyparams-restic/snapshots/$S")"; fi
} > "$M"
tar cf - "$M" keyparams-restic
rm -f "$M"
'@ -replace "`r", ""

$stamp = Get-Date -Format "yyyy-MM-dd_HHmm"
$target = Join-Path $Destination ($Prefix + $stamp)
if (Test-Path $target) {
    throw "Папка $target уже есть — запустите позже."
}
New-Item -ItemType Directory -Path $target | Out-Null
$archive = Join-Path $target "download.tar"

Write-Host "Подключаюсь к $User@$Server — введите пароль SSH, когда он спросит."
$psi = New-Object System.Diagnostics.ProcessStartInfo
$psi.FileName = $Ssh
$psi.Arguments = "-o StrictHostKeyChecking=accept-new $User@$Server sh -s"
$psi.UseShellExecute = $false
$psi.RedirectStandardInput = $true
$psi.RedirectStandardOutput = $true
$proc = [System.Diagnostics.Process]::Start($psi)
$proc.StandardInput.NewLine = "`n"
$proc.StandardInput.Write($remote)
$proc.StandardInput.Close()
$out = [System.IO.File]::Create($archive)
try {
    $proc.StandardOutput.BaseStream.CopyTo($out)
} finally {
    $out.Close()
}
$proc.WaitForExit()
if ($proc.ExitCode -ne 0) {
    Remove-Item -Recurse -Force $target
    throw "Скачать не удалось (ssh завершился с кодом $($proc.ExitCode)). Старые копии не тронуты."
}

& (Join-Path $env:SystemRoot "System32\tar.exe") -xf $archive -C $target
if ($LASTEXITCODE -ne 0) {
    throw "Не удалось распаковать $archive. Старые копии не тронуты."
}
Remove-Item $archive

# Опись с сервера и то, что получилось здесь, должны совпасть.
$manifest = @{}
foreach ($line in Get-Content (Join-Path $target "pull-manifest.txt")) {
    $key, $value = $line -split "=", 2
    $manifest[$key] = $value
}
$files = @(Get-ChildItem -Recurse -File (Join-Path $target "keyparams-restic"))
$bytes = ($files | Measure-Object -Property Length -Sum).Sum
if ($null -eq $bytes) { $bytes = 0 }
$serverFiles = [int64]$manifest["files"]
$serverBytes = [int64]$manifest["bytes"]
Write-Host ("На сервере: {0} файлов, {1:N0} байт. Скачано: {2} файлов, {3:N0} байт." -f `
    $serverFiles, $serverBytes, $files.Count, $bytes)
if ($files.Count -ne $serverFiles -or $bytes -ne $serverBytes) {
    Rename-Item $target ((Split-Path -Leaf $target) + "-НЕПОЛНАЯ")
    Write-Banner @("КОПИЯ СКАЧАЛАСЬ НЕ ПОЛНОСТЬЮ", "Папка помечена -НЕПОЛНАЯ, старые копии не тронуты.") "Red"
    exit 1
}
Write-Host "Копия скачана полностью: $target" -ForegroundColor Green

# Хранится $Keep последних полных копий.
$old = Get-ChildItem -Directory $Destination |
    Where-Object { $_.Name -match '^restic-\d{4}-\d{2}-\d{2}_\d{4}$' } |
    Sort-Object Name -Descending |
    Select-Object -Skip $Keep
foreach ($dir in $old) {
    Remove-Item -Recurse -Force $dir.FullName
    Write-Host "Удалена старая копия: $($dir.Name)"
}

# Когда на сервере последний раз прошло копирование.
$last = $null
if ($manifest["last_success"]) {
    $last = [datetime]::Parse($manifest["last_success"], [Globalization.CultureInfo]::InvariantCulture,
        [Globalization.DateTimeStyles]::AdjustToUniversal -bor [Globalization.DateTimeStyles]::AssumeUniversal)
} elseif ($manifest["snapshot_epoch"]) {
    # Отметки last-success ещё нет — время самой свежей копии в хранилище.
    $last = [DateTimeOffset]::FromUnixTimeSeconds([int64]$manifest["snapshot_epoch"]).UtcDateTime
}
if ($null -eq $last) {
    Write-Banner @("НА СЕРВЕРЕ НЕТ НИ ОДНОЙ УСПЕШНОЙ КОПИИ") "Red"
    exit 1
}
$age = (Get-Date).ToUniversalTime() - $last
$local = $last.ToLocalTime().ToString("dd.MM.yyyy HH:mm")
if ($age.TotalHours -gt $MaxAgeHours) {
    Write-Banner @(
        "ВНИМАНИЕ: КОПИРОВАНИЕ НА СЕРВЕРЕ НЕ ПРОХОДИТ",
        "Последняя успешная копия: $local ($([int]$age.TotalHours) ч назад)",
        "Смотрите ~/.config/keyparams-backup/backup.log на сервере."
    ) "Red"
    exit 2
}
Write-Host ("Последнее успешное копирование на сервере: {0} ({1:N0} ч назад)." -f $local, $age.TotalHours) -ForegroundColor Green
