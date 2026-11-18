# 바깥 부품 라이선스 표

> **김비서 설치 파일(zip)에는 아래 부품이 하나도 들어 있지 않습니다 — 우리는 이 부품들을 다시 나눠 주지(재배포하지) 않습니다.**
> 설치할 때 사용자 PC 가 각 부품의 **공식 배포처에서 직접** 받습니다(판 고정 + sha256 확인 — `installer/runtimes.json`·`installer/models.json`·`installer/locks/*.json`).
> 각 부품은 자기 라이선스를 따르며, 라이선스 원문은 받은 부품 안(파이썬 꾸러미의 `*.dist-info`, 프로그램 폴더의 LICENSE 등)에 그대로 남겨 둡니다.
> 아래 표는 안내용 요약이고, 서로 다르면 각 부품의 원문이 앞섭니다.
> **폰 앱(APK)에는 LiteRT-LM 실행 코드가 들어가고, Gemma 4 E2B 모델 파일은 앱에 넣지 않고 처음 쓸 때 폰이 공식 배포처에서 직접 받습니다.** 둘 다 Apache License 2.0 입니다.

## 실행 프로그램

| 부품 | 판 | 라이선스 | 받는 곳 | 쓰는 곳 |
|---|---|---|---|---|
| Python (임베디드) | 3.11.9 | PSF-2.0 | python.org | 본체·음성 실행 |
| pip · setuptools | 26.2.2 · 84.2.1 | MIT | PyPI | 설치 때 꾸러미 깔기 |
| llama.cpp (llama-server) | b12283 | MIT | github.com/ggml-org/llama.cpp 릴리스 | '이 PC(Gemma)' 두뇌일 때만 |
| CUDA 실행 라이브러리(cudart-llama) | b12283 과 같이 | NVIDIA CUDA 라이선스(재배포 조건은 NVIDIA EULA) | llama.cpp 릴리스 | 엔비디아 PC 의 Gemma 두뇌 |
| llama.cpp (목소리용 DLL — ggml·llama·libomp) | b10621 | MIT | github.com/ggml-org/llama.cpp 릴리스(`installer/radeon/runtimes.json`, sha256 고정) | 라데온 판의 김비서 목소리(GGUF) |
| Electron | 45.2.3 | MIT (+ Chromium 등 고지 LICENSES.chromium.html 그대로) | github.com/electron/electron 릴리스 | 펫 창 |
| 클로드 코드 · Codex | 사용자가 설치한 판 | 각 회사 약관(Anthropic · OpenAI) | 사용자가 직접 설치 | 구독 두뇌를 고를 때만 — 김비서는 설치하지 않음 |
| Piper (piper-tts, 통역 목소리 읽기 프로그램) | 1.8.0 | **GPL-3.0** (espeak-ng 포함, GPL-3.0) | PyPI(`installer/locks/interp.json`, sha256 고정) | 통역 원어민 목소리(선택 — 설정 → 통역 '통역 목소리 받기'를 누를 때만 받음) |
| LiteRT-LM Android (`litertlm-android`) | 0.19.1 | Apache-2.0 | Google Maven(`com.google.ai.edge.litertlm:litertlm-android`) | **폰 앱(APK) 안** — 폰 단독 AI 실행 엔진 |

## 모델

