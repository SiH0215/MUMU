from concurrent.futures import Future
from contextlib import closing
from dataclasses import dataclass, field
from functools import partial
from secrets import token_hex
from threading import Event, Lock, Thread
from time import monotonic

from flask import Flask, jsonify, make_response, render_template, request, session

from main import DEFAULT_WHISPER_MODEL, ROOT, Conversation, load_chat, reply_error
from memory import DIARY_VERSION, ConversationMemory, is_farewell, write_diary_summary

MIC_LEASE_SECONDS = 30
PREPARING = "무무를 준비중이에요..."
INITIAL_STATUS = "메시지를 쓰거나 마이크를 켜서 이야기해요."
VOICE_SETUP_ERROR = "음성 모델을 준비하지 못했어요. 마이크 켜기를 눌러 다시 시도해 주세요."
VOICE_DEPENDENCY_ERROR = "음성 모드를 사용하려면 requirements-voice.txt를 설치해 주세요."


@dataclass
class BrowserChat:
    owner: str
    memory_id: str = field(default_factory=lambda: token_hex(16))
    lock: Lock = field(default_factory=Lock)
    messages: list = field(default_factory=list)
    conversation: Conversation | None = None
    stop: Event | None = None
    busy: bool = False
    replying: bool = False
    partial_reply: str = ""
    last_seen: float = 0.0
    status: str = INITIAL_STATUS
    error: str = ""
    ended: bool = False
    memory_state: str = ""


def prepare_microphone(model_name):
    from voice import load_voice_models, voice_input

    return partial(voice_input, 800, model_name, models=load_voice_models(model_name))


