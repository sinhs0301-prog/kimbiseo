# 김비서 설치 일꾼 — 설치 창(install.ps1)이 창 없이 띄운다. 직접 누르는 파일이 아님.
#   0.1.12~ 파이썬 준비 단계가 '멈춘 것처럼' 되지 않게: 받기는 30초 동안 아무것도 안 오면 끊고 받은 만큼에서 이어 받음(거의 못 받은 시도 5번이면 그만둠),
#   받는 양·빠르기·지난 시간을 0.5초마다 상태 파일에 적음, 실패하면 까닭(주소 못 찾음·막힘·응답 없음·인증서·거절)을 쉬운 말로.
#   같은 설치 폴더에 설치가 이미 돌고 있으면(창을 두 번 띄움) 겹쳐 돌지 않고 알려 줌.
#   1) 공식 파이썬(embeddable, 판 고정 + sha256) 을 받아 <설치 폴더>\runtime\python-app 에 풀고 pip 를 넣음
#   2) 그 파이썬으로 setup_core.py 를 돌림(나머지 전부). 상태는 -Status 파일(JSON)에, 기록은 <자료>\logs\install.log 에.
param(
  [Parameter(Mandatory = $true)][string]$Prefix,
  [Parameter(Mandatory = $true)][string]$DataDir,
  [Parameter(Mandatory = $true)][string]$Status,
  [string]$Source = "",
  [switch]$LocalBrain,
  [ValidateSet("", "E4B", "E2B")][string]$Gemma = "",
  [string]$DesktopDir = "",
  [string]$StartMenuDir = "",
  [string]$RegKey = "KimBiseo",
  [string]$DisplayName = "김비서",
  [string]$PacksCatalog = "<none>",
  [switch]$NoShortcuts,
  [switch]$NoRegister,
  [switch]$PetOnly,              # 펫 실행 틀만 다시 설치(설치 창 '펫 다시 받기')
  [string]$PetFile = "",         # 사용자가 브라우저로 직접 받아 둔 펫 실행 틀 압축 파일('직접 넣기')
  [string]$Lang = "ko"           # 설치 화면 언어(0.1.18~): ko | en | ja | zh
)
$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
if (-not $Source) { $Source = Split-Path -Parent $PSScriptRoot }
$utf8 = New-Object System.Text.UTF8Encoding($false)

# 설치 화면 언어 — 사전은 본체와 같은 app\i18n\<언어>.json. 한국어면 그대로.
$wantLang = [string]$Lang          # ★ $script:lang 과 $Lang 은 같은 변수(스크립트 범위) — 덮어쓰기 전에 따로 둔다
$script:lang = "ko"
foreach ($c in @("ko", "en", "ja", "zh")) { if ($wantLang.Trim().ToLower().StartsWith($c)) { $script:lang = $c } }
$script:dict = @{}
if ($script:lang -ne "ko") {
  try {
    $o = [IO.File]::ReadAllText((Join-Path $Source "app\i18n\$($script:lang).json"), $utf8) | ConvertFrom-Json
    foreach ($pr in $o.PSObject.Properties) { if ($pr.Value -is [string]) { $script:dict[$pr.Name] = $pr.Value } }
  } catch { }
}
function T([string]$s, [object[]]$a = $null) {
  $t = if ($script:dict.ContainsKey($s)) { [string]$script:dict[$s] } else { $s }
  if ($a -and $a.Count) { try { $t = $t -f $a } catch { } }
  return $t
}
$logDir = Join-Path $DataDir "logs"
New-Item -ItemType Directory -Force -Path $logDir, (Split-Path -Parent $Status), (Join-Path $Prefix "install\downloads") | Out-Null
$log = Join-Path $logDir "install.log"
function Log([string]$m) { [IO.File]::AppendAllText($log, (Get-Date -Format "yyyy-MM-dd HH:mm:ss ") + $m + "`r`n", $utf8) }

