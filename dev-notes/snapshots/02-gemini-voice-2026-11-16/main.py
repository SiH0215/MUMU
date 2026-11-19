import argparse
import os
from contextlib import closing
from pathlib import Path

from dotenv import dotenv_values, load_dotenv
from langchain.chat_models import init_chat_model
from langchain_core.messages import HumanMessage, SystemMessage

ROOT = Path(__file__).resolve().parent
DEFAULT_MODEL = "google_genai:gemini-3.5-flash-lite"


def text_input():
    print("MUMU 텍스트 채팅 · /exit로 종료")
    while True:
        try:
            yield input("나: ")
        except EOFError:
            return


def run_chat(model, system_prompt, messages=None):
    history = [SystemMessage(content=system_prompt)]
    if messages is None:
        messages = text_input()
    for user_text in messages:
        user_text = user_text.strip()
        if user_text == "/exit":
            return
        if not user_text:
            continue

        user_message = HumanMessage(content=user_text)
        try:
            reply = model.invoke([*history, user_message])
            reply_text = reply.text
            if not reply_text.strip():
                raise ValueError("모델이 빈 답변을 반환했습니다.")
        except Exception as error:
            detail = type(error).__name__
            status = getattr(error.__cause__ or error, "status", None)
            if status == "RESOURCE_EXHAUSTED":
                detail = "모델 제공자의 사용량 또는 결제 한도를 확인하세요"
            print(f"응답을 받지 못했습니다 ({detail}).")
            continue

        history.extend((user_message, reply))
        print(f"MUMU: {reply_text}")


def main():
    parser = argparse.ArgumentParser(description="MUMU 멀티턴 채팅")
    parser.add_argument("--voice", action="store_true", help="마이크 음성 입력 사용")
    parser.add_argument("--silence-ms", type=int, default=800, help="발화 종료 대기 시간(ms)")
    args = parser.parse_args()
    if not 100 <= args.silence_ms <= 3000:
        parser.error("--silence-ms는 100~3000 사이여야 합니다.")

    env_path = ROOT / ".env"
    file_settings = dotenv_values(env_path)
    load_dotenv(env_path)
    model_name = os.getenv("MUMU_MODEL", "").strip() or DEFAULT_MODEL
    model_options = {}
    if model_name.startswith("google_genai:"):
        key_names = ("GOOGLE_API_KEY", "GEMINI_API_KEY")
        api_key = next(
            (
                value.strip()
                for settings in (file_settings, os.environ)
                for name in key_names
                if (value := settings.get(name)) and value.strip()
            ),
            None,
        )
        if api_key is None:
            raise SystemExit("Gemini 연결에 GOOGLE_API_KEY 또는 GEMINI_API_KEY가 필요합니다.")
        model_options["api_key"] = api_key

    system_prompt = (ROOT / "SYSTEMPROMPT.txt").read_bytes().decode("utf-8-sig")
    try:
        model = init_chat_model(model_name, **model_options)
    except (ImportError, ValueError) as error:
        raise SystemExit(
            f"LangChain 모델 설정을 확인하세요 ({model_name}, {type(error).__name__})."
        ) from None

    try:
        if args.voice:
            try:
                from voice import voice_input
            except ImportError:
                raise SystemExit("음성 의존성을 설치하세요. README의 음성 모드 설정을 참고하세요.") from None

            with closing(voice_input(args.silence_ms)) as messages:
                run_chat(model, system_prompt, messages)
        else:
            run_chat(model, system_prompt)
    except KeyboardInterrupt:
        print()
    except (OSError, RuntimeError) as error:
        if not args.voice:
            raise
        raise SystemExit(f"음성 모드를 실행하지 못했습니다. 마이크와 모델을 확인하세요. ({error})") from None


if __name__ == "__main__":
    main()
