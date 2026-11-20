# 해커톤 원본 코드 설명

이 문서는 [original/](../original/)에 보관한 `IBM-hackathon-program/test`의 코드를 기준으로 작성했습니다. 코드의 함수 호출과 저장 흐름을 확인한 내용이며, 당시 외부 서비스의 연결을 재검증한 결과는 아닙니다.

## 파일 구성

| 파일 | 역할 |
|---|---|
| [main.py](../original/main.py) | 이미지 기반 홈 화면. 대화와 일기장으로 이동 |
| [pages/chat.py](../original/pages/chat.py) | 음성 대화, 말풍선 렌더링, 종료 후 전문·일기 저장 |
| [pages/diary.py](../original/pages/diary.py) | 일기 파일 목록과 제목 표시 |
| [pages/read_diary.py](../original/pages/read_diary.py) | 선택한 일기의 제목·본문 열람 |
| [mumu.py](../original/mumu.py) | 콘솔 음성 대화와 전문·일기 저장 |
| [mumu_cli.py](../original/mumu_cli.py) | 텍스트 콘솔 대화. 최근 5개 대화 쌍 전달, 전문·일기 저장 |
| [st_chatbot.py](../original/st_chatbot.py) | 별도로 남아 있는 Streamlit 음성 대화 버전 |
| [pages/mumu.py](../original/pages/mumu.py) | 콘솔 음성 대화 코드. 루트 `mumu.py`와 내용이 동일 |
| [SYSTEMPROMPT.txt](../original/SYSTEMPROMPT.txt) | 대화 성격과 행동 지침 원본 |
| [DIARYPROMPT.txt](../original/DIARYPROMPT.txt) | 무무의 1인칭 일기·제목 생성 지침 원본 |
| [img/](../original/img/) · [pages/img/](../original/pages/img/) | 홈·대화·일기장 이미지. 중복 파일도 원래 위치 그대로 보관 |
| [더미/](../original/더미/) | STT·TTS 개별 연동과 이전 모델·프롬프트를 시험한 코드 |

## 홈과 화면 이동

`main.py`는 홈 이미지를 base64로 바꿔 HTML에 삽입합니다. ‘이야기’와 ‘일기장’ 이미지 링크는 각각 `chat`, `diary` 페이지로 연결됩니다. `import mumu`도 포함되어 있어 홈 코드를 읽는 과정에서 환경변수·프롬프트·watsonx 모델 초기화가 함께 실행되는 구조입니다.

## 음성 대화의 한 턴

`pages/chat.py`에서 ‘대화하기’를 누르면 다음 처리를 반복합니다.

1. `record_audio()`가 PyAudio 입력을 16kHz·모노·16비트로 5초 녹음하고 float32 배열로 변환합니다.
2. `stt()`가 `whisper.load_model("base")`를 호출하고 `language="ko"`로 전사합니다. 모델 로딩 호출은 매 턴 함수 내부에 있습니다.
3. 사용자 문장을 `st.session_state.history`에 넣고 말풍선으로 표시합니다.
4. 종료 문구인지 확인합니다. 일반 발화이면 `chatbot_response()`로 답변을 생성합니다.
5. 답변을 같은 이력 항목에 넣고 화면에 표시한 뒤 `speak()`로 읽어줍니다.
6. 음성 재생이 끝나면 다음 녹음으로 돌아갑니다.

VAD로 말소리의 시작·끝을 판단하는 방식은 없으며, 마이크 입력과 음성 재생은 Streamlit 서버를 실행한 컴퓨터에서 처리합니다.

## LLM 요청과 대화 이력

모델 ID는 `meta-llama/llama-4-maverick-17b-128e-instruct-fp8`입니다. 최대 생성 토큰은 900으로 설정하고 `<|eot|>`를 종료 시퀀스로 전달합니다.

`build_prompt()`는 시스템 프롬프트 → 이전 사용자·무무 발화 → 현재 입력 → assistant 헤더 순서로 문자열을 구성합니다. 응답은 `results[0]['generated_text']`에서 꺼내 `<|eot|>` 이후를 잘라내고, 화면 버전은 ‘무무 >>’, ‘assistant:’ 같은 말머리도 제거합니다.

