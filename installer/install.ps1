# 김비서 설치 창 — '설치.bat' 이 창 없이(명령창 숨김) 띄운다. 사용자는 '설치' 단추 하나만 누르면 됨.
#   실제 일은 worker.ps1(파이썬 준비) → setup_core.py(나머지)가 창 없이 하고, 이 창은 상태 파일을 0.5초마다 읽어 보여 준다.
#   시험·고급: -Prefix 설치폴더 -DataDir 자료폴더 -DesktopDir 바탕화면 -StartMenuDir 시작메뉴 -RegKey 이름 -DisplayName 이름
#             -PacksCatalog 옷목록주소 -Auto(창이 뜨면 바로 설치) -ShotDir 폴더(창 그림을 단계마다 저장)
#             -Gemma E2B(이 PC 두뇌를 받을 때 작은 판 — 기본 E4B)
#             -TestOffScreen(시험용: 창을 화면 밖에 띄움 — 자동 시험이 사용자 화면을 가리지 않게. 창 그림(-ShotDir)은 그대로 찍힘)
param(
  [string]$Prefix = "",
  [string]$DataDir = "",
  [string]$DesktopDir = "",
  [string]$StartMenuDir = "",
  [string]$RegKey = "KimBiseo",
  [string]$DisplayName = "김비서",
  [string]$PacksCatalog = "<none>",
  [switch]$Auto,
  [ValidateSet("", "E4B", "E2B")][string]$Gemma = "",
  [string]$ShotDir = "",
  [string]$Lang = "",
  [switch]$TestOffScreen
)
$ErrorActionPreference = "Stop"
Add-Type -AssemblyName System.Windows.Forms, System.Drawing
[Windows.Forms.Application]::EnableVisualStyles()
$utf8 = New-Object System.Text.UTF8Encoding($false)
$Source = Split-Path -Parent $PSScriptRoot
if (-not $Prefix) { $Prefix = Join-Path $env:LOCALAPPDATA "KimBiseo" }
if (-not $DataDir) { $DataDir = Join-Path $env:APPDATA "KimBiseo" }

# ---------------------------------------------------------------- 언어(0.1.18~)
#   처음 설치 때 고른다. 이미 쓰던 사람은 설정의 '언어'를 그대로 보여 준다. 고른 언어는 설치 본체가 settings.json 에 적는다.
function Norm-Lang([string]$code) {
  $c = $code.Trim().ToLower()
  if ($c.StartsWith("en")) { return "en" }
  if ($c.StartsWith("ja")) { return "ja" }
  if ($c.StartsWith("zh")) { return "zh" }
  if ($c.StartsWith("ko")) { return "ko" }
  return ""
}
$script:lang = Norm-Lang $Lang
if (-not $script:lang) {
  try {
    $sp = Join-Path $DataDir "settings.json"
    if (Test-Path $sp) { $script:lang = Norm-Lang ([string]([IO.File]::ReadAllText($sp, $utf8) | ConvertFrom-Json)."언어") }
  } catch { }
}
if (-not $script:lang) {
  $script:lang = switch ([System.Globalization.CultureInfo]::CurrentUICulture.TwoLetterISOLanguageName) { "ko" { "ko" } "ja" { "ja" } "zh" { "zh" } default { "en" } }
}
$script:dict = @{}
function Load-Dict {
  $script:dict = @{}
  if ($script:lang -eq "ko") { return }
  try {
    $o = [IO.File]::ReadAllText((Join-Path $Source "app\i18n\$($script:lang).json"), $utf8) | ConvertFrom-Json
    foreach ($pr in $o.PSObject.Properties) { if ($pr.Value -is [string]) { $script:dict[$pr.Name] = $pr.Value } }
  } catch { }
}
Load-Dict
function T([string]$s, [object[]]$a = $null) {
  $t = if ($script:dict.ContainsKey($s)) { [string]$script:dict[$s] } else { $s }
  if ($a -and $a.Count) { try { $t = $t -f $a } catch { } }
  return $t
}
$script:ui = @()       # 화면 글 — 언어를 바꾸면 이 목록을 다시 씀
function Set-K($ctl, [string]$key, $a = $null, [string]$pre = "", [string]$post = "") {
  $script:ui += @{ ctl = $ctl; key = $key; a = $a; pre = $pre; post = $post }
  $ctl.Text = $pre + (T $key $a) + $post
}
$script:appName = if ($DisplayName -eq "김비서") { T "김비서" } else { $DisplayName }
$script:status = Join-Path $Prefix "install\status.json"
$script:worker = $null
$script:result = $null

