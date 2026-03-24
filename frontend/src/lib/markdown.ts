/**
 * Minimal Markdown-to-HTML renderer for chat messages.
 *
 * Supports: code fences, tables, headers, bold, italic,
 * strikethrough, inline code, links, blockquotes, lists.
 * No external dependencies.
 */

const ESC: Record<string, string> = {
  "&": "&amp;",
  "<": "&lt;",
  ">": "&gt;",
  '"': "&quot;",
};

function esc(s: string): string {
  return s.replace(/[&<>"]/g, (ch) => ESC[ch] ?? ch);
}

// ---------- block-level ----------

function renderTable(rows: string[]): string {
  const parsed: string[][] = [];
  for (const row of rows) {
    if (/^\|[\s:]*-{2,}/.test(row)) continue; // skip separator
    const cells = row
      .trim()
      .replace(/^\|/, "")
      .replace(/\|$/, "")
      .split("|")
      .map((c) => c.trim());
    parsed.push(cells);
  }
  if (parsed.length === 0) return "";

  const [header, ...body] = parsed;
  const ths = header.map((c) => `<th>${inlineFormat(esc(c))}</th>`).join("");
  const bodyRows = body
    .map((r) => {
      const tds = r.map((c) => `<td>${inlineFormat(esc(c))}</td>`).join("");
      return `<tr>${tds}</tr>`;
    })
    .join("\n");
  return `<table class="md-table"><thead><tr>${ths}</tr></thead><tbody>${bodyRows}</tbody></table>`;
}

function renderCodeBlock(lang: string, lines: string[]): string {
  const code = esc(lines.join("\n"));
  if (lang) {
    return `<pre><code class="language-${esc(lang)}">${code}</code></pre>`;
  }
  return `<pre><code>${code}</code></pre>`;
}

// ---------- inline ----------

function inlineFormat(text: string): string {
  // inline code (protect first)
  const codeSpans: string[] = [];
  text = text.replace(/`([^`]+)`/g, (_, code) => {
    const idx = codeSpans.length;
    codeSpans.push(`<code>${code}</code>`);
    return `\x00C${idx}\x00`;
  });

  // bold
  text = text.replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>");
  // strikethrough
  text = text.replace(/~~(.+?)~~/g, "<s>$1</s>");
  // italic *text* (not **)
  text = text.replace(/(?<!\*)\*([^*]+?)\*(?!\*)/g, "<em>$1</em>");
  // italic _text_
  text = text.replace(/(?<!\w)_([^_]+?)_(?!\w)/g, "<em>$1</em>");
  // links
  text = text.replace(
    /\[([^\]]+)\]\(([^)]+)\)/g,
    '<a href="$2" target="_blank" rel="noopener">$1</a>',
  );

  // restore code spans
  for (let i = 0; i < codeSpans.length; i++) {
    text = text.replace(`\x00C${i}\x00`, codeSpans[i]);
  }
  return text;
}

// ---------- main ----------

export function renderMarkdown(md: string): string {
  const lines = md.split("\n");
  const out: string[] = [];

  let inCode = false;
  let codeLang = "";
  let codeLines: string[] = [];
  let tableRows: string[] = [];
  let bqLines: string[] = [];

  const flushTable = () => {
    if (tableRows.length > 0) {
      out.push(renderTable(tableRows));
      tableRows = [];
    }
  };

  const flushBlockquote = () => {
    if (bqLines.length > 0) {
      const inner = bqLines.map((l) => inlineFormat(esc(l))).join("<br>");
      out.push(`<blockquote>${inner}</blockquote>`);
      bqLines = [];
    }
  };

  for (const line of lines) {
    // Code fence
    if (!inCode && /^```(\w*)/.test(line)) {
      flushTable();
      flushBlockquote();
      inCode = true;
      codeLang = line.replace(/^```/, "").trim();
      codeLines = [];
      continue;
    }
    if (inCode) {
      if (/^```\s*$/.test(line)) {
        out.push(renderCodeBlock(codeLang, codeLines));
        inCode = false;
        codeLang = "";
        codeLines = [];
      } else {
        codeLines.push(line);
      }
      continue;
    }

    // Table row
    if (/^\|.+/.test(line)) {
      flushBlockquote();
      tableRows.push(line);
      continue;
    }
    flushTable();

    // Blockquote
    const bqMatch = line.match(/^>\s?(.*)/);
    if (bqMatch) {
      bqLines.push(bqMatch[1]);
      continue;
    }
    flushBlockquote();

    // Header
    const hMatch = line.match(/^(#{1,6})\s+(.*)/);
    if (hMatch) {
      const level = hMatch[1].length;
      out.push(`<h${level}>${inlineFormat(esc(hMatch[2]))}</h${level}>`);
      continue;
    }

    // Horizontal rule
    if (/^(-{3,}|\*{3,}|_{3,})\s*$/.test(line)) {
      out.push("<hr>");
      continue;
    }

    // Unordered list item
    if (/^[-*]\s+/.test(line)) {
      const content = line.replace(/^[-*]\s+/, "");
      out.push(`<li>${inlineFormat(esc(content))}</li>`);
      continue;
    }

    // Ordered list item
    if (/^\d+\.\s+/.test(line)) {
      const content = line.replace(/^\d+\.\s+/, "");
      out.push(`<li>${inlineFormat(esc(content))}</li>`);
      continue;
    }

    // Empty line — just a spacer, avoid stacking <br>s
    if (line.trim() === "") {
      // Only add spacing if last output wasn't already a spacer
      if (out.length > 0 && out[out.length - 1] !== '<div class="md-spacer"></div>') {
        out.push('<div class="md-spacer"></div>');
      }
      continue;
    }

    // Regular text line (no <p> wrapper to avoid excessive margins)
    out.push(`<div>${inlineFormat(esc(line))}</div>`);
  }

  // Flush remaining
  flushTable();
  flushBlockquote();
  if (inCode) {
    out.push(renderCodeBlock(codeLang, codeLines));
  }

  return out.join("\n");
}
