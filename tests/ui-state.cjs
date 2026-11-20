const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");

function element() {
  const classes = new Set();
  return {
    children: [], textContent: "", hidden: false, dataset: {}, handlers: {}, open: false,
    classList: {
      add: value => classes.add(value),
      remove: value => classes.delete(value),
      contains: value => classes.has(value),
      toggle() {},
    },
    get firstElementChild() { return this.children[0]; },
    get lastElementChild() { return this.children.at(-1); },
    append(...items) { this.children.push(...items); },
    replaceChildren(...items) { this.children = items; },
    setAttribute() {}, removeAttribute() {},
    addEventListener(name, callback) { this.handlers[name] = callback; },
    focus() { this.focused = true; },
    showModal() { this.open = true; },
    close() { this.open = false; },
  };
}

const nodes = new Map();
const document = {
  querySelector(selector) {
    if (!nodes.has(selector)) nodes.set(selector, element());
    return nodes.get(selector);
  },
  createElement: element,
};
document.querySelector("#chat").hidden = true;
document.querySelector("#status").parentElement = element();
const timers = new Map();
let timerId = 0;
let fetchCount = 0;
const context = vm.createContext({
  document,
  window: {
    addEventListener() {},
    setTimeout(callback) { timers.set(++timerId, callback); return timerId; },
    clearTimeout(id) { timers.delete(id); },
  },
  fetch: async () => {
    fetchCount += 1;
    return {
      ok: true, headers: { get: () => "application/json" },
      json: async () => ({
        messages: [], busy: false, replying: false, partial_reply: "", error: "",
        status: "ready", ended: false, voice: false,
      }),
    };
  },
});
vm.runInContext(fs.readFileSync("mumu/static/mumu.js", "utf8"), context);
const run = code => vm.runInContext(code, context);

async function main() {
  await new Promise(resolve => setImmediate(resolve));
  timers.clear();
  run("chat.hidden = false; state = {replying:true,partial_reply:'오늘은 친구',voice:false}; renderReplyPreview();");
  const preview = nodes.get("#reply-preview").firstElementChild.lastElementChild;
  run("window.clearTimeout(typingTimer); typeNextWord();");
  assert.equal(preview.textContent, "오늘은 ");
  assert.equal(run("typingTimer"), null, "wait without repeatedly scheduling empty typing ticks");
  run("state.partial_reply = '오늘은 친구랑 놀자!'; renderReplyPreview();");
  run("window.clearTimeout(typingTimer); typeNextWord();");
  assert.equal(preview.textContent, "오늘은 친구랑 ");
  run("state = {replying:false,partial_reply:'',voice:false}; renderMessages([{role:'human',text:'안녕'},{role:'ai',text:'오늘은 친구랑 놀자!'}]); renderReplyPreview(); updateControls();");
  const final = nodes.get("#messages").lastElementChild.lastElementChild;
  assert.equal(final.textContent, "오늘은 친구랑 ");
  assert.ok(nodes.get("#send").disabled);
  run("window.clearTimeout(typingTimer); typeNextWord();");
  assert.equal(final.textContent, "오늘은 친구랑 놀자!");
  assert.equal(nodes.get("#send").disabled, false);
  assert.ok(nodes.get("#message").focused);
  assert.equal(run("typingBubbles.size"), 0);

  run("clearTyping(); messages.replaceChildren(); renderMessages([{role:'ai',text:'past reply'}], false);");
  assert.equal(nodes.get("#messages").firstElementChild.lastElementChild.textContent, "past reply");
  assert.equal(run("typingBubbles.size"), 0, "restored history should not animate again");

  run("chat.hidden = true; state = {busy:true,replying:true,voice:false};");
  await run("refresh()");
  assert.equal(fetchCount, 1, "finish pending response after returning home");
  await run("refresh()");
  assert.equal(fetchCount, 1, "idle home should not request chat state");

  run("chat.hidden = false; state = {ended:true,memory_state:'saving',voice:false}; updateControls();");
  assert.ok(nodes.get("#loading-dialog").open);
  run("state.memory_state = 'saved'; updateControls();");
  assert.equal(nodes.get("#loading-dialog").open, false);
  assert.ok(nodes.get("#chat").hidden);

  let submitted = 0;
  nodes.get("#composer").requestSubmit = () => submitted++;
  nodes.get("#send").disabled = false;
  const keydown = nodes.get("#message").handlers.keydown;
  const event = {key:"Enter", shiftKey:false, isComposing:false, preventDefault() {}};
  keydown({...event, shiftKey:true});
  keydown({...event, isComposing:true});
  assert.equal(submitted, 0);
  keydown(event);
  assert.equal(submitted, 1);
  console.log("PASS: typing timer, word boundaries, restored history, focus, home polling, modal lifecycle and Enter shortcuts");
}
main().catch(error => { console.error(error); process.exitCode = 1; });
