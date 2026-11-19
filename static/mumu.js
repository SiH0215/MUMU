const home = document.querySelector("#home");
const chat = document.querySelector("#chat");
const startButton = document.querySelector("#open-chat");
const composer = document.querySelector("#composer");
const message = document.querySelector("#message");
const sendButton = document.querySelector("#send");
const microphone = document.querySelector("#microphone");
const endButton = document.querySelector("#end-chat");
const retryMemory = document.querySelector("#retry-memory");
const micLabel = document.querySelector("#mic-label");
const micLight = document.querySelector("#mic-light");
const statusText = document.querySelector("#status");
const initialStatus = statusText.textContent;
const errorText = document.querySelector("#error");
const homeError = document.querySelector("#home-error");
const homeErrorText = document.querySelector("#home-error-text");
const loadingDialog = document.querySelector("#loading-dialog");
const loadingText = document.querySelector("#loading-text");
const conversation = document.querySelector("#conversation");
const welcome = document.querySelector("#welcome");
const messages = document.querySelector("#messages");
const replyPreview = document.querySelector("#reply-preview");
const openDiary = document.querySelector("#open-diary");
const memoryDialog = document.querySelector("#memory-dialog");
const memoryStatus = document.querySelector("#memory-status");
const memoryList = document.querySelector("#memory-list");
const memoryPages = document.querySelector(".memory-pages");
const memoryBack = document.querySelector("#memory-back");
const memoryEntry = document.querySelector("#memory-entry");
const memoryEntryDate = document.querySelector("#memory-entry-date");
const memoryContent = document.querySelector("#memory-content");
const memoryTranscript = document.querySelector("#memory-transcript");
const memoryView = document.querySelector("#memory-view");
const memoryRetry = document.querySelector("#memory-retry");
const memoryDate = new Intl.DateTimeFormat("ko-KR", {
  dateStyle: "medium", timeStyle: "short", timeZone: "Asia/Seoul",
});

let state = { voice: false, busy: false, stopping: false, preparing: false, voice_ready: false, ended: false };
let opening = false;
let ending = false;
let sending = false;
let switching = false;
let fetching = false;
let micRevision = 0;
let memoryRequest = 0;
let currentRecord = null;
let showingTranscript = false;
const typingBubbles = new Map();
const WORD_INTERVAL_MS = 70;
let typingTimer = null;
let focusAfterReply = false;

function queueTyping(bubble, text, complete, shown = "") {
  const previous = typingBubbles.get(bubble);
  typingBubbles.set(bubble, {
    text, complete, shown: previous ? previous.shown : shown,
  });
  if (typingTimer === null) typingTimer = window.setTimeout(typeNextWord, WORD_INTERVAL_MS);
}

function typeNextWord() {
  typingTimer = null;
  let moreWords = false;
  let changed = false;
  for (const [bubble, progress] of typingBubbles) {
    const available = progress.complete ? progress.text : (progress.text.match(/^[\s\S]*\s/u)?.[0] || "");
    const word = available.slice(progress.shown.length).match(/^\s*\S+\s*|^\s+$/u)?.[0];
    if (word) {
      progress.shown += word;
      bubble.textContent = progress.shown;
      bubble.classList.remove("skeleton-bubble");
      bubble.removeAttribute("aria-label");
      changed = true;
    }
    if (progress.complete && progress.shown === progress.text) {
      typingBubbles.delete(bubble);
      focusAfterReply = true;
    } else if (progress.shown.length < available.length) {
      moreWords = true;
    }
  }
  if (changed) conversation.scrollTop = conversation.scrollHeight;
  updateControls();
  if (moreWords) typingTimer = window.setTimeout(typeNextWord, WORD_INTERVAL_MS);
}

function clearTyping() {
  window.clearTimeout(typingTimer);
  typingTimer = null;
  typingBubbles.clear();
  focusAfterReply = false;
}

async function api(path, payload, keepalive = false) {
  const options = payload === undefined ? { cache: "no-store" } : {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
    keepalive,
  };
  const response = await fetch(path, options);
  if (!response.headers.get("Content-Type")?.includes("application/json")) {
    throw new Error("무무 서버에 연결할 수 없어요.");
  }
  const data = await response.json();
  if (!response.ok) throw new Error(data.error || "잠시 후 다시 시도해 주세요.");
  return data;
}

