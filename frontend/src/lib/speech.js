// Pure helpers (unit-tested with `npm test`): make streamed markdown speakable, sentence by sentence.

export function cleanForSpeech(t) {
  return t
    .replace(/```[\s\S]*?```/g, " ")
    .replace(/`([^`]+)`/g, "$1")
    .replace(/!?\[([^\]]*)\]\([^)]*\)/g, "$1")
    .replace(/^#{1,6}\s*/gm, "")
    .replace(/(\*\*|__|\*|~~)/g, "")
    .replace(/^\s*[-•]\s+/gm, "")
    .replace(/\s+/g, " ")
    .trim();
}

function takeSentences(s) {
  const out = [], re = /[.!?।](?=\s)|\n/g;
  let start = 0, m;
  while ((m = re.exec(s))) {
    if (m[0] === "." && /^\s*\d+$/.test(s.slice(start, m.index))) continue; // "1." list numbering
    out.push(s.slice(start, m.index + 1));
    start = m.index + 1;
  }
  return [out, s.slice(start)];
}

/** Feed streamed text deltas; get back complete sentences ready for TTS. Code blocks are never read aloud. */
export class SentenceChunker {
  constructor() { this.buf = ""; }
  push(d) {
    this.buf += d;
    const out = [];
    for (;;) {
      const f = this.buf.indexOf("```");
      const head = f === -1 ? this.buf : this.buf.slice(0, f);
      const [sents, rest] = takeSentences(head);
      out.push(...sents);
      if (f === -1) { this.buf = rest; break; }
      const close = this.buf.indexOf("```", f + 3);
      if (close === -1) { this.buf = rest + this.buf.slice(f); break; } // wait for the fence to close
      if (rest.trim()) out.push(rest);
      out.push("The code is shown on screen.");
      this.buf = this.buf.slice(close + 3);
    }
    return out.map(cleanForSpeech).filter(Boolean);
  }
  flush() {
    let b = this.buf;
    this.buf = "";
    const f = b.indexOf("```");
    if (f !== -1) b = b.slice(0, f);
    const c = cleanForSpeech(b);
    return c ? [c] : [];
  }
  reset() { this.buf = ""; }
}

/** "Hey VoxSight, ..." -> "..." (returns "" when only the wake phrase was said). */
export function stripWake(t) {
  return t.replace(/^\s*(?:hey|hi|ok|okay)?[\s,]*vox\s?sight\b[\s,.:!-]*/i, "").trim();
}