# ---------------------------------------------------------------- 사양(창에 보여 주기만 — 실제 구성은 setup_core/plan.py 가 다시 정함)
function Get-Spec {
  $g = $null; $mib = 0
  $fake = $env:KIMBISEO_FAKE_GPU
  if ($fake) {
    if ($fake.Trim().ToLower() -ne "none") { $i = $fake.LastIndexOf(":"); $g = $fake.Substring(0, $i); $mib = [int]$fake.Substring($i + 1) }
  } else {
    $smi = Get-Command nvidia-smi -ErrorAction SilentlyContinue
    if ($smi) {
      try {
        $line = (& $smi.Source --query-gpu=name,memory.total --format=csv,noheader,nounits | Select-Object -First 1)
        $p = $line.Split(","); $g = $p[0].Trim(); $mib = [int][double]$p[1].Trim()
      } catch { }
    }
  }
  $ram = [math]::Round((Get-CimInstance Win32_ComputerSystem).TotalPhysicalMemory / 1GB, 1)
  if ($env:KIMBISEO_FAKE_RAM_GB) { $ram = [double]$env:KIMBISEO_FAKE_RAM_GB }
  $root = [IO.Path]::GetPathRoot($Prefix)
  $free = [math]::Round((New-Object IO.DriveInfo($root)).AvailableFreeSpace / 1GB, 1)
  if ($env:KIMBISEO_FAKE_DISK_GB) { $free = [double]$env:KIMBISEO_FAKE_DISK_GB }
  $hint = ""
  if (-not $g) { $kind = "그래픽카드 없음"; $need = 9 }
  elseif ($mib -ge 9216) { $kind = "그래픽 메모리 넉넉함"; $need = 22 }
  elseif ($mib -ge 6144) { $kind = "그래픽 메모리 8GB 이하"; $need = 22 }
  else { $kind = "그래픽 메모리 6GB 미만"; $need = 16 }
  return @{ gpu = $g; mib = $mib; ram = $ram; free = $free; kind = $kind; hint = $hint; need = $need }
}
$spec = Get-Spec

# ---------------------------------------------------------------- 창(운영판과 같은 색: 검은 바탕 + 분홍 하나)
$C_BG = [Drawing.Color]::FromArgb(11, 12, 15); $C_CARD = [Drawing.Color]::FromArgb(21, 23, 28); $C_LINE = [Drawing.Color]::FromArgb(38, 41, 50)
$C_TEXT = [Drawing.Color]::FromArgb(236, 236, 241); $C_MUTED = [Drawing.Color]::FromArgb(139, 143, 154)
$C_ACC = [Drawing.Color]::FromArgb(255, 0, 90); $C_ACCINK = [Drawing.Color]::FromArgb(255, 92, 138)
$C_OK = [Drawing.Color]::FromArgb(86, 211, 100); $C_BAD = [Drawing.Color]::FromArgb(255, 138, 138)
$font = New-Object Drawing.Font("Malgun Gothic", 10)
$bold = New-Object Drawing.Font("Malgun Gothic", 10, [Drawing.FontStyle]::Bold)
$form = New-Object Windows.Forms.Form
$form.Text = (T '{0} 설치' @($script:appName))
$form.ClientSize = New-Object Drawing.Size(720, 676)
$form.FormBorderStyle = "FixedDialog"; $form.MaximizeBox = $false
$form.StartPosition = "CenterScreen"
if ($TestOffScreen) { $form.StartPosition = "Manual"; $form.Location = New-Object Drawing.Point(-30000, -30000); $form.ShowInTaskbar = $false }
$form.Font = $font
$form.BackColor = $C_BG; $form.ForeColor = $C_TEXT
$ico = Join-Path $Source "pet\renderer\img\icon.ico"
if (Test-Path $ico) { $form.Icon = New-Object Drawing.Icon($ico) }

function Add-Label($text, $x, $y, $w, $h, $f = $font, $color = $null) {
  $l = New-Object Windows.Forms.Label
  $l.Text = $text; $l.Location = New-Object Drawing.Point($x, $y); $l.Size = New-Object Drawing.Size($w, $h); $l.Font = $f
  if ($color) { $l.ForeColor = $color }
  $form.Controls.Add($l); return $l
}
$t = Add-Label "" 24 14 600 36 (New-Object Drawing.Font("Malgun Gothic", 18, [Drawing.FontStyle]::Bold))
Set-K $t '{0} 설치' @($script:appName)
$accLine = New-Object Windows.Forms.Panel
$accLine.Location = New-Object Drawing.Point(26, 50); $accLine.Size = New-Object Drawing.Size(36, 3); $accLine.BackColor = $C_ACC
$form.Controls.Add($accLine)
$null = Add-Label (T "말로 부르는 내 PC 비서와 바탕화면 펫을 이 PC 에 설치해요. '설치'를 누르면 나머지는 저절로 해요.") 26 60 640 22 $font $C_MUTED
# 언어 고르기 — 처음 설치 때. 바꾸면 이 창의 글만 그 자리에서 바뀐다(고른 언어는 설치 본체가 settings.json 에 적음).
$script:langCodes = @("ko", "en", "ja", "zh")
$langLbl = Add-Label (T "언어") 566 16 44 22 $font $C_MUTED
$langBox = New-Object Windows.Forms.ComboBox
$langBox.DropDownStyle = "DropDownList"; $langBox.Font = $font
$langBox.Location = New-Object Drawing.Point(610, 13); $langBox.Size = New-Object Drawing.Size(86, 26)
foreach ($c in @("한국어", "English", "日本語", "中文")) { [void]$langBox.Items.Add($c) }
$langBox.SelectedIndex = [array]::IndexOf($script:langCodes, $script:lang)
$form.Controls.Add($langBox)