$steps = @(@("python", (T "파이썬 준비")), @("plan", (T "이 PC 사양 확인")), @("files", (T "프로그램 파일")), @("packages", (T "파이썬 부품")),
           @("brain", (T "두뇌 프로그램")), @("models", (T "모델(두뇌·귀·목소리)")), @("pet", (T "펫")), @("finish", (T "바탕화면 아이콘·마무리")))
$script:t0 = Get-Date
function Write-Status([string]$state, [string]$text, [double]$prog, $err) {
  $list = @()
  foreach ($s in $steps) {
    $st = if ($s[0] -eq "python") { $state } else { "기다림" }
    $list += [ordered]@{ id = $s[0]; "이름" = $s[1]; "상태" = $st; "글" = "" }
  }
  $o = [ordered]@{ "단계" = $list; "지금" = "python"; "글" = $text; "진행" = $prog; "전체" = [math]::Round($prog * 0.02, 1); "끝" = [bool]$err;
                   "성공" = $false; "오류" = $err; "시각" = (Get-Date -Format "HH:mm:ss");
                   "경과_초" = [int]((Get-Date) - $script:t0).TotalSeconds }
  $json = $o | ConvertTo-Json -Depth 6
  try {
    [IO.File]::WriteAllText($Status + ".tmp", $json, $utf8)
    Move-Item -Force ($Status + ".tmp") $Status
  } catch { }   # 설치 창이 읽는 순간과 겹치면 다음 번에 씀
}
function Size-Text([long]$n) { if ($n -ge 1MB) { "{0:N1}MB" -f ($n / 1MB) } else { "{0:N0}KB" -f ($n / 1KB) } }

# 받기 실패 까닭 → 쉬운 말
function Why-Text($ex) {
  $st = ""; $code = 0
  if ($ex -is [Net.WebException]) {
    $st = [string]$ex.Status
    if ($ex.Response) { try { $code = [int]$ex.Response.StatusCode } catch { } }
  }
  $m = [string]$ex.Message
  # 말은 설치 본체(get_models.py WHY)와 같게 — 어려운 낱말 없이
  if ($st -eq "NameResolutionFailure" -or $st -eq "ProxyNameResolutionFailure") { return (T "인터넷 연결이 안 돼요(받는 곳 주소를 찾지 못했어요).") }
  if ($st -eq "TrustFailure" -or $st -eq "SecureChannelFailure" -or $m -match "SSL|TLS|인증서|certificate") { return (T "보안 연결을 확인하지 못했어요(백신이나 회사·학교 인터넷이 연결을 검사하거나, PC 시계가 틀렸을 수 있어요).") }
  if ($st -eq "Timeout" -or $m -match "시간이 초과|시간을 초과|timed out|timeout") { return (T "받는 곳이 응답하지 않아요(인터넷이 느리거나 막혀 있어요).") }
  if ($st -eq "ConnectFailure") { return (T "인터넷에서 받는 길이 막혀 있어요(회사·학교 인터넷이나 백신 때문일 수 있어요).") }
  if ($code -eq 403 -or $code -eq 407) { return (T "받는 곳에서 거절했어요(회사·학교 인터넷이 막았을 수 있어요).") }
  if ($code -eq 404) { return (T "받을 파일을 찾지 못했어요. 새 설치 파일을 받아 주세요.") }
  if ($code -ge 500) { return (T "받는 곳에 잠깐 문제가 있어요. 조금 뒤에 다시 해 주세요.") }
  if ($st -eq "ConnectionClosed" -or $st -eq "ReceiveFailure" -or $m -match "끊|closed|reset|모자람") { return (T "받는 도중에 끊겼어요.") }
  return (T "인터넷 연결에 문제가 있어요.")
}

