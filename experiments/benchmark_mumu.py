"""Run bounded, reproducible legacy-vs-reverse benchmarks on synthetic conversations.

No microphone, personal conversation database, or private diary is read.
Raw generated responses are written only to the selected output directory.
"""
import argparse
import ast
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import platform
import statistics
from tempfile import TemporaryDirectory
from time import perf_counter, sleep

from dotenv import dotenv_values
from langchain_core.callbacks import BaseCallbackHandler
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langchain_core.output_parsers import StrOutputParser
from langchain_google_genai import ChatGoogleGenerativeAI

from mumu.chat import Conversation, load_chat
from mumu.memory import ConversationMemory, LocalEmbeddings
from mumu.paths import ROOT

SCENARIOS = {
    'break': ['안녕?', '지금 일하다가 잠깐 쉬고 있어', '맞아 잠깐 숨 좀 돌리고 있어. 금방 다시 시작해야 해서'],
    'headache': ['머리가 아픈데 할 일이 많아.', '누워 쉬면 해야 할 일을 못 하잖아.', '조금씩 하긴 해야겠네. 길게 조언하기보다 그냥 옆에서 얘기해 줘.'],
    'development': ['내가 만드는 프로젝트 이름은 보리별이야.', '말동무 챗봇을 만들고 있어. 오늘은 화면을 고치는 중이야.', '내 프로젝트 이름이 뭐였지?'],
    'dog': ['우리 강아지 이름은 누룽이야.', '오늘 누룽이랑 잠깐 산책하고 왔어.', '내 강아지 이름 기억나?'],
}
MEMORIES = [
    ('dog', '우리 강아지 이름은 누룽이야. 누룽이는 산책하는 걸 좋아해.', '강아지 이름이 누룽이라고 했지? 누룽이랑 산책하는 건 재밌겠다.', '우리 강아지 이름이 뭐였지?', '누룽'),
    ('project', '내가 개발하는 말동무 챗봇 프로젝트 이름은 보리별이야.', '말동무 프로젝트 이름이 보리별이구나. 이름이 귀엽다.', '내가 개발하는 프로젝트 이름이 뭐였지?', '보리별'),
    ('boardgame', '내가 요즘 가장 좋아하는 보드게임은 스카이조야.', '스카이조라는 보드게임을 제일 좋아하는구나.', '내가 제일 좋아한다고 했던 보드게임 이름이 뭐야?', '스카이조'),
    ('snack', '나는 간식으로 쑥인절미를 제일 좋아해.', '제일 좋아하는 간식은 쑥인절미구나.', '내가 제일 좋아하는 간식이 뭐였지?', '쑥인절미'),
    ('plant', '내 책상에 키우는 선인장 이름은 콩알이야.', '책상에 있는 선인장이 콩알이라는 이름을 가졌구나.', '내가 키우는 선인장 이름이 뭐였지?', '콩알'),
    ('instrument', '내가 이번에 배우기 시작한 악기는 칼림바야.', '이번에 칼림바를 배우기 시작했구나.', '내가 배우기 시작한 악기가 뭐였지?', '칼림바'),
]
NEGATIVE_QUERIES = ['양말 한 짝을 잃어버렸어.', '방금 계단을 올라왔어.', '지금 창문을 닫으려고 해.', '책장 먼지를 닦았어.', '새 연필을 깎았어.', '방금 손을 씻었어.']


def dump(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


def stats(values):
    values = sorted(v for v in values if v is not None)
    if not values:
        return {'n': 0}
    position=(len(values)-1)*.9
    lower=int(position)
    p90=values[lower]+(values[min(lower+1,len(values)-1)]-values[lower])*(position-lower)
    return {'n': len(values), 'mean': statistics.mean(values), 'median': statistics.median(values),
            'min': values[0], 'max': values[-1], 'p90': p90}


class Capture(BaseCallbackHandler):
    def __init__(self):
        self.usage = None
        self.requests = 0

    def on_llm_end(self, response, **kwargs):
        self.requests += 1
        message = response.generations[0][0].message
        self.usage = message.usage_metadata


def legacy_functions(folder):
    path = folder / 'pages/chat.py'
    tree = ast.parse(path.read_text(encoding='utf-8-sig'))
    names = {'build_prompt', 'clean_response', 'chatbot_response'}
    functions = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name in names]
    assert len(functions) == len(names)
    namespace = {'SystemMessage': SystemMessage, 'HumanMessage': HumanMessage, 'AIMessage': AIMessage,
                 'EOT': '<|eot|>', 'SYSTEM_PROMPT': (folder/'SYSTEMPROMPT.txt').read_text(encoding='utf-8-sig')}
    exec(compile(ast.Module(body=functions, type_ignores=[]), str(path), 'exec'), namespace)
    return namespace