# '이 PC' 칸 — 진한 판 + 제목(테두리 상자 대신: 어두운 바탕에서 윈도우 기본 테두리가 밝게 튀어서)
$box = New-Object Windows.Forms.Panel
$box.Location = New-Object Drawing.Point(24, 88); $box.Size = New-Object Drawing.Size(672, 184); $box.BackColor = $C_CARD
$form.Controls.Add($box)
$boxT = New-Object Windows.Forms.Label
$boxT.Font = $bold; $boxT.ForeColor = $C_ACCINK; $boxT.Location = New-Object Drawing.Point(14, 8); $boxT.Size = New-Object Drawing.Size(300, 20)
$box.Controls.Add($boxT); Set-K $boxT "이 PC"
$specLbl = New-Object Windows.Forms.Label
$specLbl.Font = $font; $specLbl.ForeColor = $C_TEXT; $specLbl.Location = New-Object Drawing.Point(14, 30); $specLbl.Size = New-Object Drawing.Size(645, 148)
$box.Controls.Add($specLbl)
function Update-Spec {
  $gtext = if ($spec.gpu) { "$($spec.gpu) ($([math]::Round($spec.mib / 1024)) GB)" } else { T "엔비디아 그래픽카드 없음" }
  $hint = if (-not $spec.gpu) { T "목소리는 윈도우 음성, 받아쓰기는 작은 귀(CPU). 두뇌는 구독 클로드·GPT 또는 '내 로컬 AI 주소'를 권해요." }
    elseif ($spec.mib -ge 6144) { T '받아쓰기·김비서 목소리를 그래픽카드로 해요. {0}' @((T "클로드 코드·Codex 로그인이 있으면 그것을 두뇌로 쓰고(Gemma 안 받음), 없으면 Gemma 를 받아요.")) }
    else { T "받아쓰기는 그래픽카드, 목소리는 윈도우 음성. 두뇌는 구독 클로드·GPT 또는 바깥 AI 를 권해요." }
  $specLbl.Text = (T '그래픽카드: {0}' @($gtext)) + "`r`n" + (T '메모리(램): {0} GB · 남은 디스크: {1} GB' @($spec.ram, $spec.free)) + "`r`n" +
    (T '추천 구성: {0}' @((T $spec.kind))) + "`r`n" + $hint
}
Update-Spec

$chkBrain = New-Object Windows.Forms.CheckBox
$chkBrain.Text = ""
Set-K $chkBrain "그래도 이 PC 에서 두뇌 돌리기(느림 — 약 5GB 를 더 받아요)"
$chkBrain.Location = New-Object Drawing.Point(26, 278); $chkBrain.Size = New-Object Drawing.Size(620, 24)
$chkBrain.FlatStyle = "Flat"; $chkBrain.ForeColor = $C_TEXT
$chkBrain.Visible = ($spec.kind -eq "그래픽카드 없음" -or $spec.kind -eq "그래픽 메모리 6GB 미만")
$form.Controls.Add($chkBrain)

$locLbl = Add-Label "" 26 308 560 22 $font $C_MUTED
Set-K $locLbl '설치 위치: {0}' @($Prefix)
function Set-BtnStyle($b, [bool]$primary) {
  $b.FlatStyle = "Flat"; $b.UseVisualStyleBackColor = $false; $b.Cursor = [Windows.Forms.Cursors]::Hand
  $b.FlatAppearance.BorderSize = 1
  if ($primary) {
    $b.BackColor = $C_ACC; $b.ForeColor = [Drawing.Color]::White; $b.FlatAppearance.BorderColor = $C_ACC
    $b.FlatAppearance.MouseOverBackColor = [Drawing.Color]::FromArgb(230, 0, 81); $b.FlatAppearance.MouseDownBackColor = [Drawing.Color]::FromArgb(200, 0, 70)
  } else {
    $b.BackColor = $C_BG; $b.ForeColor = $C_TEXT; $b.FlatAppearance.BorderColor = $C_LINE
    $b.FlatAppearance.MouseOverBackColor = $C_CARD; $b.FlatAppearance.MouseDownBackColor = $C_LINE
  }
}
$locBtn = New-Object Windows.Forms.Button
$locBtn.Location = New-Object Drawing.Point(600, 302); $locBtn.Size = New-Object Drawing.Size(96, 30)
Set-BtnStyle $locBtn $false; Set-K $locBtn "바꾸기"
$form.Controls.Add($locBtn)
$locBtn.Add_Click({
  $d = New-Object Windows.Forms.FolderBrowserDialog
  $d.Description = T "김비서를 설치할 폴더(그 안에 KimBiseo 폴더를 만들어요)"
  if ($d.ShowDialog() -eq "OK") {
    $script:Prefix = Join-Path $d.SelectedPath "KimBiseo"; $script:status = Join-Path $script:Prefix "install\status.json"
    $locLbl.Text = T '설치 위치: {0}' @($script:Prefix)
  }
})

$stepY = 340
$stepLbls = @{}
$stepNames = @(@("python", "파이썬 준비"), @("plan", "이 PC 사양 확인"), @("files", "프로그램 파일"), @("packages", "파이썬 부품"),
               @("brain", "두뇌 프로그램"), @("models", "모델(두뇌·귀·목소리)"), @("pet", "펫"), @("finish", "바탕화면 아이콘·마무리"))