function showError(text) {
  errorText.hidden = !text;
  if (errorText.textContent !== text) errorText.textContent = text;
  homeError.hidden = !text;
  homeErrorText.textContent = text;
}

function goHome() {
  chat.hidden = true;
  home.hidden = false;
  startButton.focus();
}

function updateLoading() {
  const saving = ending || state.memory_state === "saving" || (state.ended && state.voice);
  const preparing = !chat.hidden && (opening || state.preparing);
  const text = saving ? "대화를 정리중이에요..." : preparing ? "무무를 준비중이에요..." : "";
  if (text) {
    if (loadingText.textContent !== text) loadingText.textContent = text;
    if (!loadingDialog.open) {
      loadingDialog.showModal();
      loadingText.focus();
    }
  } else if (loadingDialog.open) {
    loadingDialog.close();
  }
  statusText.parentElement.hidden = Boolean(text);
  if (state.ended && !saving && !opening && !sending && !typingBubbles.size && !chat.hidden) {
    goHome();
  }
}

loadingDialog.addEventListener("cancel", event => event.preventDefault());

function updateControls() {
  const preparing = state.preparing || (opening && !state.voice_ready);
  const closed = ending || state.ended;
  const typing = typingBubbles.size > 0;
  message.disabled = closed || preparing || state.voice || typing;
  sendButton.disabled = closed || preparing || sending || state.busy || state.voice || switching || typing;
  microphone.disabled = closed || preparing || sending || (state.busy && !state.voice) ||
    state.stopping || switching || (typing && !state.voice);
  endButton.disabled = state.ended || ending || opening || sending || switching || state.busy ||
    state.memory_state === "saving" || (state.ended && state.voice) || typing;
  retryMemory.hidden = state.memory_state !== "failed";
  retryMemory.disabled = ending || state.busy;
  microphone.setAttribute("aria-pressed", String(state.voice));
  micLight.classList.toggle("active", state.voice && state.voice_ready && !state.stopping &&
    Boolean(state.status?.startsWith("듣고 있어요.")));
  micLabel.textContent = state.stopping ? "마이크 끄는 중…" :
    state.voice ? "마이크 끄기" : "마이크 켜기";
  updateLoading();
  if (focusAfterReply && !typing && !state.busy && !state.replying && !sending) {
    focusAfterReply = false;
    if (!message.disabled && !chat.hidden && !memoryDialog.open) {
      message.focus({ preventScroll: true });
    }
  }
}

function createMessageRow(item) {
  const row = document.createElement("li");
  row.className = item.role === "human" ? "message human" : "message";
  const speaker = document.createElement("span");
  speaker.className = "speaker";
  speaker.textContent = item.role === "human" ? "나" : "무무";
  const bubble = document.createElement("p");
  bubble.className = "bubble";
  bubble.textContent = item.text;
  row.append(speaker, bubble);
  return row;
}

function renderMessages(items, animate = true) {
  if (items.length < messages.children.length) {
    clearTyping();
    messages.replaceChildren();
  }
  const previousCount = messages.children.length;
  for (const item of items.slice(previousCount)) {
    const row = createMessageRow(item);
    if (animate && item.role !== "human") {
      const previewBubble = replyPreview.firstElementChild?.lastElementChild;
      const shown = previewBubble && !previewBubble.classList.contains("skeleton-bubble")
        ? previewBubble.textContent : "";
      const bubble = row.lastElementChild;
      bubble.textContent = item.text.startsWith(shown) ? shown : "";
      queueTyping(bubble, item.text, true, bubble.textContent);
    }
    messages.append(row);
  }
  welcome.hidden = items.length > 0;
  if (items.length !== previousCount) conversation.scrollTop = conversation.scrollHeight;
}

