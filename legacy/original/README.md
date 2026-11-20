# 해커톤 당시 원본

로컬 `IBM-hackathon-program/test`에서 확인한 소스와 이미지 43개를 원래 상대 경로 그대로 복사했습니다. 이 README와 `SOURCE_MANIFEST.json`은 보관 내용을 설명하기 위해 추가한 파일입니다.

- [main.py](main.py): 홈 화면
- [pages/chat.py](pages/chat.py): 음성 대화와 전문·일기 저장
- [pages/diary.py](pages/diary.py) · [pages/read_diary.py](pages/read_diary.py): 일기 목록과 본문
- [mumu.py](mumu.py) · [mumu_cli.py](mumu_cli.py): 음성·텍스트 콘솔 버전
- [st_chatbot.py](st_chatbot.py) · [pages/mumu.py](pages/mumu.py): 함께 남아 있는 대화 버전
- [SYSTEMPROMPT.txt](SYSTEMPROMPT.txt) · [DIARYPROMPT.txt](DIARYPROMPT.txt): 대화와 일기 프롬프트
- [img/](img/) · [pages/img/](pages/img/): 당시 화면 이미지
- [더미/](더미/): 개별 기능과 이전 대화 처리 실험

`.env`, `__pycache__/`, `log_DB/`, `diary_DB/`의 개인 설정·캐시·실제 대화 기록은 제외했습니다. 복사한 파일의 SHA-256은 [파일 목록](SOURCE_MANIFEST.json)에 기록했습니다.

외부 서비스의 이용 기간 만료·당시 API 종료로 실행 가능한 완성본을 제공하는 목적은 아닙니다. 경로 처리나 API 호출, 중복 파일도 당시 상태를 보존했습니다.

[레거시 소개](../README.md) · [원본 코드 설명](../docs/CODE_GUIDE.md)