# 한 번 받기(이어 받기): 윈도우의 보안 연결·프록시 설정을 그대로 쓰고, 60초 동안 아무것도 안 오면 끊음. 진행을 상태 파일에 적음
function Get-Part([string]$url, [string]$part, [long]$size, [string]$label, [int]$try) {
  $have = 0L
  if (Test-Path $part) { $have = (Get-Item $part).Length }
  if ($size -gt 0 -and $have -gt $size) { Remove-Item -Force $part; $have = 0L }
  if ($size -gt 0 -and $have -eq $size) { return }
  $req = [Net.HttpWebRequest]::Create($url)
  $req.UserAgent = "KimBiseo-installer/1"
  $req.Timeout = 30000               # 연결·머리글까지 30초
  $req.ReadWriteTimeout = 30000      # 받는 도중 30초 동안 아무것도 안 오면 끊고 이어 받음(멈춘 회선에서 끝없이 기다리지 않게)
  $req.AllowAutoRedirect = $true
  try { if ($req.Proxy) { $req.Proxy.Credentials = [Net.CredentialCache]::DefaultNetworkCredentials } } catch { }      # 회사망 프록시(윈도우 로그인으로 인증)
  if ($have -gt 0) { $req.AddRange([long]$have) }
  $resp = $req.GetResponse()
  try {
    if ($have -gt 0 -and [int]$resp.StatusCode -ne 206) { $have = 0L }      # 이어 받기를 안 받는 서버 → 처음부터
    $mode = if ($have -gt 0) { [IO.FileMode]::Append } else { [IO.FileMode]::Create }
    $in = $resp.GetResponseStream()
    $out = [IO.File]::Open($part, $mode, [IO.FileAccess]::Write, [IO.FileShare]::Read)
    try {
      $buf = New-Object byte[] 262144
      $t0 = Get-Date; $got0 = $have; $last = Get-Date
      while (($n = $in.Read($buf, 0, $buf.Length)) -gt 0) {
        $out.Write($buf, 0, $n); $have += $n
        if (((Get-Date) - $last).TotalMilliseconds -ge 500) {
          $last = Get-Date
          $rate = ($have - $got0) / [math]::Max(0.001, ((Get-Date) - $t0).TotalSeconds)
          $pct = if ($size -gt 0) { [math]::Min(99, 100.0 * $have / $size) } else { 10 }
          $msg = if ($size -gt 0) { T '{0} 받는 중 {1} / {2}' @($label, (Size-Text $have), (Size-Text $size)) } else { T '{0} 받는 중 {1}' @($label, (Size-Text $have)) }
          $msg += " " + (T '· {0}/초' @((Size-Text ([long]$rate))))
          if ($try -gt 1) { $msg += " " + (T '({0} 번째 시도)' @($try)) }
          Write-Status "하는 중" $msg $pct $null
        }
      }
    } finally { $out.Close(); $in.Close() }
  } finally { $resp.Close() }
  if ($size -gt 0 -and $have -ne $size) { throw "받은 크기가 모자람($have/$size)" }
}