function Update-StepNames {
  foreach ($s in $stepNames) { if ($stepLbls[$s[0]]) { $stepLbls[$s[0]].Text = "○  " + (T $s[1]) } }
}
for ($i = 0; $i -lt $stepNames.Count; $i++) {
  $col = [math]::Floor($i / 4); $row = $i % 4
  $stepLbls[$stepNames[$i][0]] = Add-Label "" (30 + 340 * $col) ($stepY + 26 * $row) 330 24 $font $C_MUTED
}
Update-StepNames
# 진행 막대 — 윈도우 기본 막대는 색을 못 바꿔서(초록) 판 두 장으로 그림
$bar = New-Object Windows.Forms.Panel
$bar.Location = New-Object Drawing.Point(26, 456); $bar.Size = New-Object Drawing.Size(670, 8); $bar.BackColor = $C_LINE
$form.Controls.Add($bar)
$barFill = New-Object Windows.Forms.Panel
$barFill.Location = New-Object Drawing.Point(0, 0); $barFill.Size = New-Object Drawing.Size(0, 8); $barFill.BackColor = $C_ACC
$bar.Controls.Add($barFill)
$timeLbl = Add-Label "" 26 468 670 18 (New-Object Drawing.Font("Malgun Gothic", 9)) $C_MUTED       # 지난 시간
$detail = Add-Label "" 26 486 670 40 $font $C_MUTED
Set-K $detail '인터넷에서 약 {0}GB 를 받아요(python.org · PyPI · PyTorch · GitHub · 허깅페이스 — 공식 배포처에서 이 PC 가 직접 받아요).' @($spec.need)
$errLbl = Add-Label "" 26 528 670 76 $font $C_BAD
$C_WARN = [Drawing.Color]::FromArgb(227, 179, 65)
$script:manual = $null      # 펫 파일을 직접 받을 때 쓸 정보(주소·파일 이름·크기)

function Add-Btn($x, $w) {
  $b = New-Object Windows.Forms.Button
  $b.Location = New-Object Drawing.Point($x, 616); $b.Size = New-Object Drawing.Size($w, 40); $b.Font = $bold
  Set-BtnStyle $b ($x -lt 100)
  $form.Controls.Add($b); return $b
}
$btnInstall = Add-Btn 26 150
$btnRetry = Add-Btn 26 150; $btnRetry.Visible = $false
$btnRun = Add-Btn 26 150; $btnRun.Visible = $false
# 펫만 못 받았을 때: 펫만 다시 설치 · 브라우저로 직접 받은 파일로 넣기
$btnPet = Add-Btn 184 126; $btnPet.Font = $font; $btnPet.Visible = $false
$btnPetFile = Add-Btn 316 126; $btnPetFile.Font = $font; $btnPetFile.Visible = $false
$btnLog = Add-Btn 450 110; $btnLog.Font = $font
$btnClose = Add-Btn 576 120; $btnClose.Font = $font
$state0 = Join-Path $Prefix "install\state.json"
$script:installed = $false
if (Test-Path $state0) {
  try { if (([IO.File]::ReadAllText($state0, $utf8) | ConvertFrom-Json).installed_at) { $script:installed = $true } } catch { }
}
function Update-Buttons {
  $btnInstall.Text = if ($script:installed) { T "다시 설치(고치기)" } else { T "설치" }
  $btnRetry.Text = T "다시 하기"
  $btnRun.Text = T '{0} 켜기' @($script:appName)
  $btnPet.Text = T "펫 다시 받기"
  $btnPetFile.Text = T "직접 넣기"
  $btnLog.Text = T "기록 보기"
  $btnClose.Text = T "닫기"
  [void]$langLbl
  $langLbl.Text = T "언어"
}
function Update-Static {
  $script:appName = if ($DisplayName -eq "김비서") { T "김비서" } else { $DisplayName }
  foreach ($u in $script:ui) { $u.ctl.Text = $u.pre + (T $u.key $u.a) + $u.post }
  $form.Text = T '{0} 설치' @($script:appName)
  $t.Text = T '{0} 설치' @($script:appName)
  Update-Spec; Update-StepNames; Update-Buttons
  $locLbl.Text = T '설치 위치: {0}' @($script:Prefix)
}
Update-Buttons
$langBox.Add_SelectedIndexChanged({
  if ($langBox.SelectedIndex -lt 0) { return }
  $script:lang = $script:langCodes[$langBox.SelectedIndex]
  Load-Dict
  Update-Static
  $form.Invalidate()
})

function Save-Shot([string]$name) {
  if (-not $ShotDir) { return }
  try {
    New-Item -ItemType Directory -Force -Path $ShotDir | Out-Null
    $bmp = New-Object Drawing.Bitmap($form.Width, $form.Height)
    $form.DrawToBitmap($bmp, (New-Object Drawing.Rectangle(0, 0, $form.Width, $form.Height)))
    $bmp.Save((Join-Path $ShotDir "$name.png"), [Drawing.Imaging.ImageFormat]::Png); $bmp.Dispose()
  } catch { }
}