| 모델 | 라이선스 | 출처(판 고정) | 쓰는 곳 |
|---|---|---|---|
| Huihui gemma-4-E4B-it abliterated (Q4_K GGUF) | Apache-2.0 (모델 카드 표시) · 바탕 모델 Gemma 4 의 조건(https://ai.google.dev/gemma/docs/gemma_4_license) 그대로 | Hugging Face huihui-ai 의 공식 GGUF 저장소(정확한 주소·판·sha256 = `installer/models.json`) | '이 PC' 두뇌(구독 두뇌가 없을 때만 받음). 거절(안전 거름)을 줄인 모델이라 답을 사용자가 확인해야 함 — 모델 카드 경고 |
| Huihui gemma-4-E2B-it abliterated (Q4_K GGUF) | Apache-2.0 (모델 카드 표시) · Gemma 4 조건 그대로 | Hugging Face huihui-ai 의 공식 GGUF 저장소(정확한 주소·판·sha256 = `installer/models.json`) | '이 PC' 두뇌의 작은 판(설정 '두뇌 바꾸기 → Gemma 판'에서 고를 때만 받음). 같은 모델 카드 경고 |
| gemma-4-E4B-it (Q4_K_M GGUF, unsloth) | Apache-2.0 · Gemma 4 조건 | huggingface.co/unsloth/gemma-4-E4B-it-GGUF | 옛 판 사용자 유지용 |
| Whisper large-v3-turbo | MIT | huggingface.co/openai/whisper-large-v3-turbo | 받아쓰기(그래픽카드) |
| Whisper small | Apache-2.0 (모델 카드 표시) | huggingface.co/openai/whisper-small | 받아쓰기(그래픽카드 없음) |
| Qwen3-TTS-12Hz-0.6B-Base | Apache-2.0 | huggingface.co/Qwen/Qwen3-TTS-12Hz-0.6B-Base | 김비서 목소리 |
| Gemma 4 E2B — LiteRT-LM 판 (`gemma-4-E2B-it.litertlm`, 2,588,147,712바이트) | Apache-2.0 (모델 카드 표시) · https://gemma.ai/resources/apache-2/ | huggingface.co/litert-community/gemma-4-E2B-it-litert-lm (판 고정 sha256 `181938105e0eefd105961417e8da75903eacda102c4fce9ce90f50b97139a63c`) | **폰 단독 두뇌** — APK 에 넣지 않고 처음 쓸 때 폰이 직접 받음 |
| Qwen3-TTS-12Hz-0.6B-Base GGUF·ONNX 변환본 (라데온 판) | Apache-2.0 (원 모델과 같음 · 변환 = 형식 바꾸기·양자화만, 고지 NOTICE 같이 올림) | 원 모델 huggingface.co/Qwen/Qwen3-TTS-12Hz-0.6B-Base 를 변환 도구 HaujetZhao/Qwen3-TTS-GGUF(MIT)로 바꿔 **김비서 저장소 릴리스 첨부로 올림**(`installer/radeon/models.json`, sha256 고정) — 위 '다시 나눠 주지 않음'의 예외(공식 변환본이 없어서) | 라데온 판 김비서 목소리 |
| TitaNet small (sherpa-onnx 변환판) | Apache-2.0 — NVIDIA NGC 모델 카드(nvidia/nemo/titanet_small): "License to use this model is covered by the license of the NeMo Toolkit" = NeMo 저장소 Apache-2.0 · 변환(ONNX)은 sherpa-onnx(Apache-2.0) | github.com/k2-fsa/sherpa-onnx 릴리스(자산 고정·sha256) | 내 목소리 등록·등록한 목소리만 명령 받기(선택 — 설정 → 내 목소리 '확인 모델 받기'를 누를 때만 받음, 이 PC 안에서만 돌림) |
| 윈도우 기본 음성(SAPI) | 윈도우 라이선스 | 윈도우에 들어 있음 | 예비 목소리 |
| Kokoro-82M (목소리 af_heart·jf_alpha·zf_xiaobei·ef_dora·ff_siwis·if_sara) | Apache-2.0 (모델·목소리) | huggingface.co/hexgrad/Kokoro-82M (판·sha256 = `installer/interp/models.json`) | 통역 원어민 목소리 — 영어·일본어·중국어·스페인어·프랑스어·이탈리아어(선택) |
| Piper 목소리 de_DE-thorsten-medium | 학습 자료 CC0 (Thorsten-Voice) · 저장소 MIT | huggingface.co/rhasspy/piper-voices (판 고정, MODEL_CARD 같이 받음) | 통역 — 독일어(선택) |
| Piper 목소리 el_GR-rapunzelina-medium | 학습 자료 CC0 (greek-single-speaker-speech-dataset) · 저장소 MIT | huggingface.co/rhasspy/piper-voices | 통역 — 그리스어(선택) |
| Piper 목소리 ru_RU-denis-medium | 학습 자료 CC0 (OHF-Voice voice-datasets) · 저장소 MIT | huggingface.co/rhasspy/piper-voices | 통역 — 러시아어(선택) |
| Piper 목소리 tr_TR-antalia-medium | **CC-BY-4.0** — 출처 표시: "tr_TR-antalia-medium" by ozgurguler (https://huggingface.co/ozgurguler/piper-tr-antalia-medium), 성우 동의 녹음으로 학습한 합성 목소리 | huggingface.co/ozgurguler/piper-tr-antalia-medium | 통역 — 터키어(선택) |
| MrJMThaiTTS (Kokoro 태국어 판, 목소리 thai_som · fp16 ONNX) — 0.1.17~ | 가중치 **Apache-2.0** (FireH2O/MrJMThaiTTS 의 LICENSE·NOTICE — awslabs/FastThaiG2P v0.3.0 모델을 fp16 으로 바꾼 것). **★학습 자료 주의:** 모델 카드가 밝힌 학습 자료 'Som TTS dataset'(CC BY 4.0 표기)은 OmniVoice 로 만든 합성음이고, OmniVoice 모델은 학습 자료(Emilia 등) 때문에 **CC-BY-NC(비상업)** 로 배포됩니다. 그래서 이 목소리를 상업적으로 쓰는 것이 괜찮은지는 분명하지 않습니다(회색). 김비서는 이 모델을 나눠 주지 않고, '통역 목소리 받기'를 누른 사용자 PC 가 원 저장소에서 직접 받습니다. 상업적으로 쓰려는 분은 직접 판단해 주세요 — 걱정되면 설정 → 통역 → 목소리를 '글자만'으로 | huggingface.co/FireH2O/MrJMThaiTTS (판·sha256 = `installer/interp/models.json` 'thai-mrjm') | 통역 원어민 목소리 — 태국어(선택) |
| FastThaiG2P (태국어 글자 → 발음) | Apache-2.0 (awslabs/FastThaiG2P). 저장소 설명: 발음 사전은 위키낱말사전(kaikki.org) 발음 + 생성 후 규칙 검사한 발음, 사전에 없는 말은 tltk 에서 가져온 자료로 읽음 | github.com/awslabs/FastThaiG2P 고정 커밋의 파일만 받음(`installer/interp/models.json` 'fastthaig2p') | 태국어 목소리 |
| PyThaiNLP 5.4.0 | Apache-2.0 | PyPI (판·sha256 = `installer/locks/interp-thai.json`) | 태국어 낱말 나누기(FastThaiG2P 가 씀) |

통역 목소리는 모두 **합성(기계) 목소리**입니다. 듣는 사람이 사람 목소리로 오해할 수 있는 곳에서는 합성 목소리라고 알려 주세요(목소리 제작자 요청).
인도네시아어·베트남어는 상업용으로 쓸 수 있는 원어민 목소리(모델·학습 자료 둘 다)가 없어 글자로만 보여 줍니다(비영리 조건의 MMS 등은 쓰지 않음).
태국어(0.1.17~)는 위 MrJMThaiTTS 로 읽습니다 — 가중치는 Apache-2.0 이지만 학습 자료가 비상업 모델의 합성음이라 회색입니다(위 표).

## 김비서 코드 안에 넣은 남의 코드

| 부품 | 라이선스 | 자리 | 쓰는 곳 |
|---|---|---|---|
| QR Code generator library (Python) — Project Nayuki | MIT (원문은 파일 머리에 그대로) | `app/core/qrcodegen.py` | 폰 짝짓기 QR(설정 → 폰 연결) |

## 폰 앱(android/) 이 쓰는 부품

폰 앱 APK 를 만들 때 gradle 이 Maven Central·Google Maven 에서 받아 앱 안에 넣는 부품입니다(라이선스 원문은 각 부품 안).

| 부품 | 판 | 라이선스 |
|---|---|---|
| OkHttp · Okio (Square) | 4.12.0 | Apache-2.0 |
| ZXing Android Embedded (journeyapps) · ZXing core | 4.3.0 · 3.4.1 | Apache-2.0 |
| Kotlin 표준 라이브러리 (JetBrains) | 1.9.24 | Apache-2.0 |
| AndroidX (zxing-android-embedded 가 끌어오는 것) | — | Apache-2.0 |

## 미디어 라이브러리 (LGPL/GPL 주의)

- **PyAV (av 17.1.0)**: 꾸러미 자체는 BSD-3-Clause. 윈도우 wheel 안에 **FFmpeg 라이브러리**가 함께 들어 있고, FFmpeg 는 빌드에 따라 **LGPL-2.1 이상**(일부 선택 부품을 넣은 빌드는 GPL)입니다. 김비서는 이 wheel 을 고치거나 다시 나눠 주지 않고, 사용자 PC 가 PyPI 에서 직접 받습니다. FFmpeg 고지·원문은 wheel 안 `av.libs`·`*.dist-info` 에 있습니다.
- **soxr 1.0.0**: LGPL-2.1-or-later (libsoxr 포함).
- **num2words 0.5.14**: LGPL.
- **soundfile**: 꾸러미는 BSD-3-Clause, 윈도우 wheel 에 든 libsndfile 은 LGPL-2.1.
- **torch · torchaudio (CUDA 판)**: BSD-3-Clause, CUDA 판 wheel 에 든 NVIDIA 라이브러리는 NVIDIA 라이선스.
- **통역 목소리 부품(`installer/locks/interp.json`, 따로 깔리는 `runtime\python-interp`)**: piper-tts 1.8.0 = **GPL-3.0**(espeak-ng 포함),
  phonemizer-fork · espeakng-loader(espeak-ng 자료) = GPL-3.0, kokoro · misaki = Apache-2.0, spacy · en_core_web_sm = MIT, torch(CPU 판) = BSD-3-Clause.
  이 부품들은 김비서 코드와 한 프로그램으로 묶이지 않습니다 — 귀 서버가 **따로 도는 프로그램**(`voice/interp_voice.py`, 그 런타임의 파이썬)을 켜고
  표준 입출력으로 글과 소리만 주고받습니다. 김비서는 이 부품을 고치거나 다시 나눠 주지 않고, 사용자 PC 가 PyPI·GitHub(spaCy 모델) 에서 직접 받습니다.
  GPL 원문·소스 안내는 받은 꾸러미의 `*.dist-info` 에 있습니다(piper 소스: https://github.com/OHF-Voice/piper1-gpl).

## 파이썬 꾸러미 전체 (`installer/locks/app.json`·`voice-cuda.json` 에 고정된 판, 꾸러미 정보의 라이선스 표시)

환경: app = 본체(대화·화면), voice = 귀(받아쓰기)·목소리.

| 꾸러미 | 판 | 라이선스(꾸러미 정보) | 환경 |
|---|---|---|---|
| accelerate | 1.12.0 | Apache | voice |
| aiofiles | 25.1.0 | Apache-2.0 | app |
| aiohappyeyeballs | 2.7.1 | PSF-2.0 | app |
| aiohttp | 3.14.5 | Apache-2.0 AND MIT | app |
| aioice | 0.10.2 | BSD-3-Clause | app |
| aiortc | 1.15.0 | BSD-3-Clause | app |
| aiosignal | 1.4.0 | Apache 2.0 | app |
| annotated-doc | 0.0.5 | MIT | app·voice |
| annotated-types | 0.8.0 | MIT | app·voice |
| anthropic | 1.17.0 | MIT | app |
| anyio | 4.15.1 | MIT | app·voice |
| attrs | 26.1.0 | MIT | app |
| audioread | 3.1.0 | MIT | voice |
| av | 17.1.0 | BSD-3-Clause | app |
| bottle | 0.13.4 | MIT | app |
| brotli | 1.2.0 | MIT | voice |
| certifi | 2026.10.19 | MPL-2.0 | app·voice |
| cffi | 2.1.1 | MIT-0 | app·voice |
| charset-normalizer | 3.5.2 | MIT | voice |
| click | 8.5.0 | BSD-3-Clause | app·voice |
| cloudpickle | 3.1.2 | BSD-3-Clause | voice |
| clr_loader | 0.3.1 | MIT | app |
| colorama | 0.4.6 | BSD License | app·voice |
| cryptography | 50.0.2 | Apache-2.0 OR BSD-3-Clause | app |
| decorator | 5.3.1 | BSD-2-Clause | voice |
| dnspython | 2.9.0 | ISC | app |
| docopt | 0.6.2 | MIT | app |
| docstring_parser | 0.18.0 | MIT | app |
| einops | 0.8.2 | MIT | voice |
| fastapi | 0.156.4 | MIT | app·voice |
| filelock | 3.32.3 | MIT | voice |
| flatbuffers | 25.12.19 | Apache 2.0 | app·voice |
| frozenlist | 1.8.0 | Apache-2.0 | app |
| fsspec | 2026.7.0 | BSD-3-Clause | voice |
| google-crc32c | 1.9.0 | Apache-2.0 | app |
| gradio | 6.17.3 | Apache-2.0 | voice |
| gradio_client | 2.5.0 | Apache-2.0 | voice |
| groovy | 0.1.2 | MIT License | voice |
| h11 | 0.16.0 | MIT | app·voice |
| h2 | 4.4.1 | MIT | app |
| hf-gradio | 0.4.1 | MIT | voice |
| hpack | 4.2.0 | MIT | app |
| httpcore | 1.0.9 | BSD-3-Clause | app·voice |
| httpcore2 | 2.15.1 | BSD-3-Clause | app |
| httpx | 0.28.1 | BSD-3-Clause | app·voice |
| httpx2 | 2.15.1 | BSD-3-Clause | app |
| huggingface_hub | 0.36.2 | Apache | voice |
| hyperframe | 6.1.0 | MIT License | app |
| idna | 3.20 | BSD-3-Clause | app·voice |
| ifaddr | 0.2.0 | MIT | app |
| Jinja2 | 3.1.6 | BSD License | voice |
| jiter | 0.17.0 | MIT | app |
| joblib | 1.6.0 | BSD-3-Clause | voice |
| lazy-loader | 0.6 | BSD-3-Clause | voice |
| librosa | 0.11.0 | ISC | voice |
| llvmlite | 0.50.0 | BSD-2-Clause | app·voice |
| loguru | 0.7.3 | MIT License | app |
| loudness | 0.2.0 | MIT | app |
| Markdown | 3.11.2 | BSD-3-Clause | app |
| markdown-it-py | 4.2.0 | MIT License | voice |
| MarkupSafe | 3.0.3 | BSD-3-Clause | voice |
| mdurl | 0.1.2 | MIT License | voice |
| mpmath | 1.3.0 | BSD | app·voice |
| msgpack | 1.2.3 | Apache-2.0 | voice |
| multidict | 7.1.0 | Apache-2.0 | app |
| narwhals | 2.27.1 | MIT | voice |
| networkx | 3.6.1 | BSD-3-Clause | voice |
| num2words | 0.5.14 | LGPL | app |
| numba | 0.68.0 | BSD | app·voice |
| numpy | 2.4.6 | BSD-3-Clause AND 0BSD AND MIT AND Zlib AND CC0-1.0 | app·voice |
| onnxruntime | 1.24.4 | MIT License | app·voice |
| openai | 3.35.1 | Apache-2.0 | app |
| opencv-python-headless | 4.14.0.94 | Apache 2.0 | app |
| opentelemetry-api | 1.45.1 | Apache-2.0 | app·voice |
| orjson | 3.13.0 | MPL-2.0 AND (Apache-2.0 OR MIT) | voice |
| packaging | 26.3 | Apache-2.0 OR BSD-2-Clause | app·voice |
| pandas | 3.0.6 | BSD License | voice |
| pillow | 12.3.0 | MIT-CMU | app·voice |
| pipecat-ai | 1.13.0 | BSD-2-Clause | app |
| platformdirs | 4.13.5 | MIT | voice |
| pooch | 1.9.0 | BSD-3-Clause | voice |
| propcache | 0.5.4 | Apache-2.0 | app |
| protobuf | 6.33.6 | 3-Clause BSD License | app·voice |
| proxy_tools | 0.1.0 | MIT | app |
| psutil | 7.2.2 | BSD-3-Clause | voice |
| pycparser | 3.11 | BSD-3-Clause | app·voice |
| pydantic | 2.14.1 | MIT | app·voice |
| pydantic_core | 2.50.1 | MIT | app·voice |
| pydub | 0.25.1 | MIT | voice |
| pyee | 13.0.1 | MIT | app |
| Pygments | 2.21.0 | BSD-2-Clause | voice |
| pylibsrtp | 1.0.0 | BSD-3-Clause | app |
| pyOpenSSL | 26.4.0 | Apache License, Version 2.0 | app |
| python-dateutil | 2.9.0.post0 | Dual License | voice |
| python-dotenv | 1.2.4 | BSD-3-Clause | app |
| python-multipart | 0.0.32 | Apache-2.0 | voice |
| pythonnet | 3.2.1 | MIT | app |
| pytz | 2026.5 | MIT | voice |
| pywebview | 6.2.1 | BSD License | app |
| PyYAML | 6.0.3 | MIT | app·voice |
| qwen-tts | 0.1.1 | Apache-2.0 | voice |
| regex | 2026.9.29 | Apache-2.0 AND CNRI-Python | voice |
| requests | 2.34.2 | Apache-2.0 | voice |
| resampy | 0.4.3 | ISC | app |
| rich | 15.0.0 | MIT | voice |
| safehttpx | 0.1.7 | MIT License | voice |
| safetensors | 0.8.0 | Apache Software License | voice |
| scikit-learn | 1.9.1 | BSD-3-Clause | voice |
| scipy | 1.17.1 | BSD License | voice |
| semantic-version | 2.10.0 | BSD | voice |
| sentencex | 1.0.32 | MIT | app |
| setuptools | 78.1.0 | MIT License | voice |
| shellingham | 1.5.4 | ISC License | voice |
| six | 1.17.0 | MIT | voice |
| sniffio | 1.3.1 | MIT OR Apache-2.0 | app |
| soundfile | 0.13.1 | BSD 3-Clause License | app·voice |
| sox | 1.5.0 | BSD-3-Clause | voice |
| soxr | 1.0.0 | LGPL-2.1-or-later | app·voice |
| starlette | 1.9.0 | BSD-3-Clause | app·voice |
| sympy | 1.14.0 | BSD | app·voice |
| threadpoolctl | 3.7.0 | BSD-3-Clause | voice |
| tokenizers | 0.22.2 | Apache Software License | voice |
| tomlkit | 0.14.0 | MIT | voice |
| torch | 2.11.0+cu128 | BSD-3-Clause | voice |
| torchaudio | 2.11.0+cu128 | BSD License | voice |
| tqdm | 4.70.1 | MPL-2.0 AND MIT | voice |
| transformers | 4.57.3 | Apache 2.0 License | voice |
| truststore | 0.10.5 | MIT | app |
| typer | 0.27.3 | MIT | voice |
| typing_extensions | 4.16.0 | PSF-2.0 | app·voice |
| typing-inspection | 0.4.4 | MIT | app·voice |
| tzdata | 2026.5 | Apache-2.0 | voice |
| urllib3 | 2.8.0 | MIT | voice |
| uvicorn | 0.54.0 | BSD-3-Clause | app·voice |
| wait_for2 | 0.4.1 | Apache-2.0 | app |
| websockets | 17.3 | BSD-3-Clause | app |
| win32_setctime | 1.2.0 | MIT license | app |
| yarl | 1.25.1 | Apache-2.0 | app |

## 통역 환율

- 통역 중 상대 말의 외국 돈을 원화로 바꿀 때 쓰는 환율: **유럽중앙은행 기준환율**(frankfurter.dev — 키 없는 공개 서비스) +
  거기 없는 통화는 **Rates By Exchange Rate API**(open.er-api.com, 무료 이용 조건 = 출처 표시. 설정 → 통역 '환율' 칸에 표시).
  통역을 쓸 때 하루 한 번만 받고(요청에 사용자 정보 없음), 자료 폴더 `fx_rates.json` 에 둡니다. 참고용 어림값이에요(실제 환전·카드 환율과 다름).

## 소스에 옮겨 넣은 코드

- `voice/gguf_tts/` — HaujetZhao/Qwen3-TTS-GGUF (MIT, 커밋 74feb581bc8c) 의 `qwen3_tts_gguf/inference` 일부를 옮겨 고침. 원문 저작권 고지 = `voice/gguf_tts/LICENSE`.