function Get-Checked([string]$url, [string]$dest, [string]$sha, [long]$size, [string]$label) {
  if ((Test-Path $dest) -and ((Get-FileHash -Algorithm SHA256 $dest).Hash.ToLower() -eq $sha)) { Log "  $label 이미 받아 둠(sha256 맞음)"; return }
  $part = $dest + ".part"
  $script:lastWhy = "인터넷 연결에 문제가 있어요."
  $stuck = 0; $hashBad = 0
  for ($i = 1; $i -le 30 -and $stuck -lt 5; $i++) {      # 받아지는 동안은 계속 이어 받고, 거의 못 받은(128KB 미만) 시도가 5번 이어지면 그만둠
    $before = 0L; if (Test-Path $part) { $before = (Get-Item $part).Length }
    try {
      Write-Status "하는 중" ((T '{0} 받는 중' @($label)) + $(if ($i -gt 1) { " " + (T '({0} 번째 시도)' @($i)) })) 5 $null
      Get-Part $url $part $size $label $i
      Write-Status "하는 중" (T '{0} 확인 중' @($label)) 99 $null
      $h = (Get-FileHash -Algorithm SHA256 $part).Hash.ToLower()
      if ($h -ne $sha) { Remove-Item -Force $part; throw "HASH:sha256 다름 $h" }
      Move-Item -Force $part $dest
      Log "  받음 $label sha256 맞음($i 번째 시도)"
      return
    } catch {
      $ex = $_.Exception
      while ($ex.InnerException -and -not ($ex -is [Net.WebException])) { $ex = $ex.InnerException }
      $after = 0L; if (Test-Path $part) { $after = (Get-Item $part).Length }
      if (($after - $before) -ge 131072) { $stuck = 0 } else { $stuck++ }      # 128KB 도 못 늘었으면 진전 없는 시도로 침
      if ("$($_.Exception.Message)" -like "HASH:*") {
        $script:lastWhy = T "받은 파일이 원본과 달라요(백신이나 회사 인터넷이 파일을 바꾸는 것 같아요)."
        $hashBad++
        if ($hashBad -ge 2) { Log "  $label 두 번 다 원본과 다름 → 그만둠"; throw "HASH:$label 이(가) 두 번 다 원본과 다름" }      # 새로 받아도 같으면 더 해도 같음
      }
      else { $script:lastWhy = Why-Text $ex }
      Log "  $label 받기 $i 번째 실패: $($ex.Message) [$([string]$ex.Status)] 받은 것 $after 바이트 — $($script:lastWhy)"
      $code = 0
      if ($ex -is [Net.WebException] -and $ex.Response) { try { $code = [int]$ex.Response.StatusCode } catch { } }
      # 다시 해도 같은 것: 없음(404)은 바로, 거절(403·407)은 두 번째에 그만둠 · 거의 못 받은 시도가 5번 이어져도 그만둠
      if ($code -eq 404 -or (($code -eq 403 -or $code -eq 407) -and $i -ge 2) -or $stuck -ge 5) { break }
      $wait = [int][math]::Min(20, [math]::Pow(2, [math]::Max(1, $stuck)))
      Write-Status "하는 중" (T '{0}: {1} {2}초 뒤 이어서 받아요({3} 번째 시도)' @($label, $script:lastWhy, $wait, $i)) 5 $null
      Start-Sleep -Seconds $wait
    }
  }
  throw "NET:$label"
}

$rt = [IO.File]::ReadAllText((Join-Path $PSScriptRoot "runtimes.json"), $utf8) | ConvertFrom-Json
$pyDir = Join-Path $Prefix "runtime\python-app"
$py = Join-Path $pyDir "python.exe"
$mark = Join-Path $pyDir "kimbiseo_python.txt"
$want = $rt.python.version + "+pip" + $rt.pip.version

# 같은 설치 폴더에 설치가 이미 돌고 있으면 겹쳐 돌지 않음(설치 창을 두 번 띄웠을 때 파일을 서로 지우며 멈추는 일 막기)
$lockName = "KimBiseoInstall_" + ([BitConverter]::ToString((New-Object Security.Cryptography.SHA1Managed).ComputeHash($utf8.GetBytes($Prefix.ToLower()))).Replace("-", "").Substring(0, 16))
$script:lock = New-Object Threading.Mutex($false, $lockName)
$gotLock = $false
try { $gotLock = $script:lock.WaitOne(0) } catch [Threading.AbandonedMutexException] { $gotLock = $true }
if (-not $gotLock) {
  # 먼저 도는 설치의 상태 파일은 건드리지 않음 — 코드 3 으로 끝내면 설치 창이 '이미 진행 중'이라고 알려 줌
  Log "!!!! 겹쳐 실행: 같은 설치 폴더의 설치가 이미 돌고 있음 → 그만둠(일꾼 PID $PID)"
  exit 3
}