def create_app(chat_loader=load_chat, voice_source=None, *, voice_loader=prepare_microphone,
               memory_path=ROOT / "memory_DB" / "mumu.sqlite3", embedder=None):
    memory = ConversationMemory(memory_path, embedder)
    app = Flask(__name__)
    app.config.update(
        SECRET_KEY=memory.session_secret,
        SESSION_COOKIE_SAMESITE="Strict",
        TRUSTED_HOSTS=["127.0.0.1", "localhost"],
        MAX_CONTENT_LENGTH=16_384,
        TEMPLATES_AUTO_RELOAD=True,
        SEND_FILE_MAX_AGE_DEFAULT=0,
    )
    chats = {}
    chats_lock = Lock()
    mic_lock = Lock()
    setup_lock = Lock()
    chat_setup_lock = Lock()
    summary_lock = Lock()
    voice_setup = None
    chat_setup = None

    def get_chat_setup():
        nonlocal chat_setup
        with chat_setup_lock:
            if chat_setup is None:
                chat_setup = chat_loader()
            return chat_setup

    def load_voice(task):
        try:
            if voice_source is None:
                source = voice_loader(DEFAULT_WHISPER_MODEL)
            else:
                source = partial(voice_source, DEFAULT_WHISPER_MODEL)
            task.set_result(source)
        except Exception as error:
            app.logger.warning("Voice preparation failed: %s", error)
            task.set_exception(error)

    def prepare_voice():
        nonlocal voice_setup
        with setup_lock:
            if voice_setup is None or (voice_setup.done() and voice_setup.exception() is not None):
                voice_setup = Future()
                try:
                    Thread(target=load_voice, args=(voice_setup,), daemon=True).start()
                except RuntimeError as error:
                    voice_setup.set_exception(error)
            return voice_setup

    def current_chat():
        key = session.get("chat_id")
        with chats_lock:
            if key not in chats:
                key = token_hex(16)
                session["chat_id"] = key
                owner = session.get("memory_owner")
                if owner is None:
                    owner = session["memory_owner"] = token_hex(16)
                session.permanent = True
                chats[key] = BrowserChat(owner)
            return chats[key]

    def write_memory(chat, messages):
        try:
            memory.save(chat.owner, chat.memory_id, messages)
        except Exception as error:
            app.logger.warning("Conversation memory save failed (%s)", type(error).__name__)
            with chat.lock:
                chat.memory_state = "failed"
                chat.status = "대화를 마쳤어요."
                chat.error = "대화 기록을 저장하지 못했어요. 다시 저장해 주세요."
            return

        try:
            turns = [
                {"화자": "사용자" if item["role"] == "human" else "무무", "내용": item["text"]}
                for item in messages
            ]
            summary = write_diary_summary(get_chat_setup()[0], {"대화": turns})
            memory.save_diary(chat.owner, chat.memory_id, "transcript", summary)
        except (Exception, SystemExit) as error:
            app.logger.warning("Diary save failed (%s)", type(error).__name__)
            with chat.lock:
                chat.memory_state = "failed"
                chat.status = "대화를 마쳤어요."
                chat.error = "일기를 저장하지 못했어요. 다시 저장해 주세요."
            return

        with chat.lock:
            chat.memory_state = "saved"
            chat.status = "대화 기록을 저장했어요."
            chat.conversation = None

    def finish_chat(chat):
        # Called with chat.lock held, so no turn can enter the snapshot midway.
        chat.ended = True
        if chat.stop is not None:
            chat.stop.set()
        if chat.memory_state in {"saving", "saved"}:
            return
        if not any(item["role"] == "human" and not is_farewell(item["text"]) for item in chat.messages):
            chat.status = "대화를 마쳤어요."
            return

        chat.error = ""
        chat.memory_state = "saving"
        chat.status = "무무가 대화를 정리하고 있어요..."
        try:
            Thread(target=write_memory, args=(chat, chat.messages.copy()), daemon=True).start()
        except RuntimeError:
            chat.memory_state = "failed"
            chat.status = "대화를 마쳤어요."
            chat.error = "대화 기록을 저장하지 못했어요. 다시 저장해 주세요."

    def reply(chat, text):
        with chat.lock:
            chat.messages.append({"role": "human", "text": text})
            if is_farewell(text):
                chat.messages.append({"role": "ai", "text": "다음에 또 이야기하자. 잘 가!"})
                finish_chat(chat)
                return
            chat.status = "무무가 답변을 준비하고 있어요..."
            chat.error = ""
            chat.replying = True
            chat.partial_reply = ""

        def append_chunk(text):
            with chat.lock:
                chat.partial_reply += text

        try:
            if chat.conversation is None:
                chat.conversation = Conversation(*get_chat_setup())
            try:
                memories = memory.search(chat.owner, text)
            except Exception as error:
                app.logger.warning("Conversation memory search failed (%s)", type(error).__name__)
                memories = []
            answer = chat.conversation.reply(text, memories=memories, on_chunk=append_chunk)
        except (Exception, SystemExit) as error:
            with chat.lock:
                chat.error = str(error) if isinstance(error, SystemExit) else reply_error(error)
        else:
            with chat.lock:
                chat.messages.append({"role": "ai", "text": answer})
        finally:
            with chat.lock:
                chat.replying = False
                chat.partial_reply = ""
                if chat.stop is None:
                    chat.status = "이어서 이야기해요."

    def listen(chat, stop, setup):
        def expired():
            with chat.lock:
                return stop.is_set() or monotonic() - chat.last_seen > MIC_LEASE_SECONDS

        def status(message):
            with chat.lock:
                if not stop.is_set():
                    chat.status = message

        try:
            while not setup.done() and not expired():
                stop.wait(0.2)
            if expired():
                return
            source = setup.result()
            with closing(source(status=status, should_stop=expired)) as messages:
                for text in messages:
                    if expired():
                        break
                    with chat.lock:
                        if stop.is_set() or chat.ended:
                            break
                        chat.busy = True
                    try:
                        reply(chat, text)
                    finally:
                        with chat.lock:
                            chat.busy = False
        except ImportError:
            with chat.lock:
                chat.error = VOICE_DEPENDENCY_ERROR
        except Exception as error:
            app.logger.warning("Microphone session failed: %s", error)
            with chat.lock:
                chat.error = "음성 입력을 시작할 수 없어요. 기본 마이크와 Whisper 설정을 확인해 주세요."
        finally:
            with chat.lock:
                chat.stop = None
                if not chat.ended:
                    chat.status = "마이크가 꺼져 있어요."
                mic_lock.release()

    @app.before_request
    def check_json():
        if request.method == "POST" and not request.is_json:
            return jsonify(error="JSON 요청이 필요해요."), 415

    @app.get("/")
    def index():
        current_chat()
        asset_version = max(
            (ROOT / path).stat().st_mtime_ns
            for path in ("static/mumu.js", "static/mumu.css", "templates/index.html")
        )
        response = make_response(render_template("index.html", asset_version=asset_version))
        response.headers["Cache-Control"] = "no-store"
        return response

    @app.get("/api/chat/memories")
    def saved_memories():
        response = jsonify(memories=memory.list_records(current_chat().owner))
        response.headers["Cache-Control"] = "no-store"
        return response

    @app.get("/api/chat/memories/transcript/<record_id>")
    def saved_transcript(record_id):
        messages = memory.read_transcript(current_chat().owner, record_id)
        if messages is None:
            return jsonify(error="대화 전문을 찾을 수 없어요."), 404
        response = jsonify(messages=messages)
        response.headers["Cache-Control"] = "no-store"
        return response

    @app.post("/api/chat/memories/<kind>/<record_id>/summary")
    def open_diary(kind, record_id):
        chat = current_chat()
        diary = memory.read_diary(chat.owner, record_id, kind)
        if diary is None or diary[1] < DIARY_VERSION:
            with summary_lock:
                # Another request may have completed this diary while we waited.
                diary = memory.read_diary(chat.owner, record_id, kind)
                if diary is None or diary[1] < DIARY_VERSION:
                    legacy_summary = memory.legacy_summary(chat.owner, record_id, kind)
                    if legacy_summary is not None:
                        source = {"보존된 대화 요약": legacy_summary}
                    elif diary is not None:
                        source = {"이전 일기 초안": diary[0]}
                    else:
                        return jsonify(error="대화 기록을 찾을 수 없어요."), 404
                    try:
                        summary = write_diary_summary(get_chat_setup()[0], source)
                        memory.save_diary(chat.owner, record_id, kind, summary)
                        diary = (summary, DIARY_VERSION)
                    except (Exception, SystemExit) as error:
                        app.logger.warning("Record summary failed (%s)", type(error).__name__)
                        return jsonify(error="요약을 만들지 못했어요. 다시 시도해 주세요."), 502
        response = jsonify(summary=diary[0])
        response.headers["Cache-Control"] = "no-store"
        return response

    @app.get("/api/chat")
    def state():
        chat = current_chat()
        with setup_lock:
            setup = voice_setup
        preparing = setup is not None and not setup.done()
        setup_error = setup.exception() if setup is not None and not preparing else None
        voice_ready = setup is not None and not preparing and setup_error is None
        preparation_error = ""
        if setup_error is not None:
            preparation_error = VOICE_DEPENDENCY_ERROR if isinstance(setup_error, ImportError) else VOICE_SETUP_ERROR
        with chat.lock:
            chat.last_seen = monotonic()
            stopping = chat.stop is not None and chat.stop.is_set()
            state_data = dict(messages=chat.messages.copy(),
                              status=PREPARING if preparing and not stopping and not chat.ended else chat.status,
                              error=chat.error or (preparation_error if not chat.ended else ""),
                              voice=chat.stop is not None, stopping=stopping, preparing=preparing,
                              voice_ready=voice_ready,
                              busy=chat.busy, ended=chat.ended, memory_state=chat.memory_state,
                              replying=chat.replying, partial_reply=chat.partial_reply,
                              whisper_model=DEFAULT_WHISPER_MODEL)
        response = jsonify(state_data)
        response.headers["Cache-Control"] = "no-store"
        return response

    @app.post("/api/chat")
    def send_text():
        payload = request.get_json(silent=True)
        text = payload.get("text") if isinstance(payload, dict) else None
        if not isinstance(text, str) or not text.strip() or len(text.strip()) > 1000:
            return jsonify(error="메시지를 1~1,000자로 입력해 주세요."), 400
        chat = current_chat()
        with chat.lock:
            if chat.ended:
                return jsonify(error="새 이야기를 시작해 주세요."), 409
            if chat.busy or chat.stop is not None:
                return jsonify(error="마이크를 끄거나 답변이 끝난 뒤에 메시지를 보내 주세요."), 409
            chat.busy = True
        try:
            reply(chat, text.strip())
        finally:
            with chat.lock:
                chat.busy = False
        return jsonify(ok=True, ended=chat.ended)

    @app.post("/api/chat/end")
    def end_chat():
        chat = current_chat()
        with chat.lock:
            if chat.busy:
                return jsonify(error="무무의 답변이 끝난 뒤에 대화를 마쳐 주세요."), 409
            finish_chat(chat)
            return jsonify(ok=True, memory_state=chat.memory_state)

    @app.post("/api/chat/new")
    def new_chat():
        chat = current_chat()
        with chat.lock:
            if not chat.ended or chat.busy or chat.stop is not None or chat.memory_state == "saving":
                return jsonify(error="대화가 마무리될 때까지 잠시 기다려 주세요."), 409
            chat.messages.clear()
            chat.conversation = None
            chat.ended = False
            chat.memory_state = ""
            chat.memory_id = token_hex(16)
            chat.status = INITIAL_STATUS
            chat.error = ""
        return jsonify(ok=True)

    @app.post("/api/microphone/prepare")
    def warm_voice():
        prepare_voice()
        return jsonify(ok=True), 202

    @app.post("/api/microphone/start")
    def start_voice():
        if not isinstance(request.get_json(silent=True), dict):
            return jsonify(error="마이크 요청을 확인해 주세요."), 400
        chat = current_chat()
        with chat.lock:
            if chat.ended:
                return jsonify(error="새 이야기를 시작해 주세요."), 409
            if chat.busy or chat.stop is not None or not mic_lock.acquire(blocking=False):
                return jsonify(error="이미 처리 중인 대화가 있어요."), 409
            stop = chat.stop = Event()
            chat.last_seen = monotonic()
            chat.error = ""
            chat.status = "마이크를 준비하고 있어요..."
            try:
                setup = prepare_voice()
                Thread(target=listen, args=(chat, stop, setup), daemon=True).start()
            except RuntimeError:
                chat.stop = None
                mic_lock.release()
                chat.status = "마이크가 꺼져 있어요."
                return jsonify(error="마이크를 시작할 수 없어요."), 503
        return jsonify(ok=True), 202

    @app.post("/api/microphone/stop")
    def stop_voice():
        chat = current_chat()
        with chat.lock:
            if chat.stop is not None and not chat.ended:
                chat.stop.set()
                chat.status = "마이크를 끄고 있어요..."
        return jsonify(ok=True)

    return app


if __name__ == "__main__":
    create_app().run(host="127.0.0.1", port=5000)