function renderReplyPreview() {
  const visible = Boolean(state.replying);
  const text = state.partial_reply || "";
  const changed = replyPreview.hidden === visible || replyPreview.dataset.text !== text;
  replyPreview.hidden = !visible;
  if (!visible) {
    const bubble = replyPreview.firstElementChild?.lastElementChild;
    if (bubble) typingBubbles.delete(bubble);
    replyPreview.replaceChildren();
    delete replyPreview.dataset.text;
    return;
  }
  if (!changed) return;
  replyPreview.dataset.text = text;
  let row = replyPreview.firstElementChild;
  if (!row) {
    row = createMessageRow({ role: "ai", text: "" });
    const bubble = row.lastElementChild;
    bubble.classList.add("skeleton-bubble");
    bubble.setAttribute("aria-label", "무무가 답변을 준비하고 있어요");
    for (let index = 0; index < 3; index += 1) {
      const line = document.createElement("span");
      line.className = "skeleton-line";
      line.setAttribute("aria-hidden", "true");
      bubble.append(line);
    }
    replyPreview.replaceChildren(row);
  }
  if (text) queueTyping(row.lastElementChild, text, false);
  conversation.scrollTop = conversation.scrollHeight;
}

async function refresh() {
  if (fetching || opening || ending || switching ||
      (chat.hidden && state.memory_state !== "saving" && !state.voice && !state.busy && !state.replying)) return;
  fetching = true;
  const revision = micRevision;
  try {
    const nextState = await api("/api/chat");
    if (revision !== micRevision) return;
    state = nextState;
    renderMessages(state.messages);
    renderReplyPreview();
    if (statusText.textContent !== state.status) statusText.textContent = state.status;
    showError(state.error);
    updateControls();
  } catch {
    if (revision === micRevision) showError("무무 서버에 연결할 수 없어요.");
  } finally {
    fetching = false;
  }
}

function stopMic() {
  return api("/api/microphone/stop", {}, true);
}

async function showMemoryList() {
  const request = ++memoryRequest;
  currentRecord = null;
  memoryTranscript.replaceChildren();
  memoryBack.hidden = true;
  memoryEntry.hidden = true;
  memoryList.hidden = false;
  memoryList.replaceChildren();
  memoryPages.scrollTop = 0;
  memoryStatus.textContent = "기록을 불러오는 중이에요...";
  try {
    const { memories } = await api("/api/chat/memories");
    if (request !== memoryRequest) return;
    memoryStatus.textContent = memories.length ? "" : "아직 저장된 기록이 없어요.";
    const items = memories.map(record => {
      const row = document.createElement("li");
      const button = document.createElement("button");
      button.type = "button";
      button.className = "memory-card";
      const timestamp = document.createElement("time");
      timestamp.dateTime = record.date;
      timestamp.textContent = memoryDate.format(new Date(record.date));
      button.append(timestamp);
      button.addEventListener("click", () => openMemoryRecord(record));
      row.append(button);
      return row;
    });
    memoryList.replaceChildren(...items);
  } catch {
    if (request === memoryRequest) memoryStatus.textContent = "대화 기록을 불러오지 못했어요.";
  }
}

async function openMemoryRecord(record, showTranscript = false) {
  const request = ++memoryRequest;
  const path = `/api/chat/memories/${record.kind}/${encodeURIComponent(record.id)}`;
  if (currentRecord !== record) {
    memoryBack.hidden = false;
    memoryBack.focus();
  }
  currentRecord = record;
  showingTranscript = showTranscript;
  memoryList.hidden = true;
  memoryPages.scrollTop = 0;
  memoryEntryDate.dateTime = record.date;
  memoryEntryDate.textContent = memoryDate.format(new Date(record.date));
  memoryEntry.hidden = false;
  memoryContent.hidden = showTranscript;
  memoryContent.textContent = "";
  memoryTranscript.hidden = !showTranscript;
  memoryTranscript.replaceChildren();
  memoryView.hidden = record.kind !== "transcript";
  memoryView.textContent = showTranscript ? "일기 보기" : "대화 전문 보기";
  memoryRetry.hidden = true;
  if (!showTranscript && !record.has_diary) {
    memoryStatus.textContent = "";
    memoryContent.textContent = "이 대화에는 저장된 일기가 없어요.";
    return;
  }
  memoryStatus.textContent = showTranscript ? "대화를 불러오는 중이에요..." : "일기를 불러오는 중이에요...";
  try {
    const result = showTranscript ? await api(path) : await api(`${path}/summary`, {});
    if (request !== memoryRequest) return;
    if (showTranscript) {
      for (const item of result.messages) memoryTranscript.append(createMessageRow(item));
    } else {
      memoryContent.textContent = result.summary;
    }
    memoryStatus.textContent = "";
  } catch (error) {
    if (request !== memoryRequest) return;
    memoryStatus.textContent = error.message;
    memoryRetry.hidden = false;
  }
}