try {
  Log "==== 설치 시작(일꾼 PID $PID) 설치 폴더 $Prefix · 자료 $DataDir · 소스 $Source"
  Log ("환경: 윈도우 " + [Environment]::OSVersion.Version + " · 파워셸 " + $PSVersionTable.PSVersion + " · 설치 폴더 경로 길이 " + $Prefix.Length + " · 남은 디스크 " + (Size-Text (New-Object IO.DriveInfo([IO.Path]::GetPathRoot($Prefix))).AvailableFreeSpace))
  if ((Test-Path $py) -and (Test-Path $mark) -and ([IO.File]::ReadAllText($mark).Trim() -eq $want)) {
    Log "파이썬: 이미 있음($want)"
  } else {
    Write-Status "하는 중" (T '공식 파이썬 {0} 받는 중' @($rt.python.version)) 5 $null
    $zip = Join-Path $Prefix ("install\downloads\" + [IO.Path]::GetFileName($rt.python.url))
    Get-Checked $rt.python.url $zip $rt.python.sha256 $rt.python.size (T '파이썬 {0}' @($rt.python.version))
    $md5 = (Get-FileHash -Algorithm MD5 $zip).Hash.ToLower()
    if ($md5 -ne $rt.python.md5_python_org) { throw "HASH:파이썬 md5 가 python.org 값과 다름" }
    Write-Status "하는 중" (T "파이썬을 설치 폴더에 푸는 중") 60 $null
    Log "파이썬: 푸는 중 → $pyDir"
    if (Test-Path $pyDir) {
      try { Remove-Item -Recurse -Force $pyDir }
      catch { throw "BUSY:$($_.Exception.Message)" }      # 김비서가 켜져 있거나 백신이 파일을 잡고 있음
    }
    Add-Type -AssemblyName System.IO.Compression.FileSystem
    [IO.Compression.ZipFile]::ExtractToDirectory($zip, $pyDir)
    $pth = "python311.zip`r`n.`r`nLib\site-packages`r`n..\..\src`r`n# 김비서: 위 줄 = 설치 폴더의 src(본체 코드). 환경변수·레지스트리는 보지 않음`r`nimport site`r`n"
    [IO.File]::WriteAllText((Join-Path $pyDir $rt.python.pth), $pth, $utf8)
    $whl = Join-Path $Prefix ("install\downloads\" + [IO.Path]::GetFileName($rt.pip.url))
    Get-Checked $rt.pip.url $whl $rt.pip.sha256 $rt.pip.size (T 'pip {0}' @($rt.pip.version))
    Write-Status "하는 중" (T "pip 를 넣는 중") 90 $null
    [IO.Compression.ZipFile]::ExtractToDirectory($whl, (Join-Path $pyDir "Lib\site-packages"))
    [IO.File]::WriteAllText($mark, $want, $utf8)
    Log "파이썬: 풀고 pip 넣음($want)"
  }
  Write-Status "됨" (T "파이썬 준비 끝") 100 $null
} catch {
  $m = $_.Exception.Message
  Log "!!!! 파이썬 준비 실패: $m"
  $why = if ($m -like "NET:*") { T '파이썬을 받지 못했어요. {0}' @($script:lastWhy) }
         elseif ($m -like "HASH:*") { T "받은 파이썬이 원본과 달라요. 백신이나 회사 인터넷이 받는 파일을 바꾸는 것 같아요 — 다른 인터넷(휴대폰 핫스팟 등)으로 바꿔서 다시 해 보세요." }
         elseif ($m -like "BUSY:*") { T "설치 폴더의 예전 파이썬을 지우지 못했어요. 김비서가 켜져 있으면 끄고, 백신 알림을 확인해 주세요." }
         elseif ($m -match "경로|path|PathTooLong") { T "설치 폴더 경로가 너무 길거나 쓸 수 없는 곳이에요. 설치 위치를 짧은 폴더(예: C 드라이브 바로 아래 폴더)로 바꿔 주세요." }
         elseif ($m -match "공간|space") { T "디스크 공간이 모자라요. 공간을 비워 주세요." }
         elseif ($m -match "거부|denied|Unauthorized") { T "설치 폴더에 파일을 쓰지 못했어요. 백신 알림을 확인하거나 설치 위치를 바꿔 주세요." }
         else { T "파이썬을 준비하지 못했어요." }
  Write-Status "실패" $why 0 ([ordered]@{ "단계" = (T "파이썬 준비"); "이유" = $why; "자세히" = $m; "기록" = $log })
  exit 1
}

$args2 = @("-B", "-X", "utf8", (Join-Path $Source "installer\setup_core.py"), "install", "--prefix", $Prefix, "--data", $DataDir,
           "--status", $Status, "--source", $Source, "--reg-key", $RegKey, "--display-name", $DisplayName)
if ($PetOnly) {
  # 펫만: 이미 깔린 설치 폴더의 설치 본체로(없으면 받은 폴더 것으로)
  $core = Join-Path $Prefix "src\installer\setup_core.py"
  if (-not (Test-Path $core)) { $core = Join-Path $Source "installer\setup_core.py" }
  $args2 = @("-B", "-X", "utf8", $core, "pet-install", "--prefix", $Prefix, "--data", $DataDir, "--status", $Status)
  if ($PetFile) { $args2 += @("--file", $PetFile) }
  Log "펫만 다시 설치$(if ($PetFile) { ' (받아 둔 파일)' })"
}
if ($LocalBrain) { $args2 += "--local-brain" }
if ($Gemma) { $args2 += @("--gemma", $Gemma) }
if ($DesktopDir) { $args2 += @("--desktop-dir", $DesktopDir) }
if ($StartMenuDir) { $args2 += @("--startmenu-dir", $StartMenuDir) }
if ($PacksCatalog -ne "<none>") { $args2 += @("--packs-catalog", $PacksCatalog) }
if ($script:lang -ne "ko") { $args2 += @("--lang", $script:lang) }
if ($NoShortcuts) { $args2 += "--no-shortcuts" }
if ($NoRegister) { $args2 += "--no-register" }
# 인자를 안전하게 따옴표로 묶어 넘김(한글·빈칸 경로)
$q = ($args2 | ForEach-Object { '"' + ($_ -replace '"', '\"') + '"' }) -join " "
$psi = New-Object System.Diagnostics.ProcessStartInfo
$psi.FileName = $py
$psi.Arguments = $q
$psi.UseShellExecute = $false
$psi.CreateNoWindow = $true
$psi.RedirectStandardOutput = $true
$psi.RedirectStandardError = $true
$psi.StandardOutputEncoding = $utf8
$psi.StandardErrorEncoding = $utf8
$psi.EnvironmentVariables["PYTHONUTF8"] = "1"
$psi.EnvironmentVariables["PYTHONIOENCODING"] = "utf-8"
$p = [Diagnostics.Process]::Start($psi)
Log "설치 본체 PID $($p.Id)"
$errTask = $p.StandardError.ReadToEndAsync()
while (-not $p.StandardOutput.EndOfStream) { $null = $p.StandardOutput.ReadLine() }
$p.WaitForExit()
$errText = $errTask.Result
if ($errText) { Log ("설치 본체 오류 출력: " + $errText.Substring([math]::Max(0, $errText.Length - 2000))) }
Log "설치 본체 끝(코드 $($p.ExitCode))"
if ($p.ExitCode -ne 0) {   # 설치 본체가 상태를 못 남기고 끝났으면(파이썬 오류 등) 여기서 실패로 적음
  $done = $false
  try { $done = ([IO.File]::ReadAllText($Status, $utf8) | ConvertFrom-Json)."끝" } catch { }
  if (-not $done) {
    $why = T "설치 도중 프로그램이 멈췄어요. '다시 하기'를 눌러 주세요. 계속되면 기록 파일을 보내 주세요."
    $tail = if ($errText) { $errText.Substring([math]::Max(0, $errText.Length - 600)) } else { "코드 $($p.ExitCode)" }
    Write-Status "됨" $why 100 ([ordered]@{ "단계" = (T "설치"); "이유" = $why; "자세히" = $tail; "기록" = $log })
  }
}
exit $p.ExitCode
