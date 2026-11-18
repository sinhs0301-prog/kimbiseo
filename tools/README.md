# tools — 공개 전 검사

## release_check.py

저장소를 공개하기 전에 실수로 들어간 비밀·내부 주소·개인정보·허용 목록 밖 파일을 찾습니다.
파이썬 3.11 이상, 표준 라이브러리만 씁니다.

```
python tools/release_check.py check                 # 저장소 전체 검사 (통과 = 종료 코드 0, 실패 = 1)
python tools/release_check.py check --json-out 결과.json
python tools/release_check.py scan <폴더나 파일>      # 허용 목록 없이 낱말·꼴·파일 종류만
python tools/release_check.py artifact <꾸러미.zip> [--manifest 목록.json] [--forbid-ext mp3,m4a]
python tools/release_check.py allowlist-verify      # 허용 목록 대조만
python tools/release_check.py allowlist-rehash --all          # 목록에 있는 줄의 sha256 다시 계산
python tools/release_check.py allowlist-add <경로> --origin new --treatment new
python tools/release_check.py privatelist-selftest  # 비공개 낱말 목록이 읽히는지
```

### 무엇을 보나

1. **허용 목록 대조** — 저장소 안 모든 파일이 `allowlist.json` 에 있어야 하고 sha256 이 같아야 합니다.
   목록 밖 파일 1개, 목록에 있는데 없는 파일 1개, sha256 이 다른 파일 1개가 모두 실패입니다.
2. **낱말·꼴 검색** — 사설 IP·테일스케일 주소·공유 폴더 경로·윈도우 사용자 폴더, 전화번호·이메일·주민번호·카드번호 꼴,
   개인키 머리글·흔한 토큰 머리(sk-, ghp_, AKIA, xox, eyJ 등)·16진수 32자리·40자 이상 무작위 글자, 날짜가 붙은 지시·사고 기록.
   눈에 안 보이는 글자를 끼운 것·전각 숫자·JSON `\u` 이스케이프·cp949 글 파일도 풀어서 봅니다.
3. **금지 파일 종류** — 열쇠·서명된 앱·기록·자료 파일(pem·jks·apk·npz·jsonl·log·db 등), venv·node_modules·__pycache__ 폴더.
   소리·모델·압축·실행 파일은 허용 목록에 `"allow_type": true` 로 적힌 것만.
4. **이진 파일 속 글자** — 이진 파일 안의 ASCII·UTF-16·UTF-8 글자와 PNG 글 묶음(압축된 것 포함)도 같은 규칙으로 봅니다.
5. **압축 산출물** — zip 꼴(zip·꾸러미·apk·docx 등)은 풀어서 속 파일까지 같은 검사를 하고, 겹친 압축은 3단까지 봅니다.
   경로 탈출 이름·암호 걸린 항목·압축 폭탄을 막고, `--manifest` 를 주면 목록과 속 파일·sha256 이 같은지 봅니다.

### 비공개 금지 낱말 목록

이 도구는 공개 저장소에 들어가므로, 내부 이름·주소 같은 낱말은 **저장소 밖** 파일에서 읽습니다
(`--private-list`, 환경변수 `KIMBISEO_PRIVATE_WORDS`, 또는 `<저장소>/../자료/금지낱말_비공개.json`).
파일이 없으면 일반 꼴만 검사하고 경고를 냅니다. 공개 직전에는 `--require-private` 로 돌리세요.

목록 형식(`kimbiseo-private-words/1`):

```json
{
  "schema": "kimbiseo-private-words/1",
  "entries": [
    {"id": "p001", "label": "보기 이름", "pattern": "보기낱말", "kind": "literal", "boundary": "left", "severity": "error"}
  ]
}
```

- `kind`: `literal`(글자 그대로) 또는 `regex`
- `boundary`: `none` / `left`(앞에 한글·영숫자가 붙지 않을 때만 — 조사가 붙는 한국어 이름용) / `word`(영어 낱말 앞뒤 경계) / `both`
- `ignore_case`: 기본 `true` · `severity`: `error`(실패) 또는 `warn`(경고)

### 허용 목록 (allowlist.json)

```json
{"path": "README.md", "origin": "new", "treatment": "new", "sha256": "…",
 "exceptions": [{"line": 9, "allow": "허락한 글자", "reason": "이유"}]}
```

- `origin`: `new`(새로 씀) / `standard:<이름>`(표준 문서) / `<별칭>:<상대 경로>`(옮겨 온 원본 — 절대 경로 금지)
- `treatment`: `new` / `copy`(그대로) / `modified`(고쳐서) / `standard`
- `exceptions`: 그 파일 그 줄에서 `allow` 글자 안에 든 것만 넘깁니다(`line: null` = 파일 전체). 줄이 밀려 그 줄에 글자가 없으면 실패합니다.
- `json_hash_keys`: JSON 파일에서 해시를 담는 칸 이름(예: `["sha256"]`) — 그 값은 16진수·무작위 글자 규칙에서 넘깁니다.
- `allow_type`: 소리·모델·압축·실행 파일을 넣어도 되는 예외
- 목록에 줄을 더하는 것은 사람이 직접 합니다(`allowlist-add` 는 고른 파일 하나씩만 더함).

### 못 잡는 것

- base64·뒤집기 등으로 감싼 글, 문자열을 쪼개 이어 붙인 값, 그림 속에 그려진 글자
- zip 이 아닌 압축(7z·rar·tar), 다른 방식으로 압축된 이진 파일 속 글자
- 실제 사람 이름·주소처럼 일정한 꼴이 없는 개인정보(비공개 목록에 적은 것만 잡음)
- 의미상 위험한 코드(예: 숨은 기능) — 사람 눈 확인이 따로 필요합니다

