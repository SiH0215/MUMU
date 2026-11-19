import os
from pathlib import Path

from dotenv import load_dotenv
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_ibm import ChatWatsonx

ROOT = Path(__file__).resolve().parent
DEFAULT_MODEL = "meta-llama/llama-4-maverick-17b-128e-instruct-fp8"


def run_chat(model, system_prompt):
    history = [SystemMessage(content=system_prompt)]
    print("MUMU 텍스트 채팅 · /exit로 종료")
    while True:
        try:
            user_text = input("나: ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return

        if user_text == "/exit":
            return
        if not user_text:
            continue

        user_message = HumanMessage(content=user_text)
        try:
            reply = model.invoke([*history, user_message])
            if not reply.text.strip():
                raise ValueError("모델이 빈 답변을 반환했습니다.")
        except Exception as error:
            print(f"응답을 받지 못했습니다 ({type(error).__name__}).")
            continue

        history.extend((user_message, reply))
        print(f"MUMU: {reply.text}")


def main():
    load_dotenv(ROOT / ".env")
    required = ("API_KEY", "PROJECT_ID", "IBM_CLOUD_URL")
    missing = [key for key in required if not os.environ.get(key, "").strip()]
    if missing:
        raise SystemExit(f".env 설정이 필요합니다: {', '.join(missing)}")

    system_prompt = (ROOT / "SYSTEMPROMPT.txt").read_bytes().decode("utf-8-sig")
    try:
        model = ChatWatsonx(
            model_id=os.environ.get("WATSONX_MODEL_ID") or DEFAULT_MODEL,
            url=os.environ["IBM_CLOUD_URL"],
            project_id=os.environ["PROJECT_ID"],
            apikey=os.environ["API_KEY"],
        )
    except Exception as error:
        raise SystemExit(f"watsonx 연결 설정을 확인하세요 ({type(error).__name__}).") from None

    run_chat(model, system_prompt)


if __name__ == "__main__":
    main()
