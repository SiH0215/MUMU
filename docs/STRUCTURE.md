# 저장소 구조

현재 실행 코드와 실험·개발 기록을 역할별로 나누어 배치하였습니다.

```text
MUMU/
├── app.py                 # 웹 실행 진입점
├── mumu/                  # 현재 무무 구현
│   ├── web.py             # Flask API와 세션·마이크 제어
│   ├── chat.py            # LLM 연결과 멀티턴 대화
│   ├── memory.py          # 대화 저장·검색과 일기 생성
│   ├── voice.py           # Whisper·VAD 음성 입력
│   ├── turns.py           # 발화 구간 판단
│   ├── paths.py           # 설정·데이터·캐시 경로 기준
│   ├── prompts/           # 대화·일기 프롬프트
│   ├── templates/         # 화면 HTML
│   └── static/            # JavaScript·CSS·이미지
├── experiments/           # STT 평가 스크립트와 학습 노트북
├── requirements/          # 기본·웹·음성 패키지 목록
├── tests/                 # 회귀 테스트와 화면 상태 테스트
├── docs/                  # 개선 결과·화면 캡처·구조 설명
├── dev-notes/             # 개발일지와 초기 코드 스냅샷
├── legacy/                # 해커톤 당시 코드
├── requirements.txt       # 기본 패키지 목록 연결
└── README.md              # 프로젝트 소개
```

설정 파일 `.env`, 대화 기록 `memory_DB/`, 모델 캐시 `.cache/`는 저장소 루트를 기준으로 유지하였습니다. 해당 개인 설정과 데이터는 Git에 포함하지 않도록 구성하였습니다.

웹 실행은 기존 `app.py` 진입점을 유지하였습니다. 콘솔 대화는 `mumu` 패키지의 실행 진입점에, STT 평가는 `experiments.evaluate_stt` 모듈에 배치하였습니다.

[프로젝트 소개](../README.md) · [개선 결과](IMPROVEMENTS.md) · [개발일지](../dev-notes/DEV_LOG.md)
