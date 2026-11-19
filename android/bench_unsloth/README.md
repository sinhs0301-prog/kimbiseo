# Unsloth Gemma 4 QAT 모바일 양자화 vs LiteRT-LM 비교 (2026-11-19)

폰 단독 앱의 엔진을 바꿀지 판단하려고, 지금 쓰는 LiteRT-LM E2B(litertlm)와
Unsloth GGUF QAT 모바일 양자화 E2B(UD-Q2_K_XL)를 같은 AVD 2개(램 6GB·4GB)에서 비교했다.
**결론: 앱 코드는 바꾸지 않는다.** Unsloth 쪽이 램·속도·통합 비용에서 낫지 않았다.

자세한 표와 4언어 답 원문: `검증결과\폰단독_언슬롯비교\시험결과.txt`

## 모델
- LiteRT-LM: `gemma-4-E2B-it.litertlm` 2,588,147,712바이트 (Google Gemma-4 mobile quantization, 2/4/8-bit 혼합)
  https://huggingface.co/litert-community/gemma-4-E2B-it-litert-lm
- Unsloth: `gemma-4-E2B-it-qat-UD-Q2_K_XL.gguf` 2,186,186,784바이트, sha256 `0a5bbc20…72da28`
  https://huggingface.co/unsloth/gemma-4-E2B-it-qat-GGUF · Apache-2.0
  문서: https://unsloth.ai/docs/models/gemma-4/qat (문서상 3GB 램, 안드로이드는 llama.cpp 경로)

## 숫자 (질문 4개 × 4언어, 중앙값. PSS = dumpsys meminfo TOTAL PSS 최대)
| AVD | 엔진 | 불러오기 | 첫 토큰 | 초당 토큰 | PSS 최대 |
|---|---|---|---|---|---|
| 6GB | LiteRT-LM | 1.4초 | 1.0~1.4초 | 9.5~11.2 | 1,577,698KB |
| 6GB | Unsloth Q2 (llama.cpp) | 4.0~5.1초 | 4.1~5.3초 | 5.2~5.8 | 2,326,883KB |
| 4GB | LiteRT-LM | 0.8~16.2초* | 1.0~6.5초 | 1.2~12.6 | 1,613,853KB |
| 4GB | Unsloth Q2 (llama.cpp) | 3.6~4.8초 | 3.7~5.6초 | 4.1~6.8 | 2,327,017KB |

\* 앱 4GB 첫 실행만 16.2초(부팅 직후·메모리 압박). 이후 0.8~3.3초.

- 램: Unsloth 2.33GB vs 앱 1.55GB → Unsloth가 약 0.70GiB 더 씀. 디스크만 383MiB 작음.
- 첫 토큰: 앱 1~1.6초 vs Unsloth 4~5.6초 (Unsloth는 생각 채널이 붙음).
- 4GB: 둘 다 크래시 없이 돎. 다만 앱의 기기 확인(MIN_RAM 5GB)은 4GB를 막는다(엔진만 직접 시험).
- 인터넷 끈 상태(Active default network: none)에서 둘 다 답함.

## 시험 스크립트
- `bench_app.py <serial> <lang> <질문파일>` — 앱(adb) 질의·PSS 샘플. `BENCH` 로그(로드/첫 토큰/완료 ms)가 필요하다.
  비교할 때만 SoloBrain.kt에 임시 로그를 넣었고, 측정 뒤 되돌렸다.
- `bench_llama.py <serial> <lang> <질문파일>` — llama.cpp `llama-completion` + 같은 지시문. PSS는 기기 안에서 샘플.
- llama.cpp는 b12530을 NDK r27d로 x86_64·android-26으로 빌드했다(`-t 4 -c 4096 --jinja --reasoning-budget 0 -n 640`).
  릴리스에는 android-arm64만 있어 x86_64 에뮬레이터용은 직접 빌드해야 한다.