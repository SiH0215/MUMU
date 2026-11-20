import os
import re
from dotenv import load_dotenv
from ibm_watson_machine_learning.foundation_models import Model
from ibm_watson_machine_learning.metanames import GenTextParamsMetaNames as GenParams

# 환경 변수 로드
load_dotenv()
WATSONX_API = os.environ['API_KEY']
PROJECT_ID = os.environ['PROJECT_ID']
IBM_URL = os.environ['IBM_CLOUD_URL']

# 시스템 프롬프트 로드
with open("SYSTEMPROMPT.txt", "r", encoding="utf-8") as f:
    SYSTEM_PROMPT = f.read()

with open("DIARYPROMPT.txt", "r", encoding="utf-8") as f:
    DIARY_PROMPT = f.read()

# 특수 토큰
BOS = "<|begin_of_text|>"
EOT = "<|eot|>"
USER_TAG = "<|header_start|>user<|header_end|>"
SYS_TAG = "<|header_start|>system<|header_end|>"
ASSISTANT_TAG = "<|header_start|>assistant<|header_end|>"

# 모델 설정
MODEL_ID = "meta-llama/llama-4-maverick-17b-128e-instruct-fp8"
generate_params = {
    GenParams.MAX_NEW_TOKENS: 900,
    "stop_sequences": [EOT]
}

model = Model(
    model_id=MODEL_ID,
    params=generate_params,
    credentials={"apikey": WATSONX_API, "url": IBM_URL},
    project_id=PROJECT_ID
)

# 프롬프트 생성
def build_prompt(system, history, user_input):
    prompt = f"{BOS}\n{SYS_TAG}\n{system.strip()}\n{EOT}\n"
    for u, b in history:
        prompt += f"{USER_TAG}\n{u.strip()}\n{EOT}\n"
        prompt += f"{ASSISTANT_TAG}\n{b.strip()}\n{EOT}\n"
    prompt += f"{USER_TAG}\n{user_input.strip()}\n{EOT}\n"
    prompt += f"{ASSISTANT_TAG}\n"
    return prompt

# 요약 프롬프트
def build_summary_prompt(system, history):
    prompt = f"{BOS}\n{SYS_TAG}\n{system.strip()}\n{EOT}\n"
    for u, b in history:
        prompt += f"{USER_TAG}\n{u.strip()}\n{EOT}\n"
        prompt += f"{ASSISTANT_TAG}\n{b.strip()}\n{EOT}\n"
    prompt += f"{ASSISTANT_TAG}\n"
    return prompt

# 응답 정리
def clean_response(text):
    return text.split(EOT)[0].strip()

# 특수 토큰 검사
def contains_reserved_tokens(text):
    return any(token in text for token in [BOS, EOT, USER_TAG, SYS_TAG, ASSISTANT_TAG])

# 자동 파일 이름 생성
def get_next_indexed_filename(folder, base_name, ext="txt"):
    os.makedirs(folder, exist_ok=True)
    existing = [f for f in os.listdir(folder) if f.startswith(base_name) and f.endswith(f".{ext}")]
    indices = [int(re.findall(rf"{base_name}_(\d+)\.{ext}", f)[0]) for f in existing if re.findall(rf"{base_name}_(\d+)\.{ext}", f)]
    next_index = max(indices) + 1 if indices else 1
    return os.path.join(folder, f"{base_name}_{next_index}.{ext}")

# 요약 생성
def summarize_conversation(conversation):
    prompt = build_summary_prompt(DIARY_PROMPT, conversation)
    response = model.generate(prompt=prompt)
    return clean_response(response['results'][0]['generated_text'])

# 대화 상태
conversation_history = []
MAX_HISTORY = 5

# 시작
print("무무 >> 안녕~ 나는 무무야! 같이 얘기하자 :)")
print("       (종료하려면 '종료', 초기화는 '/초기화' 입력)")

while True:
    user_input = input("너 >> ").strip()

    if user_input.lower() in ["종료"]:
        print("무무 >> 다음에 또 얘기하자~ 잘 가!")
        break

    if user_input == '/초기화':
        conversation_history.clear()
        print("무무 >> 내가 까먹었어~ 처음부터 다시 얘기하자 :)")
        continue

    if contains_reserved_tokens(user_input):
        print("무무 >> 앗... 그런 특이한 기호는 말에 넣지 말아줘~")
        continue

    prompt = build_prompt(SYSTEM_PROMPT, conversation_history[-MAX_HISTORY:], user_input)

    try:
        response = model.generate(prompt=prompt)
        raw_output = response['results'][0]['generated_text'].strip()
        bot_output = clean_response(raw_output)
    except Exception:
        bot_output = "앗... 나 지금 잠깐 말을 잘 못했어... 다시 한 번 말해줄래?"
        print(f"무무 >> {bot_output}")
        continue

    print(f"무무 >> {bot_output}")
    conversation_history.append((user_input, bot_output))

# 종료 후 저장
log_filename = get_next_indexed_filename("log_DB", "log")
with open(log_filename, "w", encoding="utf-8") as f:
    for user, bot in conversation_history:
        f.write(f"너 >> {user}\n")
        f.write(f"무무 >> {bot}\n\n")
print(f"[✅] 대화 기록 저장됨: {log_filename}")

summary = summarize_conversation(conversation_history)
diary_filename = get_next_indexed_filename("diary_DB", "diary")
with open(diary_filename, "w", encoding="utf-8") as f:
    f.write(summary)
print(f"[📝] 요약본 저장됨: {diary_filename}")