### 영상·소리·옷 꾸러미

- `.webm`·`.mkv` 는 압축된 장면(Cluster)·색인(Cues)을 빼고 머리·정보·트랙 이름·태그·첨부만, `.mp3` 는 ID3·APE 태그만 봅니다
  (압축된 장면 바이트에서 짧은 낱말·이메일 꼴이 우연히 걸리기 때문). 꼴이 조금이라도 이상하면 파일 통째로 봅니다.
- 옷 꾸러미(`pack.json` 의 `format` 이 `hipcpet/1`)는 `pack.json` 의 `sha256`·`mouth` 칸과 `signature.json` 의 `sig` 칸을 해시 칸으로 봅니다.
- `artifact` 의 맨 위 zip 은 항목 내용을 뺀 뼈대(이름·여분 칸·주석·목록)만 이진 검사하고, 항목은 풀어서 따로 검사합니다.

## 화면 한글 남음 검사 (ui_hangul_check.py)

실제 Chrome(헤드리스, 임시 프로필 — 끝나면 지움)으로 en/ja/zh 화면을 열어
`document.body.innerText`·모든 `placeholder`/`title`/`aria-label`/`aria-valuetext`/`alt`·CSS `::before`/`::after` 의 `content`
에 남은 한글(가-힣) 글자 수를 센다. 대화(빈 화면·글 하나 보낸 뒤)·기억·설정 모든 탭·마법사 8단계·말싸움 켬·통역 켬 상태를 연다.
허용 목록(`tools/ui_hangul_allowlist.json`)에 적은 글(예: 언어 고르기의 '한국어' — 각 언어 화면에서도 제 이름 그대로)만 뺀다.

```
python tools/ui_hangul_check.py                       # en,ja,zh · 남은 한글 0 이면 통과(종료 코드 0)
python tools/release_check.py ui-hangul                # release_check 를 거쳐 같은 검사
python tools/release_check.py check --ui               # 공개 검사를 통과한 뒤 화면 검사까지
```

- 본체 서버는 임시 설정·임시 자료 폴더로 띄우고, 가짜 두뇌로 글 한 번을 주고받는다.
- `--shots <폴더>` 를 주면 화면별 PNG 를 남긴다. `--out <파일>` 은 언어·화면별 한글 수 JSON.
- 크롬 프로필은 임시 폴더에 만들고 끝나면 지운다(`--keep-profile` 이면 남김).

## 옷 꾸러미 도구

| 파일 | 하는 일 |
|---|---|
| `pack_sign.js` | ed25519 키 만들기(`keygen`)·공개키 보기(`pubkey`)·서명(`sign`)·확인(`verify`). 비밀키는 저장소 밖에 둡니다 |
| `pack_make.py` | 옷 꾸러미를 공개용으로 다시 묶고 서명(정해진 칸만 남김·PNG 글 묶음 지움·영어 파일 이름·노래 포함/뺌) |
| `make_catalog.py` | 꾸러미 파일들로 옛 모양 옷 목록 `packs.json` 과 미리보기 그림을 만듦(`--soon` 으로 '준비 중' 옷). 공개판 옷 목록은 옷 저장소(kimbiseo-outfits)의 `outfits.json` |

자세한 형식은 `pet/README.md` 에 있습니다.

## 새 판 내기(업데이트)

판 번호는 `app/version.py` 한 곳입니다. 서명 열쇠(`kimbiseo-update-1`)의 비밀키는 저장소 밖에만 둡니다.

1. 코드를 고치고 `app/version.py` 의 `VERSION` 을 올립니다(같은 번호로 다시 내지 않음).
2. 고친 파일을 허용 목록에 반영: `python tools/release_check.py allowlist-rehash --all` → `python tools/release_check.py check --require-private` (오류 0).
3. 시험: `python -m tests.unit.test_update` · `python -m tests.unit.test_installer`.
4. 설치 파일: `python tools/make_setup_zip.py --out <폴더> --guide <설치방법.txt>`.
5. 업데이트 꾸러미와 서명된 목록(cryptography 가 있는 파이썬):
   ```
   python tools/make_update.py build --key <비밀키.pem> --out <폴더> \
       --base-url https://github.com/<계정>/kimbiseo/releases/download/v<판>/ \
       --release-page https://github.com/<계정>/kimbiseo/releases/tag/v<판> \
       --setup-zip <폴더>/KimBiseo-setup-<판>.zip --notes "바뀐 점 1" "바뀐 점 2"
   python tools/make_update.py verify --manifest <폴더>/latest.json --zip <폴더>/KimBiseo-update-<판>.zip
   ```
6. 깃허브 릴리스 `v<판>` 을 만들고 `latest.json` · `KimBiseo-update-<판>.zip` · `KimBiseo-setup-<판>.zip` 을 올립니다.
   설치된 김비서는 `releases/latest/download/latest.json` 을 보므로, 새 릴리스가 '최신(latest)' 이 되면 바로 알립니다.
7. 파이썬 부품·모델 목록(`installer/locks`·`runtimes.json`·`models.json`)을 바꾼 판은 앱이 '새 설치 파일로' 를 안내합니다.

`make_update.py` 하위 명령: `keygen --out <pem>`(새 열쇠, 있으면 멈춤) · `pubkey --key <pem>` · `build` · `verify`.
열쇠를 바꿀 때는 `app/core/update.py` 의 `PUBKEYS` 에 새 공개키를 더한 판을 옛 열쇠로 먼저 내고, 그다음 판부터 새 열쇠로 서명합니다.