$mark = @{ "기다림" = "○"; "하는 중" = "●"; "됨" = "✔"; "건너뜀" = "–"; "실패" = "✖" }
$script:shotsDone = @{}
function Update-View {
  if (-not (Test-Path $script:status)) { return }
  try { $s = [IO.File]::ReadAllText($script:status, $utf8) | ConvertFrom-Json } catch { return }
  foreach ($st in $s."단계") {
    $l = $stepLbls[$st.id]
    if ($l) {
      $l.Text = ($mark[$st."상태"]) + "  " + $st."이름" + $(if ($st."상태" -eq "하는 중") { " …" } else { "" })
      $l.ForeColor = if ($st."상태" -eq "실패") { $C_BAD } elseif ($st."상태" -eq "됨") { $C_OK } elseif ($st."상태" -eq "하는 중") { $C_ACCINK } elseif ($st."상태" -eq "건너뜀") { $C_MUTED } else { $C_MUTED }
      $l.Font = if ($st."상태" -eq "하는 중") { $bold } else { $font }
    }
  }
  $barFill.Width = [int]([math]::Min(1000, [math]::Max(0, [double]$s."전체" * 10)) * $bar.Width / 1000)
  if ($s."글") { $detail.Text = [string]$s."글" }
  if ($s."구성" -and $s."구성"."이름") {
    $c = $s."구성"
    $specLbl.Text = (T '그래픽카드: {0}' @(([string]$c.'그래픽카드') + $(if ($c.'그래픽_GB') { ' (' + $c.'그래픽_GB' + ' GB)' }))) + "`r`n" +
      (T '메모리(램): {0} GB · 남은 디스크: {1} GB · 필요 약 {2} GB' @($c.'램_GB', $c.'디스크_여유_GB', $c.'필요_GB')) + "`r`n" +
      (T '구성: {0} · 두뇌: {1}' @($c.'이름', $c.'두뇌')) + "`r`n" + (($c.'안내' + $c.'경고') -join " ")
  }
  if ($s."지금" -eq "models" -and -not $script:shotsDone["models"]) { $script:shotsDone["models"] = 1; Save-Shot "2_설치중_모델" }
  if ($ShotDir) {      # 시험 때만: 오래 걸리는 자리의 화면을 한 장씩
    $g = [string]$s."글"
    if ($s."지금" -eq "python" -and $g -like "*받는 중*/*" -and -not $script:shotsDone["py"]) { $script:shotsDone["py"] = 1; Save-Shot "2_설치중_파이썬받는중" }
    if ($s."지금" -eq "packages" -and $g -like "*받는 중*GB*" -and -not $script:shotsDone["whl"]) { $script:shotsDone["whl"] = 1; Save-Shot "2_설치중_부품받는중" }
    if ($s."지금" -eq "packages" -and $g -like "*음성*푸는 중*GB*" -and -not $script:shotsDone["unp"]) { $script:shotsDone["unp"] = 1; Save-Shot "2_설치중_부품푸는중" }
  }
}

# 윈도우의 '긴 경로 허용' 설정이 켜져 있는지(켜져 있으면 설치 폴더 경로가 길어도 됨)
function Test-LongPaths {
  try { return ((Get-ItemProperty "HKLM:\SYSTEM\CurrentControlSet\Control\FileSystem" -Name LongPathsEnabled -ErrorAction Stop).LongPathsEnabled -eq 1) } catch { return $false }
}
function Start-Worker([string]$PetMode = "", [string]$PetFile = "") {
  # $PetMode = "" (전체 설치) | "pet" (펫 실행 틀만 다시) · $PetFile = 사용자가 직접 받아 둔 압축 파일
  if ($PetMode -ne "pet" -and $script:Prefix.Length -gt 80 -and -not (Test-LongPaths)) {
    # 부품 가운데 이름이 아주 긴 파일(170자)이 있어, 설치 폴더 경로가 길면 윈도우의 경로 길이 제한(260자)에 걸려 '파이썬 부품'에서 실패함
    $errLbl.ForeColor = $C_WARN
    $errLbl.Text = (T '설치 위치의 경로가 너무 길어요({0}자 — 80자까지 돼요).' @($script:Prefix.Length)) + "`r`n" + (T "'바꾸기'를 눌러 더 짧은 폴더(예: C 드라이브 바로 아래 폴더)를 골라 주세요.")
    return
  }
  $errLbl.Text = ""; $btnInstall.Visible = $false; $btnRetry.Visible = $false; $locBtn.Enabled = $false; $chkBrain.Enabled = $false
  $langBox.Enabled = $false
  $btnRun.Visible = $false; $btnPet.Visible = $false; $btnPetFile.Visible = $false
  $script:petMode = $PetMode
  $a = @("-NoProfile", "-ExecutionPolicy", "Bypass", "-WindowStyle", "Hidden", "-File", (Join-Path $PSScriptRoot "worker.ps1"),
         "-Prefix", $script:Prefix, "-DataDir", $DataDir, "-Status", $script:status, "-Source", $Source, "-RegKey", $RegKey,
         "-DisplayName", $script:appName, "-Lang", $script:lang)
  if ($PetMode -eq "pet") { $a += "-PetOnly" }
  if ($PetFile) { $a += @("-PetFile", $PetFile) }
  if ($chkBrain.Checked) { $a += "-LocalBrain" }
  if ($Gemma) { $a += @("-Gemma", $Gemma) }
  if ($DesktopDir) { $a += @("-DesktopDir", $DesktopDir) }
  if ($StartMenuDir) { $a += @("-StartMenuDir", $StartMenuDir) }
  if ($PacksCatalog -ne "<none>") { $a += @("-PacksCatalog", $PacksCatalog) }
  $q = ($a | ForEach-Object { if ($_ -match '[\s"]') { '"' + ($_ -replace '"', '\"') + '"' } else { $_ } }) -join " "
  $psi = New-Object Diagnostics.ProcessStartInfo("powershell.exe", $q)
  $psi.UseShellExecute = $false; $psi.CreateNoWindow = $true
  $script:worker = [Diagnostics.Process]::Start($psi)
  $script:t0 = Get-Date
  $detail.Text = if ($PetMode -eq "pet") { T "펫을 다시 설치하는 중이에요." } else { T "설치를 시작했어요." }
  $timer.Start()
}