openDiary.addEventListener("click", () => {
  memoryDialog.showModal();
  showMemoryList();
});
memoryBack.addEventListener("click", showMemoryList);
memoryDialog.addEventListener("close", () => {
  memoryRequest += 1;
  memoryTranscript.replaceChildren();
});
memoryView.addEventListener("click", () => {
  if (currentRecord) openMemoryRecord(currentRecord, !showingTranscript);
});
memoryRetry.addEventListener("click", () => {
  if (currentRecord) openMemoryRecord(currentRecord, showingTranscript);
});

startButton.addEventListener("click", async () => {
  if (opening) return;
  opening = true;
  home.hidden = true;
  chat.hidden = false;
  document.querySelector("#chat-heading").focus();
  micRevision += 1;
  updateControls();
  try {
    state = await api("/api/chat");
    if (state.ended) {
      await api("/api/chat/new", {});
      state = { ...state, ended: false, memory_state: "", messages: [], error: "", status: initialStatus };
      clearTyping();
      replyPreview.replaceChildren();
      replyPreview.hidden = true;
      renderMessages([]);
      message.value = "";
    }
    renderMessages(state.messages, false);
    renderReplyPreview();
    showError(state.error);
    statusText.textContent = state.status;
    await api("/api/microphone/prepare", {});
    state.preparing = !state.voice_ready;
  } catch (error) {
    statusText.textContent = state.status || initialStatus;
    showError(error.message);
  } finally {
    opening = false;
    updateControls();
  }
  await refresh();
});

document.querySelector("#back").addEventListener("click", () => {
  if (state.voice || switching) stopMic().catch(() => {});
  goHome();
  updateControls();
});

window.addEventListener("pagehide", () => {
  if (state.voice || switching) stopMic().catch(() => {});
});

message.addEventListener("keydown", (event) => {
  if (event.key !== "Enter" || event.shiftKey || event.isComposing || event.keyCode === 229) return;
  event.preventDefault();
  if (!sendButton.disabled) composer.requestSubmit(sendButton);
});

composer.addEventListener("submit", async (event) => {
  event.preventDefault();
  const text = message.value.trim();
  if (!text || sendButton.disabled) return;
  sending = true;
  message.value = "";
  showError("");
  updateControls();
  try {
    const result = await api("/api/chat", { text });
    if (result.ended) state = await api("/api/chat");
  } catch (error) {
    if (!message.value) message.value = text;
    showError(error.message);
    return;
  } finally {
    sending = false;
    updateControls();
  }
  await refresh();
});

async function endConversation() {
  micRevision += 1;
  ending = true;
  updateControls();
  try {
    const result = await api("/api/chat/end", {});
    state.ended = true;
    state.memory_state = result.memory_state || "";
    showError("");
  } catch (error) {
    showError(error.message);
    return;
  } finally {
    ending = false;
    updateControls();
  }
  await refresh();
}

endButton.addEventListener("click", () => {
  if (!endButton.disabled) endConversation();
});

retryMemory.addEventListener("click", () => {
  if (!retryMemory.hidden && !retryMemory.disabled) endConversation();
});

microphone.addEventListener("click", async () => {
  if (microphone.disabled) return;
  micRevision += 1;
  switching = true;
  updateControls();
  try {
    if (state.voice) {
      await stopMic();
      state.stopping = true;
    } else {
      await api("/api/microphone/start", {});
      state.voice = true;
      if (chat.hidden) await stopMic();
    }
  } catch (error) {
    showError(error.message);
    return;
  } finally {
    switching = false;
    updateControls();
  }
  await refresh();
});

async function pollChat() {
  await refresh();
  window.setTimeout(pollChat, state.replying ? 120 : 550);
}
pollChat();
