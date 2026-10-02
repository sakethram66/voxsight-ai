import test from "node:test";
import assert from "node:assert/strict";
import { SentenceChunker, cleanForSpeech, stripWake } from "./speech.js";

test("splits streamed deltas into sentences, waits for boundaries", () => {
  const c = new SentenceChunker();
  assert.deepEqual(c.push("The error is a Zero"), []);
  assert.deepEqual(c.push("DivisionError. Fix it by"), ["The error is a ZeroDivisionError."]);
  assert.deepEqual(c.push(" checking len. "), ["Fix it by checking len."]);
  assert.deepEqual(c.flush(), []);
});
test("does not split decimals or list numbers", () => {
  const c = new SentenceChunker();
  assert.deepEqual(c.push("Pi is 3.14 roughly. "), ["Pi is 3.14 roughly."]);
  assert.deepEqual(c.push("1. Open the file\n"), ["1. Open the file"]);
});
test("splits Telugu and Hindi danda sentence boundaries", () => {
  const c = new SentenceChunker();
  assert.deepEqual(c.push("నమస్కారం। "), ["నమస్కారం।"]);
  assert.deepEqual(c.push("नमस्ते। "), ["नमस्ते।"]);
});
test("code blocks are skipped, even when split across deltas", () => {
  const c = new SentenceChunker();
  let out = [...c.push("Try this. ```py\nprint(1"), ...c.push(")\n``` Then rerun it.")];
  out.push(...c.flush());
  assert.deepEqual(out, ["Try this.", "The code is shown on screen.", "Then rerun it."]);
});
test("unclosed code block is never spoken on flush", () => {
  const c = new SentenceChunker();
  c.push("Here you go ```js\nlet x");
  assert.deepEqual(c.flush(), ["Here you go"]);
});
test("cleanForSpeech strips markdown", () => {
  assert.equal(cleanForSpeech("## **Do** `this` [link](http://x)"), "Do this link");
});
test("wake phrase", () => {
  assert.equal(stripWake("Hey VoxSight, look at this"), "look at this");
  assert.equal(stripWake("vox sight what's wrong"), "what's wrong");
  assert.equal(stripWake("Hey Vox Sight"), "");
  assert.equal(stripWake("explain this"), "explain this");
});
