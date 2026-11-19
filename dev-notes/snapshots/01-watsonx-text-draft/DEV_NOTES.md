# MUMU 복원 개발 기록

## 2026-11-13 · 텍스트 멀티턴 대화 복원

- 목표는 IBM AI 해커톤의 음성 챗봇을 다시 실행 가능한 상태로 복원하는 것이다. 첫 단계에서는 텍스트 입출력만 사용해 모델 응답과 문맥 유지부터 확인한다.
- `레거시/IBM-hackathon-program/test/SYSTEMPROMPT.txt`를 원본 바이트 그대로 복사한다. 매 호출마다 동일한 시스템 메시지를 전달하고, 이후 성공한 사용자·챗봇 턴을 순서대로 붙인다.
- 기존 IBM watsonx 연결을 LangChain의 `ChatWatsonx`로 옮긴다. 모델 ID는 레거시 값을 기본으로 하고, 계정에서 사용 가능한 모델에 맞춰 환경 변수로 바꿀 수 있게 한다.
- 대화 이력은 실행 중 메모리에 보관한다. 응답 실패 시 해당 턴은 이력에 추가하지 않는다. 장기 저장과 음성 입출력은 이후 단계에서 검토한다.
- 감정분석은 향후 Whisper 전사문을 대상으로 검토한다. 공개 한국어 감정 데이터로 문자 TF-IDF 기준 모델과 한국어 사전학습 모델을 비교하고, 실제 MUMU 전사문으로 별도 평가하는 방안을 논의했다. 이번 단계에는 구현하지 않는다.

## 실행

PowerShell에서 프로젝트 폴더로 이동한 뒤 실행한다.

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
Copy-Item .env.example .env
```

`.env`에 기존 watsonx의 `API_KEY`, `PROJECT_ID`, `IBM_CLOUD_URL`을 입력한다. 필요하면 `WATSONX_MODEL_ID`를 변경한다.

```powershell
.\.venv\Scripts\python.exe main.py
```

첫 턴에서 이름이나 좋아하는 음식을 말하고, 다음 턴에서 무엇이라고 했는지 물어 문맥 유지 여부를 확인한다. `/exit`로 종료한다.

## 검증 결과

- 원본과 복사한 시스템 프롬프트의 SHA-256 일치를 확인했다.
- Python 문법 검사와 모의 모델 테스트에서 이전 턴 전달, 실패한 턴 제외, 종료 처리를 확인했다.
- 현재 환경에서 패키지를 설치하지 못해 실제 watsonx 호출은 미검증이다.
