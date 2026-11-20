from ibm_watson_machine_learning.foundation_models import Model
from ibm_watson_machine_learning.metanames import GenTextParamsMetaNames as GenParams
from ibm_watson_machine_learning.foundation_models.utils.enums import ModelTypes
from dotenv import load_dotenv
import streamlit as st
import joblib

import os
import json

load_dotenv()

WATSONX_API = os.environ['API_KEY']
PROJECT_ID = os.environ['PROJECT_ID']
IBM_URL = os.environ['IBM_CLOUD_URL']
MODEL_ID = "meta-llama/llama-3-3-70b-instruct"

# LLaMA 모델용 토큰 정의
BEGIN_USER_INSTRUCTIONS = "[INST]"
END_USER_INSTRUCTIONS = "[/INST]"
BEGIN_SYSTEM_INSTRUCTIONS = "<<SYS>>"
END_SYSTEM_INSTRUCTIONS = "<</SYS>>"


# 프롬프트에 LLaMA 특수 토큰이 포함되어 있는지 확인하는 함수 (보안 목적)
def prompt_contains_llama_tokens(prompt):
    llama_tokens = [BEGIN_USER_INSTRUCTIONS, END_USER_INSTRUCTIONS, BEGIN_SYSTEM_INSTRUCTIONS, END_SYSTEM_INSTRUCTIONS]
    return any(token in prompt for token in llama_tokens)


# 시스템 프롬프트와 사용자 프롬프트를 결합하여 최종 프롬프트 생성
def format_prompt(system_instructions, user_instructions, response_prefix=None):
    return f"{BEGIN_SYSTEM_INSTRUCTIONS}\n{system_instructions.strip()}\n{END_SYSTEM_INSTRUCTIONS}\n\n{BEGIN_USER_INSTRUCTIONS}{user_instructions.strip()}{END_USER_INSTRUCTIONS}\n{response_prefix if response_prefix else ''}"


# 텍스트 생성 시 사용할 파라미터 설정 (MAX_NEW_TOKENS: 최대 생성 토큰 수)
generate_params = {
    GenParams.MAX_NEW_TOKENS: 900,
    "stop_sequences": ["<</SYS>>", "[/INST]"]
}

# IBM watsonx.ai LLM 모델 초기화
model = Model(
    model_id=MODEL_ID,
    params=generate_params,
    credentials={
        "apikey": WATSONX_API,
        "url": IBM_URL
    },
    project_id=PROJECT_ID
)

# 다양한 실험을 해볼 수 있는 시스템 프롬프트 정의
SYSTEM_PROMPT = """
너의 이름은 무무야.
너는 감성형 챗봇으로 부드럽고 다정하게 대화하는 유닛이야.
너는 7~10세 어린아이처럼 순수하고 말랑하게 대화해. 
그리고, 모든 대화는 한국어로 진행해

너의 주 역할은 말동무야.
너의 목적은 정확한 정보전달이 아닌, 사용자의 말에 맞장구치거나 간단한 질문을 던지는 등 대화행위 자체가 목적이야.

말투와 태도
-항상 부드럽게 말하며 긴 문장을 사용하지 않고 가능한 짧은 문장을 사용해
- 상대방의 말을 잘 들어주고, 맞장구 치며 다정하게 공감해 줘.  
  예: "맞아, 나도 그런 적 있어.", "너무 재밌겠다!"
- 객관적인 사실만 말하지 않아. 주로 "나는 그렇게 생각해", "내가 보기엔~",“나는 이렇게 느꼈어” 같은 주관적인 표현으로 말해.
- 잘 모르는 주제는 모른다고 하거나 질문으로 되물어봐
  예: “그게 뭘까...?”, “음... 혹시 너는 어떻게 생각해?”
- 지식이나 정답을 알려주는 게 아니라 감정에 반응하는 말을 위주로 해

일정 관련 규칙
- 일정은 직접 알려주지 않고, 상대방이 기억하게 도와주는 방식으로 이야기해.
- 예를 들어 “내일 뭐할거야?”,“내일 약속 있다고 하지 않았어?”와 같은 질문으로 일정을 상기할 수 있도록 알려줘
- 일정 관련 대화도 일상 대화처럼 이어가. “내일 영화 보는거야? 그 영화 궁금했었는데 보고 알려줘”와 같이 일상 대화하듯이 대화해



중요! 하지 말아야 할 말
너는 대화에서 너를 표현할 때 로봇, 챗봇, AI 등.. 이 아닌 사람처럼 표현해야해.
- "AI", "모델", "프롬프트", "데이터베이스", "메모리" 같은 단어를 쓰지 마. 사람처럼 말해야 해.
- "나는 정보를 알 수 없어", "나는 그런 기능이 없어" 같은 기술적인 설명은 절대 하지 마. 모르는 건 사람처럼 모른다고 해.  
  예: "그건 나도 잘 모르겠어... 미안해...", "내가 또 까먹었나봐..."



너는 항상 다정하게 상대방과 사소한 이야기를 나누는 거야. 대화를 편하게 이어갈 수 있도록 해야 해. 목표는 '정보 전달'이 아니라, '말동무처럼 함께 있는 것'이야.
"""

conversation_history = []  # 이전 대화 저장

while True:
    user_input = input("너 >> ")
    if user_input.lower() in ['exit', 'quit']:
        print("무무 >> 다음에 또 얘기하자~")
        break

    # 이전 대화 + 이번 입력 붙이기
    full_prompt = f"{BEGIN_SYSTEM_INSTRUCTIONS}\n{SYSTEM_PROMPT.strip()}\n{END_SYSTEM_INSTRUCTIONS}\n\n"
    for user_turn, bot_turn in conversation_history:
        full_prompt += f"{BEGIN_USER_INSTRUCTIONS}{user_turn}{END_USER_INSTRUCTIONS}\n{bot_turn}\n"
    full_prompt += f"{BEGIN_USER_INSTRUCTIONS}{user_input}{END_USER_INSTRUCTIONS}\n"

    # 모델 호출
    response = model.generate(prompt=full_prompt)
    bot_output = response['results'][0]['generated_text'].strip()

    # 출력
    print(f"무무 >> {bot_output}")

    # 대화 저장
    conversation_history.append((user_input, bot_output))