# 지난 시간과 '진전 없음' 안내. 일꾼은 2초마다 상태 파일을 새로 쓰고, 그 안의 '조용_초' = 진짜 진전(받은 양·풀린 양·다음 일)이 없던 시간.
#   · 상태 파일이 3분 넘게 안 바뀜 = 일꾼이 멈춤 / '조용_초'가 3분 넘음 = 일꾼은 살아 있는데 일이 안 나감 → 둘 다 노란 글로 알려 줌
$script:stall = $false
function Update-Clock {
  if (-not $script:t0) { return }
  $el = (Get-Date) - $script:t0
  $t = (T "지난 시간") + " " + $(if ($el.TotalMinutes -ge 1) { T '{0}분 {1}초' @([int][math]::Floor($el.TotalMinutes), $el.Seconds) } else { T '{0}초' @([int]$el.TotalSeconds) })
  $timeLbl.Text = T '{0} · 창을 닫지 말고 기다려 주세요(큰 파일은 몇 분씩 걸려요).' @($t)
  $quiet = 0
  try {
    if (Test-Path $script:status) {
      $quiet = [math]::Min($el.TotalSeconds, ((Get-Date) - (Get-Item $script:status).LastWriteTime).TotalSeconds)      # 방금 시작했으면 옛 상태 파일의 나이는 안 침
      $q = ([IO.File]::ReadAllText($script:status, $utf8) | ConvertFrom-Json)."조용_초"
      if ($q -and [double]$q -gt $quiet) { $quiet = [double]$q }
    }
  } catch { }
  if ($quiet -ge 180) {
    $script:stall = $true
    $errLbl.ForeColor = $C_WARN
    $errLbl.Text = (T '{0}분째 진전이 없어요. 백신이 파일을 검사하고 있거나 인터넷이 멈췄을 수 있어요.' @([int][math]::Floor($quiet / 60))) + "`r`n" + (T "조금 더 기다려 보시고, 10분 넘게 그대로면 이 창을 닫고 '설치.bat' 을 다시 실행해 주세요. 받은 것은 그대로 두고 이어서 해요.")
  } elseif ($script:stall) {
    $script:stall = $false
    $errLbl.Text = ""
  }
}

