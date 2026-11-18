공개판 시험을 둘 곳입니다 — 시험 자료는 가짜 값만 씁니다.

- `unit/test_body.py` — 본체 단위 시험(소리·두뇌 없이). `python -m tests.unit.test_body`
- `unit/test_debate.py` — 말싸움(토론) 모드 단위 시험(4언어 켜기·끄기 확인·30분 자동 끔·도구 거르기·금지어 빼기·
  꺼짐 지시문이 바꾸기 전과 같은지·성인 지시문·말 끝 기다림). `python tests/unit/test_debate.py`
- `unit/test_update.py` — 업데이트 단위 시험(서명·꾸러미 확인·바꿔 끼우기·되돌리기). cryptography 가 있는 파이썬으로 `python -m tests.unit.test_update`
- `unit/test_installer.py` — 설치·실행기 단위 시험(받기·설치 없음). `python -m tests.unit.test_installer`
- `unit/test_install_download.py` — 설치 때 받기 단위 시험(끊겨도 이어 받기·원인 가려내기·윈도우 내려받기로 대신 받기·깨진 파일 다시 받기·
  '펫' 단계가 실패해도 설치 끝내기·펫만 다시 받기·직접 받은 파일로 넣기). 이 PC 안 임시 서버만 씀. `python -m tests.unit.test_install_download`
- `unit/test_install_progress.py` — 설치가 멈춘 것처럼 보이지 않게 하는 부분의 단위 시험(지난 시간·진전 없던 시간·살아 있음 표시·
  큰 부품을 디스크에 푸는 동안의 진행 표시·실패 까닭 한 줄). 가짜 pip 만 씀. `python -m tests.unit.test_install_progress`
- `unit/test_text_norm.py` — 숫자·단위 한국어 읽기 단위 시험(134문장: 돈·날짜·시각·개수·전화·판 번호·소수·퍼센트·단위·영어 약어). `python -m tests.unit.test_text_norm` (`--table` 이면 변환 표)
- `unit/test_winbox.py` — 김비서 창 옮기기·크기 조절·자리 기억 단위 시험(가짜 모니터: 배율 섞임·음수 좌표·세로·사라진 모니터). `python -m tests.unit.test_winbox`
- `unit/test_pet_geometry.js` — 펫 자리·크기 계산 단위 시험(가짜 화면 구성). `node tests/unit/test_pet_geometry.js`
- `unit/test_persona_voice.py` — 말투·성격·답 길이 지시문 · 목소리 세부 설정 범위 단위 시험. `python -m tests.unit.test_persona_voice`
- `unit/test_compat_api.py` — 'OpenAI 호환 API' 두뇌 단위 시험(이 PC 안 가짜 서버 · 열쇠가 새지 않는지). `python -m tests.unit.test_compat_api`
- `unit/test_pet_download.js` — 펫 옷 꾸러미 받기 단위 시험(이어 받기·다시 시도·깨진 파일 다시 받기). `node tests/unit/test_pet_download.js`
- `unit/test_settings.py` — 설정 화면 단위 시험(값 검사·반영 시점·끼어들기 감도·사양 추천). `python -m tests.unit.test_settings`
- `unit/test_voice_gender.py` — 성별→목소리 단위 시험(자동 연결·직접 고정·자산 없음 대체·voices.json 보존). `python -m tests.unit.test_voice_gender`
- `unit/test_voice_outfit.py` — 옷→목소리 단위 시험(입은 옷으로 고르기·'옷에 맞춤(자동)' 설정·모르는 목소리는 기본으로·펫에 옷 묻기). `python -m tests.unit.test_voice_outfit`
- `unit/test_phone.py` — 폰 연결 단위 시험(사설 주소만·짝 코드 10분 한 번·틀리면 잠금·QR·자체 인증서·관문 TLS/짝짓기/WS·지운 기기 거절·폰 도구·'실행할까요?' 겉싸개). 시험 설치 파이썬으로 파일 경로로 실행
- `unit/test_voiceprint.py` — 내 목소리 등록 단위 시험(특징·등록 규칙·남의 목소리 무시·통역 중엔 켜기/끄기만 가림). 진짜 모델 시험은 환경변수 `KIMBISEO_TITANET`(모델 파일)·`KIMBISEO_VOICE_WAVS`(a_*·b_* 16kHz wav 폴더)
- `android/app/src/test` — 폰 앱 규칙 단위 시험(QR 읽기·주소·인증서 지문·길안내 주소·연락처 이름·앱 이름). `python android/build_apk.py --unit`
- `e2e/fake_brain.py` — 가짜 두뇌(OpenAI 꼴 + llama-server 꼴 `/apply-template`·`/tokenize`). 규칙으로만 답함.
  `--text-tools`(도구 호출을 글로 씀) · `--trip N`(캐시 오염 흉내) · `--require-key 환경변수`(바깥 두뇌 흉내, 열쇠 값은 기록 안 함)
- `e2e/fake_pet.py` — 본체가 펫에 보내는 신호를 받아 기록만 하는 가짜 펫
- `brain_eval/` — 두뇌 모델 고르기 시험(3단계)