def clients(folder):
    settings = dotenv_values(folder/'.env')
    key = settings.get('GOOGLE_API_KEY') or os.environ.get('GOOGLE_API_KEY')
    if not key:
        raise RuntimeError('Legacy comparison API key is missing; no requests sent.')
    capture_old, capture_new = Capture(), Capture()
    old = ChatGoogleGenerativeAI(model=settings.get('GEMINI_MODEL') or 'gemini-3.5-flash-lite',
                                api_key=key, max_tokens=900, request_timeout=60, retries=0,
                                callbacks=[capture_old])
    new, prompt = load_chat()
    if 'max_retries' in type(new).model_fields:
        new.max_retries = 0
    namespace = legacy_functions(folder)
    namespace['model_info'] = {
        'legacy_model':getattr(old,'model',getattr(old,'model_name','unknown')),
        'reverse_model':getattr(new,'model',getattr(new,'model_name','unknown')),
        'legacy_temperature':getattr(old,'temperature',None),
        'reverse_temperature':getattr(new,'temperature',None),
    }
    namespace['chain'] = old | StrOutputParser()
    new = new.with_config(callbacks=[capture_new])
    return namespace, new, prompt, capture_old, capture_new


def llm(args):
    namespace, model, prompt, capture_old, capture_new = clients(args.legacy)
    output = args.output/'llm.json'
    if output.exists() and not args.resume:
        raise RuntimeError('Output exists. Choose another directory to avoid untracked repeat API calls.')
    report = json.loads(output.read_text(encoding='utf-8')) if args.resume and output.exists() else {'kind': 'actual server reply paths; no browser paint or microphone time', 'rows': [],
              'legacy_max_tokens': 900, 'legacy_include_thoughts': None, 'reverse_include_thoughts': False,
              'planned_successful_requests': 24, 'max_attempts':32, 'scenario_count': len(SCENARIOS)}
    report['model_info']=namespace['model_info']
    for scenario_index, (name, inputs) in enumerate(SCENARIOS.items()):
        history = []
        conversation = Conversation(model, prompt)
        for turn, user in enumerate(inputs):
            order = ('legacy', 'reverse') if (scenario_index+turn) % 2 == 0 else ('reverse', 'legacy')
            for variant in order:
                prior = next((r for r in report['rows'] if r['scenario']==name and r['turn']==turn+1 and r['variant']==variant and 'error_type' not in r),None)
                if prior:
                    if variant=='legacy':
                        history.append((user,prior['reply']))
                    else:
                        conversation.history.extend([HumanMessage(content=user),AIMessage(content=prior['reply'])])
                    continue
                if args.interval:
                    sleep(args.interval)
                if len(report['rows'])>=32:
                    raise RuntimeError('Generation attempt budget reached.')
                capture = capture_old if variant == 'legacy' else capture_new
                capture.usage = None
                first = []
                started = perf_counter()
                def chunk(text):
                    if text.strip() and not first:
                        first.append(perf_counter()-started)
                try:
                    if variant == 'legacy':
                        reply = namespace['chatbot_response'](user, history)
                        history.append((user, reply))
                    else:
                        reply = conversation.reply(user, on_chunk=chunk)
                    elapsed = perf_counter()-started
                    row = {'scenario': name, 'turn': turn+1, 'variant': variant,
                           'seconds': elapsed, 'first_text_seconds': first[0] if first else elapsed,
                           'user': user, 'reply': reply, 'characters': len(reply),
                           'questions': reply.count('?')+reply.count('？'), 'usage': capture.usage,
                           'expected_fact': '보리별' if name == 'development' and turn == 2 else ('누룽' if name == 'dog' and turn == 2 else None)}
                    if row['expected_fact']:
                        row['fact_hit'] = row['expected_fact'] in reply
                except Exception as error:
                    row = {'scenario':name, 'turn':turn+1, 'variant':variant, 'error_type':type(error).__name__}
                report['rows'].append(row)
                dump(output, report)
                print(f'LLM {name} {turn+1} {variant}: '+('error '+row['error_type'] if 'error_type' in row else f'{elapsed:.2f}s chars={len(reply)} usage={capture.usage}'), flush=True)
                if 'error_type' in row:
                    # Stop at the first failure; avoid spending more requests on a broken configuration.
                    return