# 펫 파일을 직접 받을 때 쓸 것(주소·파일 이름·크기) — 상태 파일의 오류·주의에서 꺼냄
function Get-Manual($note) {
  if (-not $note) { return $null }
  $m = $note."직접받기"
  if ($m -and $m."주소") { return @{ url = [string]$m."주소"; file = [string]$m."파일"; size = [string]$m."크기_글" } }
  return $null
}
# 까닭 한 줄(짧게). 설치 본체가 적어 준 '까닭'이 있으면 그것, 없으면 이유의 첫 문장
function Short-Why($note) {
  if (-not $note) { return "" }
  if ($note."까닭") { return [string]$note."까닭" }
  $t = [string]$note."이유"
  $i = $t.IndexOf(". ")
  if ($i -gt 0) { return $t.Substring(0, $i + 1) }
  return $t
}
# 펫만 못 받았을 때의 화면: 노란 글 세 줄 + 단추('김비서 켜기' · '펫 다시 받기' · '직접 넣기')
function Show-PetMissing($note, [bool]$again) {
  $script:manual = Get-Manual $note
  $errLbl.ForeColor = $C_WARN
  $first = if ($again) { T "펫을 이번에도 받지 못했어요. 대화는 지금 쓸 수 있어요." } else { T "펫만 아직 못 받았어요. 대화는 지금 쓸 수 있어요." }
  $errLbl.Text = $first + "`r`n" + (T '까닭: {0}' @((Short-Why $note))) + "`r`n" + (T "'펫 다시 받기'를 눌러 보세요. 계속 안 되면 '직접 넣기'를 누르면 순서대로 알려 드려요.")
  $btnRun.Visible = [bool]$script:result; $btnPet.Visible = $true; $btnPetFile.Visible = [bool]$script:manual
}
# '직접 넣기' 창: ① 브라우저로 펫 파일 받기 → ② 받은 파일 고르기. 고른 파일 경로를 돌려줌(안 골랐으면 "")
function Show-ManualDialog {
  if (-not $script:manual) { return "" }
  $m = $script:manual
  $dlg = New-Object Windows.Forms.Form
  $dlg.Text = T "펫 파일 직접 넣기"; $dlg.ClientSize = New-Object Drawing.Size(520, 318); $dlg.FormBorderStyle = "FixedDialog"
  $dlg.MaximizeBox = $false; $dlg.MinimizeBox = $false; $dlg.StartPosition = "CenterParent"; $dlg.Font = $font
  $dlg.BackColor = $C_BG; $dlg.ForeColor = $C_TEXT
  if ($TestOffScreen) { $dlg.StartPosition = "Manual"; $dlg.Location = New-Object Drawing.Point(-30000, -29000); $dlg.ShowInTaskbar = $false }
  $script:picked = ""
  function Dlg-Label($text, $y, $h, $color) {
    $l = New-Object Windows.Forms.Label
    $l.Text = $text; $l.Location = New-Object Drawing.Point(20, $y); $l.Size = New-Object Drawing.Size(480, $h); $l.ForeColor = $color
    $dlg.Controls.Add($l); return $l
  }
  function Dlg-Btn($text, $y, [bool]$primary) {
    $b = New-Object Windows.Forms.Button
    $b.Text = $text; $b.Location = New-Object Drawing.Point(20, $y); $b.Size = New-Object Drawing.Size(480, 42); $b.Font = $bold
    Set-BtnStyle $b $primary; $dlg.Controls.Add($b); return $b
  }
  $null = Dlg-Label (T "인터넷에서 펫 파일이 받아지지 않을 때 쓰는 방법이에요. 아래 두 단추를 차례로 눌러 주세요.") 14 40 $C_TEXT
  $b1 = Dlg-Btn (T "① 브라우저로 펫 파일 받기") 60 $true
  $hint1 = Dlg-Label (T '브라우저가 열리고 파일을 받아요(약 {0}). 다 받을 때까지 기다려 주세요. 이름을 바꾸거나 압축을 풀지 마세요.' @($m.size)) 106 40 $C_MUTED
  $b2 = Dlg-Btn (T "② 받은 파일 고르기") 152 $false
  $hint2 = Dlg-Label (T "보통 '다운로드' 폴더에 있어요. 파일 이름: {0}" @($m.file)) 198 22 $C_MUTED
  $state = Dlg-Label "" 226 40 $C_WARN
  $bCopy = New-Object Windows.Forms.Button
  $bCopy.Text = T "주소 복사"; $bCopy.Location = New-Object Drawing.Point(20, 270); $bCopy.Size = New-Object Drawing.Size(110, 32); Set-BtnStyle $bCopy $false; $dlg.Controls.Add($bCopy)
  $bClose = New-Object Windows.Forms.Button
  $bClose.Text = T "닫기"; $bClose.Location = New-Object Drawing.Point(390, 270); $bClose.Size = New-Object Drawing.Size(110, 32); Set-BtnStyle $bClose $false; $dlg.Controls.Add($bClose)
  $b1.Add_Click({
    try { Start-Process $m.url; $state.ForeColor = $C_MUTED; $state.Text = T "브라우저에서 받는 중이에요. 다 받으면 ②를 눌러 주세요." }
    catch { $state.ForeColor = $C_WARN; $state.Text = T "브라우저를 열지 못했어요. '주소 복사'를 눌러 브라우저 주소창에 붙여 넣어 주세요." }
  })
  $b2.Add_Click({
    $d = New-Object Windows.Forms.OpenFileDialog
    $d.Title = T "받은 펫 파일 고르기"; $d.Filter = (T "펫 파일 (*.zip)") + "|*.zip"; $d.FileName = $m.file
    $dl = Join-Path $env:USERPROFILE "Downloads"
    if (Test-Path $dl) { $d.InitialDirectory = $dl }
    if ($d.ShowDialog() -eq "OK") { $script:picked = $d.FileName; $dlg.Close() }
  })
  $bCopy.Add_Click({ try { [Windows.Forms.Clipboard]::SetText($m.url); $state.ForeColor = $C_MUTED; $state.Text = T "주소를 복사했어요. 브라우저 주소창에 붙여 넣으면 받아져요(다른 PC 에서 받아 옮겨도 돼요)." } catch { $state.Text = $m.url } })
  $bClose.Add_Click({ $dlg.Close() })
  $script:manualDlg = $dlg
  if ($ShotDir) { $dlg.Add_Shown({ try { $bmp = New-Object Drawing.Bitmap($dlg.Width, $dlg.Height); $dlg.DrawToBitmap($bmp, (New-Object Drawing.Rectangle(0, 0, $dlg.Width, $dlg.Height))); $bmp.Save((Join-Path $ShotDir "5_직접넣기_창.png"), [Drawing.Imaging.ImageFormat]::Png); $bmp.Dispose() } catch { } }) }
  [void]$dlg.ShowDialog($form)
  return $script:picked
}

