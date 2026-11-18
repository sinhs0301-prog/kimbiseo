[한국어](README.md) | **English** | [日本語](README.ja.md) | [中文](README.zh.md)

# KimBiseo (김비서)

A **voice-activated assistant** and **desktop character pet** that runs entirely on your own PC.
Call out "KimBiseo," or type into its window, and it answers; the pet on your desktop moves its mouth
along with the speech and changes its expression and pose.

This project is made by HighlifePC.

## What it does

- **Conversation**: Ask by voice and hear the answers. Basic tools include weather, web search, price checks, arithmetic,
  opening programs, remembering facts, and taking notes. Multi-step requests like "Look up the price of an RTX 5090 and
  write it up in Notepad" are carried out in order. Notes are written only in the **KimBiseo Notes** window the assistant
  opens itself (Windows Notepad is not launched automatically); Ctrl+S or the Save button stores them in `Documents\KimBiseo Notes\`.
- **Brain**: If Claude Code or Codex (ChatGPT) is signed in on this PC with your own account, KimBiseo uses that subscription
  as-is (it calls the program directly — it never sees your account or tokens). Otherwise it runs Gemma 4 (uncensored) locally
  (usually E4B, or the lighter E2B, via llama.cpp, downloaded straight from the original distributor). You can also point it at
  a local OpenAI-compatible endpoint or use your own API key (GPT, Claude) in Settings.
- **Ears and voice**: Dictation uses whisper; speech uses the Qwen3-TTS KimBiseo voice (under 6 GB of graphics memory, and
  Windows built-in voices when memory is short). Two voices ship — KimBiseo (female) and KimBiseo (male) — and the one it uses
  follows the outfit the pet is wearing (you can also choose one in Settings).
  The **speech gate** (0.1.17+) stops quiet-room noise and breathing from being transcribed as "thank you" or "hello":
  only segments with enough actual speech are transcribed, and short, faint one-word greetings are dropped
  (the `귀.말소리_문` setting in the config file).
- **Pet**: A desktop character — KimBiseo (female) and KimBiseo (male). If you agree on the first screen, it downloads the
  outfit for the character you chose; other outfits are picked individually from **Get more outfits** in the pet menu
  (outfit list = [kimbiseo-outfits](https://github.com/sinhs0301-prog/kimbiseo-outfits)).
- **Interpretation** (0.1.15+): Say "interpret to Thai" or just "interpret" (auto-detect) and it translates between Korean
  and 13 languages (English, Thai, Japanese, Chinese, Indonesian, Vietnamese, German, Greek, Turkish, Russian, French,
  Spanish, Italian). It recognizes the language the other person is speaking, and while interpreting, speech is **translated
  only** (it is not taken as a request to KimBiseo). Stop with "stop interpreting" or the on-screen **Off** button; it turns
  itself off after 10 minutes of silence. Translation uses your current brain (Gemma on this PC recommended) and keeps the
  original figures for numbers and amounts. Foreign amounts are followed by a rough won estimate — "(about ₩14,000)"
  (exchange rates fetched once a day; Korea only).
  Foreign languages are spoken in **native voices** (Settings → Interpretation → "Download interpretation voices",
  about 800 MB — Kokoro, Piper, and the Thai MrJMThaiTTS). Indonesian and Vietnamese have no commercially usable voices yet,
  so they are shown as text. The Thai voice (0.1.17+) uses Apache-2.0 weights, but its training data is synthetic audio
  from a non-commercial model, so commercial use is a gray area — see [THIRD_PARTY_LICENSES](THIRD_PARTY_LICENSES/README.md).
- **Using it from your phone** (0.1.16+, optional, off by default): Install the "KimBiseo" app on your phone and connect it to
  this PC, and speaking into the phone reaches the KimBiseo on your PC — see "Using it from your phone" below.
- **Registering your own voice** (0.1.16+, optional, off by default): Read a few sentences and you can turn on "Only take
  commands in my registered voice" (so it won't answer the TV or other people) — see "Registering your own voice" below.
- **Make it yours** (Settings): tone (automatic, polite, casual-polite, casual), answer length, a personality description,
  voice details (speaking rate, pitch variation, pause between sentences — with a "Reset to defaults" button),
  pet size (50–200%), and the KimBiseo window size (drag the edges; size and position are remembered). Numbers, dates and
  units are read aloud in Korean while the on-screen text stays as it is — **Korea only**
  ("12개" → "yeoldu gae", "3:30" → "se si samsip bun", "0.1.12" → "yeong jeom il jeom sibi").
- **Multiple monitors**: Even when monitors use different scaling (100% / 125% / 150%), windows don't drift when moved between
  them, and the pet remembers which screen it was on and where. Unplug a monitor and it moves to a visible screen; plug it
  back in and it returns to its old spot.
- **Your own API key**: Choose **OpenAI-compatible API** as the brain to use any outside AI service with an OpenAI-style
  endpoint and your own API key (address, model, key, test connection). The key is stored on this PC only, encrypted with your
  Windows account, and never appears on screen or in logs.
- **Your data stays on your PC**: Every program listens only on this PC (127.0.0.1). Settings, conversation memory and keys
  are stored on this PC only. If you choose an outside brain (GPT, Claude, etc.), only the text of the conversation goes to
  that company.

## Recommended specs

| | Minimum | Recommended |
|---|---|---|
| OS | Windows 10/11 64-bit | Windows 11 |
| RAM | 16 GB | 32 GB |
| Graphics card | Not required (brain via outside AI, voice via Windows) | NVIDIA with 12 GB+ of VRAM |
| Disk | About 10 GB (no graphics card) | About 25 GB |

With 6 GB+ of NVIDIA VRAM you get the KimBiseo voice (Qwen3-TTS); with less, or no card, Windows built-in voices are used.
The KimBiseo voice starts on the GPU only if at least 3.3 GB of VRAM is free at launch; with less (the brain or other
programs using it) it starts with Windows voices instead of stuttering. If VRAM runs short while running, it switches to
Windows voices on its own without cutting off the speech.
A microphone and speakers (or a headset) are required.

## Installation

1. Download the installer that matches your graphics card from [Releases](https://github.com/sinhs0301-prog/kimbiseo/releases/latest).
   NVIDIA (RTX/GTX) → `KimBiseo-setup-<version>-NVIDIA.zip` · Radeon, Intel, integrated graphics, or no graphics card →
   `KimBiseo-setup-<version>-Radeon.zip`
   (To check your graphics card: Task Manager → Performance → GPU.)
2. Right-click the zip → Properties → check "Unblock" (if present) → extract.
3. Double-click `설치.bat` (the install script) in the extracted folder. If a blue warning appears, click "More info" → "Run".
4. In the installer window, click "Install" and it takes care of the rest by itself (15–25 minutes on a fast connection).
5. Click "Start KimBiseo" or the "KimBiseo" desktop icon. The first-run screen asks for your name, how you want to be
   addressed, the brain, the voice, and the microphone, one after another.

Python, dependencies and models are downloaded by your PC directly from the official sources (python.org, PyPI, PyTorch,
GitHub, Hugging Face) during installation, and every downloaded file is checked against its sha256. Full instructions are in
`설치방법.txt` inside the zip.

If a download drops, it resumes from where it stopped; if that fails, it retries by another route (Windows download). If only
the "pet" step failed, you can finish the installation and use KimBiseo (conversation) right away; the pet can be added later
with "Re-download pet" / "Add manually" in the installer, or from Settings → Pet. The installer shows elapsed time and what it
is doing (file being downloaded, amount received, time left), and tells you if nothing has progressed for more than 3 minutes.

Uninstall: "Uninstall KimBiseo" in the Start menu, or Windows Settings → Apps → KimBiseo → Uninstall (it asks whether to keep
conversation memory and settings).

## How to use interpretation

1. Start talking (mic button) and say something like **"Interpret to Thai."** If you just say **"Interpret"** without naming
   a language, it works out the other person's language by itself. You can also press the **Interpret** button below the
   chat screen.
2. Speak Korean and it comes out in the other language; when the other person speaks, it comes out in Korean. On screen the
   translation is shown large with the original small underneath, and a foreign amount gets an extra line with a rough won
   estimate (≈ ₩14,000; rates are fetched once a day and are approximate, for reference — Korea only).
3. To finish, say **"Stop interpreting"** or press **Off** in the interpretation panel. It turns itself off after 10 minutes
   without speech (adjustable in Settings → Interpretation).
4. To hear foreign languages in the native voice, press **Settings → Interpretation → "Download interpretation voices"**
   (about 800 MB, one time). If you downloaded them before 0.1.16, press it once more to add just the Thai voice. Without
   these voices, foreign languages are shown as text only.

- While interpreting, speech is **translated only** — if the other person says "open Notepad," KimBiseo translates it and
  does not run it.
- Translation uses the brain you are currently using (Gemma on this PC recommended — the conversation never leaves the PC;
  subscription brains take a few seconds per line). You can change it with "Interpretation AI endpoint" in
  Settings → Interpretation.
- While interpreting, typed messages are translated only as well (0.1.17+; commands are not run, but "stop interpreting"
  is accepted).
- What is said and translated is shown on screen only and is not stored in memory or chat history.

| Language | Foreign voice | Voice license |
|---|---|---|
| English · Japanese · Chinese · Spanish · French · Italian | Kokoro-82M (af_heart · jf_alpha · zf_xiaobei · ef_dora · ff_siwis · if_sara) | Apache-2.0 |
| German | Piper de_DE-thorsten-medium | Training data CC0 (Thorsten-Voice) |
| Greek | Piper el_GR-rapunzelina-medium | Training data CC0 |
| Russian | Piper ru_RU-denis-medium | Training data CC0 |
| Turkish | Piper tr_TR-antalia-medium | CC-BY-4.0 — "tr_TR-antalia-medium" by ozgurguler |
| Thai (0.1.17+) | MrJMThaiTTS (Kokoro Thai edition, thai_som) + FastThaiG2P | Weights Apache-2.0 · ★ training data is synthetic audio from a non-commercial model, so commercial use is a gray area (see THIRD_PARTY_LICENSES) |
| Indonesian · Vietnamese | None (text only) | No commercially usable voice yet (both model and training data) — planned for later |

The reader program Piper (piper-tts, GPL-3.0) runs separately from KimBiseo; your PC downloads it directly from PyPI.
All interpretation voices are synthetic (machine) voices.
Full notices = [THIRD_PARTY_LICENSES](THIRD_PARTY_LICENSES/README.md).

## Using it from your phone (optional)

1. In KimBiseo on the PC, open **Settings → Phone connection**, turn on "Enable phone connection", and save. If the Windows
   Firewall prompt appears, allow **private networks** only.
2. Install the **KimBiseo app** on your phone (release asset `KimBiseo-phone-0.1.1.apk` — Android 8.0+, or build it yourself
   from `android/`), then press **"Create connection code"** on the PC screen. A QR code and an 8-digit number appear
   (valid for 10 minutes, one use).
   (If you open the APK in the phone browser, it asks you to allow "install from this source" once — that is because it is
   not a Play Store app.)
3. In the phone app, **scan the QR code** (or type in the PC address, code and certificate text) → check that the
   "certificate check text" shown on the phone matches the PC screen → **Connect**.
4. Press **Start conversation** in the phone app and speak or type. The conversation continues even with the screen off
   ("in conversation" in the notification).

- You can give the PC tasks from the phone too: search, open sites and programs, write KimBiseo notes (turn off with
  "PC control" in Settings → Phone connection).
- It can do phone-side tasks as well: "Call Mom" (fills in the number on the dialer — you press Call), "Send a text"
  (fills in the recipient and message — you press Send), "Open YouTube".
- Directions: "Give me directions to Gangnam Station", "Open Seoul Station in T Map." If you name an app it opens that app;
  if you don't, it picks among installed apps in the order KakaoMap → Naver Map → T Map → Google Maps → Kakao Navi
  (falling back to KakaoMap on the web). **Korea only** for these navigation apps: KakaoMap, Naver Map and T Map open the
  search results for the destination, and you press "Directions" yourself. Google Maps has no car directions inside Korea,
  so there it opens search results ("Route" is manual); abroad it starts navigation directly. Kakao Navi opens the app and
  copies the destination name, so paste it into the search box (passing the destination directly is planned for a later
  version). If the chosen app doesn't open (disabled, etc.), it tries the next installed app, and then KakaoMap on the web.
- For hard-to-undo actions such as deleting, the phone shows **"Run it?"** and you must press "Run" (no answer within
  45 seconds means it does not run).
- Interpretation works from the phone too ("Interpret" at the top of the chat screen).
- Only one device talks at a time — starting a conversation on the phone puts the PC window's conversation to rest, and vice
  versa.
- To use it outside the home, install Tailscale on the phone and the PC, sign in to the same account, and turn on "Also
  accept connections over Tailscale". The PC address to enter is the 100.x.x.x address shown on the PC screen (pressing a
  comma on the numeric keypad is corrected to a dot).
- If the connection fails, the phone app tells you why: wrong code · code expired (10 minutes) · too many wrong codes
  (brief lockout) · can't reach the PC (check Wi-Fi/Tailscale) · the PC is not accepting Tailscale connections. Entering a
  wrong code does not invalidate the code on the PC screen (it disappears once you connect with the right one).

## Registering your own voice (optional)

1. In **Settings → My voice**, press "Download check model" (about 40 MB, one time).
2. Read the sentences shown, one at a time (3 or more, 5 recommended) → **Finish registration**.
3. Turn on **"Only take commands in my registered voice"** and save (strictness: loose / normal / strict). The same applies
   when speaking through the phone app.

- Other people's voices and the TV are heard but not answered; the chat screen shows "not heard".
- While interpreting, the other person's speech is translated as usual, and only on/off phrases such as "stop interpreting"
  are accepted when spoken in the registered voice.
- Only the voice characteristics (192 numbers) are stored; the recorded sound is not. "Delete registration" removes it at
  any time.
- The phone mic may score a little lower than the PC mic — if it doesn't pick you up well, set strictness to "loose".

## Updates

- When KimBiseo starts (at most once a day), it checks for a new version. You can also check right away with
  Settings → About → "Check for updates".
- If a new version exists, the changes and an "Update" button appear above the chat screen.
- Pressing it downloads the update, **verifies the signature and sha256**, briefly closes KimBiseo, replaces only the program
  code, and starts it again. Conversation memory, settings, keys, voices, pet outfits and models are left as they are.
- If the new version fails to start, it **rolls back to the previous version by itself**.
- For versions that change Python dependencies or models, it tells you to install with the new installer (installing keeps
  your conversation memory and settings).

## Folders

| Folder | Contents |
|---|---|
| `app/` | Main body (conversation flow, tools, UI, launcher, updates) |
| `voice/` | Ears (dictation) and the voice server |
| `brain/` | Brain test tools |
| `pet/` | Desktop pet (Electron) |
| `installer/` | Install, uninstall, update swapping |
| `tools/` | Pre-release checks, building installers and update packages |
| `tests/` | Tests |
| `android/` | Phone app (KimBiseo — connect, chat, interpret, phone actions). Build = `android/build_apk.py` |
| `assets/` · `docs/` | Asset terms and documentation |

## License

- Code: [Apache License 2.0](LICENSE)
- The name, face, voice and outfit packs of the character "KimBiseo": [separate terms](ASSETS-LICENSE.md) — personal use only
- Third-party components (Python packages, models, llama.cpp, Electron) follow their own licenses and are downloaded from the
  official sources during installation: [THIRD_PARTY_LICENSES](THIRD_PARTY_LICENSES/)
- Reporting security issues: [SECURITY.md](SECURITY.md) · Privacy: [PRIVACY.md](PRIVACY.md)