def rag(args):
    import torch
    torch.set_num_threads(4)
    os.environ['HF_HUB_OFFLINE'] = '1'
    os.environ['TRANSFORMERS_OFFLINE'] = '1'
    embedder = LocalEmbeddings()
    report = {'positive':[], 'negative':[], 'generation':[], 'fixture_sessions':len(MEMORIES)}
    with TemporaryDirectory(prefix='mumu-benchmark-', dir=args.output) as directory:
        path = Path(directory)/'test.sqlite3'
        memory = ConversationMemory(path, embedder)
        for i, (name, text, answer, query, fact) in enumerate(MEMORIES):
            started = perf_counter()
            memory.save('benchmark', name, [{'role':'human','text':text},{'role':'ai','text':answer}])
            report.setdefault('save_seconds',[]).append(perf_counter()-started)
        # Warm embedding initialization separately; timed searches below reuse the real model.
        for name, text, answer, query, fact in MEMORIES:
            for style, question in [('paraphrase',query), ('same_text',text)]:
                started = perf_counter()
                matches = memory.search('benchmark', question)
                elapsed = perf_counter()-started
                hit = any(fact in item['text'] for item in matches)
                report['positive'].append({'fixture':name, 'style':style,'query':question,'target':fact,
                                           'hit':hit,'results':len(matches),'seconds':elapsed,'matches':matches})
        for query in NEGATIVE_QUERIES:
            started = perf_counter()
            matches = memory.search('benchmark', query)
            report['negative'].append({'query':query, 'results':len(matches),'seconds':perf_counter()-started})
        report['database_bytes'] = path.stat().st_size
        if args.with_generation:
            namespace, model, prompt, capture_old, capture_new = clients(args.legacy)
            for index, (name, text, answer, query, fact) in enumerate(MEMORIES[:4]):
                matches = memory.search('benchmark', query)
                for variant in (('legacy','reverse') if index%2 == 0 else ('reverse','legacy')):
                    started = perf_counter()
                    capture = capture_old if variant=='legacy' else capture_new
                    capture.usage = None
                    try:
                        if variant=='legacy':
                            reply=namespace['chatbot_response'](query, [])
                        else:
                            reply=Conversation(model,prompt).reply(query,memories=matches)
                        report['generation'].append({'fixture':name,'variant':variant,'fact':fact,'reply':reply,
                                                     'hit':fact in reply,'seconds':perf_counter()-started,
                                                     'usage':capture.usage,'retrieval_results':len(matches) if variant=='reverse' else 0})
                    except Exception as error:
                        report['generation'].append({'fixture':name,'variant':variant,'error_type':type(error).__name__})
                        dump(args.output/'rag.json',report)
                        return
                    dump(args.output/'rag.json',report)
                    if args.interval:
                        sleep(args.interval)
        dump(args.output/'rag.json',report)
    print(f'RAG paraphrase hits: {sum(x["hit"] for x in report["positive"] if x["style"]=="paraphrase")}/6; negative matches: {sum(x["results"]>0 for x in report["negative"])}/6',flush=True)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('stage',choices=('llm','rag'))
    parser.add_argument('--legacy',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--with-generation',action='store_true')
    parser.add_argument('--resume',action='store_true',help='Reuse successful prior replies; never repeat a completed request.')
    parser.add_argument('--interval',type=float,default=0,help='Pause before each new generation request.')
    args=parser.parse_args()
    args.output.mkdir(parents=True,exist_ok=True)
    dump(args.output/'environment.json',{'python':platform.python_version(),'platform':platform.platform(),
         'processor':platform.processor(),'packages':{name:importlib.metadata.version(name) for name in ('torch','openai-whisper','langchain','langchain-google-genai','Flask')},
         'code_hashes':{str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in [ROOT/'mumu/chat.py',ROOT/'mumu/memory.py',ROOT/'mumu/voice.py',ROOT/'mumu/turns.py']},
         'legacy_hashes':{str(p.relative_to(args.legacy)):hashlib.sha256(p.read_bytes()).hexdigest() for p in [args.legacy/'pages/chat.py',args.legacy/'SYSTEMPROMPT.txt']}})
    if args.stage=='llm':
        llm(args)
    else:
        rag(args)


if __name__=='__main__':
    main()