$timer = New-Object Windows.Forms.Timer
$timer.Interval = 500
$timer.Add_Tick({
  Update-View
  Update-Clock
  if ($script:worker -and $script:worker.HasExited) {
    $timer.Stop()
    Update-View
    $el = (Get-Date) - $script:t0
    $timeLbl.Text = T '걸린 시간 {0}분 {1}초' @([int][math]::Floor($el.TotalMinutes), $el.Seconds)
    if ($script:stall) { $script:stall = $false; $errLbl.Text = "" }
    if ($script:worker.ExitCode -eq 3) {
      # 같은 폴더에 설치가 이미 돌고 있음(설치 창을 두 번 띄움)
      $errLbl.ForeColor = $C_WARN
      $errLbl.Text = (T "이 폴더에 설치가 이미 진행 중이에요.") + "`r`n" + (T "먼저 띄운 설치 창이 끝날 때까지 기다려 주세요. 그 창이 안 보이면 1~2분 뒤에 '다시 하기'를 눌러 주세요.")
      $detail.Text = T "설치를 시작하지 않았어요."
      if ($script:petMode -eq "pet") { $btnRun.Visible = [bool]$script:result; $btnPet.Visible = $true } else { $btnRetry.Visible = $true }
      $locBtn.Enabled = $true
      return
    }
    $s = $null; try { $s = [IO.File]::ReadAllText($script:status, $utf8) | ConvertFrom-Json } catch { }
    $locBtn.Enabled = $true
    $warn = if ($s -and $s."주의") { @($s."주의") | Where-Object { $_ } | Select-Object -First 1 } else { $null }
    if ($s -and $s."성공" -and $script:petMode -eq "pet") {
      # 펫만 다시 받은 것이 끝남
      $errLbl.Text = ""
      $detail.Text = T "펫을 설치했어요. '{0}' 단추를 누르면 펫도 같이 나와요." @((T '{0} 켜기' @($script:appName)))
      $btnRun.Visible = [bool]$script:result
      Save-Shot "4_펫만_다시받기_끝"
    } elseif ($s -and $s."성공" -and $warn) {
      # 펫만 못 받음 — 김비서(대화)는 지금 쓸 수 있고, 펫은 여기서 다시 받거나 직접 넣을 수 있음
      $script:result = $s
      $detail.Text = T "설치가 끝났어요(펫만 빼고)."
      Show-PetMissing $warn $false
      Save-Shot "3_설치끝_펫빠짐"
    } elseif ($s -and $s."성공") {
      $script:result = $s
      $detail.Text = T "설치가 끝났어요. 바탕화면의 '{0}' 아이콘으로도 켤 수 있어요." @($script:appName)
      $btnRun.Visible = $true
      Save-Shot "3_설치끝"
    } else {
      $e = if ($s) { $s."오류" } else { $null }
      if ($script:petMode -eq "pet") {
        # 펫만 다시 받다가 또 실패 — 김비서는 이미 설치돼 있음
        $detail.Text = T "설치는 끝나 있어요(펫만 빼고)."
        Show-PetMissing $e $true
        Save-Shot "4_펫만_다시받기_실패"
      } else {
        $errLbl.ForeColor = $C_BAD
        $errLbl.Text = if ($e) { (T '멈춘 곳: {0}' @($e.'단계')) + "`r`n" + [string]$e.'이유' + "`r`n" + (T "'다시 하기'를 누르면 받은 것은 그대로 두고 이어서 해요. 계속 안 되면 '기록 보기'의 글을 보내 주세요.") } else { T "설치가 끝나지 않았어요. '다시 하기'를 눌러 주세요." }
        $btnRetry.Visible = $true
        Save-Shot "3_설치실패"
      }
    }
  }
})
$btnInstall.Add_Click({ Save-Shot "1_시작"; Start-Worker })
$btnRetry.Add_Click({ Start-Worker })
$btnPet.Add_Click({ Start-Worker "pet" "" })
$btnPetFile.Add_Click({
  $f = Show-ManualDialog
  if ($f) { Start-Worker "pet" $f }
})
$btnRun.Add_Click({
  $r = $script:result."실행"
  $q = ($r."인자" | ForEach-Object { if ($_ -match '[\s"]') { '"' + $_ + '"' } else { $_ } }) -join " "
  Start-Process -FilePath $r."파이썬" -ArgumentList $q -WorkingDirectory $r."작업폴더"
  $form.Close()
})
$btnLog.Add_Click({ $lg = Join-Path $DataDir "logs\install.log"; if (Test-Path $lg) { Start-Process notepad.exe -ArgumentList ('"' + $lg + '"') } })
$btnClose.Add_Click({ $form.Close() })
$form.Add_FormClosing({
  param($sender, $e)
  if ($script:worker -and -not $script:worker.HasExited) {
    $r = [Windows.Forms.MessageBox]::Show((T "설치를 멈출까요? 받은 것은 남아서 '다시 하기' 때 이어서 받아요."), (T '{0} 설치' @($script:appName)), "YesNo", "Question")
    if ($r -ne "Yes") { $e.Cancel = $true; return }
    # 이 창이 띄운 일꾼(과 그 아래 프로세스)만 끔
    & taskkill.exe /PID $script:worker.Id /T /F | Out-Null
  }
})
# 화면이 작거나 배율이 커서 창이 화면보다 크면 굴려 볼 수 있게(아래 단추가 작업 표시줄에 가리지 않게)
$wa = [Windows.Forms.Screen]::PrimaryScreen.WorkingArea
if ($form.Height -gt $wa.Height) { $form.AutoScroll = $true; $form.Height = $wa.Height; $form.Width = $form.Width + 18 }
if ($Auto) { $form.Add_Shown({ Save-Shot "1_시작"; Start-Worker }) }
[void]$form.ShowDialog()