| 버전 | 다음 답변에 전달하는 기록 |
|---|---|
| `pages/chat.py` | 현재 화면 세션에 누적한 이력 |
| `mumu.py` | 현재 콘솔 대화의 전체 이력 |
| `mumu_cli.py` | 현재 콘솔 대화 중 최근 5개 쌍 |
| 재구성본 `mumu/` | 최근 5개 쌍만 내부에 유지 |

화면 버전은 현재 발화를 이력에 먼저 추가한 뒤, `build_prompt()`에 현재 입력으로도 넘깁니다. 따라서 해당 발화가 요청에 두 번 들어가는 부분이 원본에 남아 있습니다. 보관본에서는 이를 수정하지 않았습니다.

과거 세션의 `log_DB` 파일을 읽어 다음 대화에 넣거나, 임베딩·벡터 검색으로 참조하는 코드는 없습니다.

## Supertone 합성과 재생

`speak()`는 `https://supertoneapi.com/v1/text-to-speech/{VOICE_ID}`로 요청합니다. 한국어, `Sad` 스타일, `sona_speech_1`, WAV 형식, 속도 1.1 설정이 남아 있습니다. 음성 Content-Type 응답을 임시 WAV로 저장한 뒤 pygame으로 재생합니다.

이 원본 함수에는 요청 타임아웃, 재생 후 임시 파일 삭제, JSON 음성 URL 응답 처리 등이 없습니다. 재구성본에 추가된 예외 처리나 자원 정리는 당시 원본의 기능으로 기술하지 않았습니다.

## 대화 종료와 일기 저장

종료 문구는 인식된 문자열과 정확히 비교합니다. 화면 버전의 루프가 끝나면 다음 처리를 수행합니다. STT·답변 처리 오류로 루프를 빠져나간 경우에도 이 저장 코드에 도달할 수 있습니다.

1. `get_next_indexed_filename()`이 폴더의 기존 번호를 확인해 다음 파일명을 정합니다.
2. 전체 세션 이력을 `log_DB/log_번호.txt`에 저장합니다.
3. `summarize_conversation()`이 일기 프롬프트와 전체 이력을 같은 watsonx 모델에 보냅니다.
4. 요약 결과를 `diary_DB/diary_번호.txt`에 저장합니다.

원본 일기 프롬프트는 무무가 ‘나’로, 상대를 ‘너’로 부르며 3~4문장의 일기를 작성하고 마지막 줄에 3단어 이하 제목을 쓰도록 지시합니다. 별도 감정 분류 모델을 실행하는 구조는 아닙니다.

## 일기 조회

`pages/diary.py`는 `diary_DB`의 텍스트 파일을 수정 시각의 내림차순으로 정렬합니다. 마지막 3개의 비어 있지 않은 줄에서 ‘제목:’을 찾고, 없으면 마지막 줄을 제목으로 사용합니다.

`pages/read_diary.py`는 `file` 쿼리의 파일명을 `os.path.basename()`으로 처리해 일기 폴더에서 찾습니다. 제목과 본문을 분리하고 HTML 문자를 이스케이프해 표시합니다. 전문 로그를 말풍선으로 다시 보는 화면은 없습니다.

## 보관 기준

원본 소스와 이미지의 내용은 변경하지 않았습니다. 과거 파일의 구문은 외부 API 호출 없이 검사했으며, 자격 증명과 실제 대화·일기는 업로드하지 않았습니다. [SOURCE_MANIFEST.json](../original/SOURCE_MANIFEST.json)의 SHA-256으로 원본과 복사본을 비교할 수 있습니다.

`mumu/`, `mumu_legacy.py`, `tests/`는 별도 재구성본입니다. 해당 테스트 결과와 동작 설명은 [재구성 코드 설명](RECONSTRUCTED_CODE.md)을 참고하세요.
