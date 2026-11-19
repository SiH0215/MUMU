# MUMU 텍스트 채팅

PowerShell에서 MUMU와 대화합니다. LangChain은 `SYSTEMPROMPT.txt`의 무무 시스템 프롬프트와 이전 대화를 매 요청에 모델로 전달합니다. 대화 기록은 실행 중 메모리에 보관합니다.

## 처음 설정하기

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

기본 모델은 Gemini 3.5 Flash-Lite입니다. 환경 변수 또는 프로젝트의 `.env`에 `GEMINI_API_KEY`나 `GOOGLE_API_KEY`를 설정하세요. 프로젝트의 `.env`에 키가 있으면 터미널 환경 변수보다 우선합니다.

모델을 바꾸려면 해당 LangChain 연동 패키지를 설치하고 `MUMU_MODEL`에 `제공자:모델명`을 지정하세요.

## 실행하기

```powershell
.\.venv\Scripts\python.exe main.py
```

첫 턴에 좋아하는 음식을 말하고, 다음 턴에 방금 말한 음식이 무엇인지 물어보세요. `/exit`를 입력하면 종료합니다.

## 마이크로 대화하기

PowerShell에서 음성 패키지를 설치합니다. 아래 명령은 CPU로 실행하는 설정입니다.

```powershell
.\.venv\Scripts\python.exe -m pip install torch torchaudio --index-url https://download.pytorch.org/whl/cpu
.\.venv\Scripts\python.exe -m pip install -r requirements-voice.txt
.\.venv\Scripts\python.exe main.py --voice
```

처음 실행할 때 Whisper `base` 모델을 프로젝트의 `.cache/whisper`에 내려받습니다.
16kHz 모노 마이크 입력을 Silero VAD로 검사하고 발화가 감지될 때만 Whisper로 한국어를 전사합니다. 감지 전 약 224ms를 보관해 첫 음절을 살리고, 말소리가 800ms 동안 멈추면 한 턴을 넘깁니다. 그 전에 다시 말하면 같은 턴으로 이어집니다. 아주 짧은 감지 신호와 빈 전사문은 건너뜁니다.
전사문과 무무의 답변을 터미널에 표시합니다. Whisper는 로컬에서 실행되고, 전사문이 대화 이력과 함께 Gemini로 전송됩니다. 음성 모드는 Ctrl+C로 종료합니다.

중간에 쉬어 말할 때 자주 끊기면 `--silence-ms 1200`으로, 빠른 응답을 원하면 `--silence-ms 400`으로 비교할 수 있습니다. 포트폴리오 수치는 아래 방식으로 평가용 녹음에서 측정합니다.

## STT 비교 평가

비교에 사용할 원본 WAV를 16kHz 모노 PCM16으로 준비합니다. WAV 하나에 의도한 대화 턴 하나를 담고, 녹음 시작 기준으로 실제 발화가 끝난 시각을 ms로 표시합니다. 무음이나 배경 소음만 있는 샘플은 두 칸을 모두 비웁니다. 아래는 CSV 형식의 예시입니다.

```csv
wav,reference,speech_end_ms
short.wav,오늘 산책했어,2050
room-noise.wav,,
```

```powershell
.\.venv\Scripts\python.exe evaluate_stt.py samples.csv --silence-ms 800
```

같은 WAV와 Whisper 설정으로 첫 5초 고정 녹음, Silero 기본 VAD 이벤트, 무무의 발화 종료 로직을 비교합니다. 글자 오류율(CER)은 띄어쓰기와 문장부호를 제외해 계산합니다. 조기 종료, 미전사, 무발화 오인식을 집계하고, 정상적으로 끝난 샘플의 대기 시간은 WAV의 감지 시각과 실제 Whisper 처리 시간을 합쳐 추정합니다. 실제 마이크나 Gemini 응답 시간은 이 수치에 포함되지 않습니다.
