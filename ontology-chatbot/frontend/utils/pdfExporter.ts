import { jsPDF } from 'jspdf';
import type { Message } from '@/types/chat';

/* ═══════════════════════════════════════════════════════════
   PDF Export Utility — Structured markdown-aware renderer
   ═══════════════════════════════════════════════════════════ */

type RGB = [number, number, number];

const COLORS = {
  brand:      [255, 214, 0]   as RGB,
  dark:       [26, 28, 27]    as RGB,
  muted:      [120, 120, 120] as RGB,
  userLabel:  [37, 99, 235]   as RGB,
  asstLabel:  [16, 150, 110]  as RGB,
  userBg:     [235, 245, 255] as RGB,
  userBorder: [59, 130, 246]  as RGB,
  asstBg:     [245, 247, 249] as RGB,
  asstBorder: [180, 190, 200] as RGB,
  tableBg:    [250, 250, 250] as RGB,
  tableHead:  [235, 238, 242] as RGB,
  tableBorder:[200, 205, 210] as RGB,
  sqlBg:      [40, 44, 52]    as RGB,
  sqlText:    [171, 178, 191] as RGB,
  white:      [255, 255, 255] as RGB,
};

const MARGIN = 16;
const LINE_H = 4.8;

interface PdfContext {
  pdf: jsPDF;
  y: number;
  pageW: number;
  pageH: number;
  contentW: number;
}

/* ── Ensure page break ────────────────────────────────────── */
function ensureSpace(ctx: PdfContext, needed: number) {
  if (ctx.y + needed > ctx.pageH - MARGIN - 8) {
    ctx.pdf.addPage();
    ctx.y = MARGIN;
  }
}

/* ── Render a markdown table ──────────────────────────────── */
function renderTable(ctx: PdfContext, tableLines: string[]) {
  const rows = tableLines
    .filter(l => !l.match(/^\s*\|[\s\-:|]+\|\s*$/))           // skip separator row
    .map(l =>
      l.split('|').map(c => c.trim()).filter(Boolean)
    );

  if (rows.length === 0) return;

  const numCols = rows[0].length;
  const colW = (ctx.contentW - 6) / numCols;
  const cellPad = 3;
  const rowH = 7;
  const tableW = colW * numCols;
  const startX = MARGIN + 3;

  ensureSpace(ctx, rows.length * rowH + 6);

  rows.forEach((cells, ri) => {
    const isHeader = ri === 0;
    const rowY = ctx.y;

    // Row background
    ctx.pdf.setFillColor(...(isHeader ? COLORS.tableHead : (ri % 2 === 0 ? COLORS.white : COLORS.tableBg)));
    ctx.pdf.rect(startX, rowY, tableW, rowH, 'F');

    // Row border
    ctx.pdf.setDrawColor(...COLORS.tableBorder);
    ctx.pdf.setLineWidth(0.2);
    ctx.pdf.rect(startX, rowY, tableW, rowH, 'S');

    // Cell text
    cells.forEach((cell, ci) => {
      ctx.pdf.setFont('helvetica', isHeader ? 'bold' : 'normal');
      ctx.pdf.setFontSize(8.5);
      ctx.pdf.setTextColor(...COLORS.dark);
      const text = ctx.pdf.splitTextToSize(cell, colW - cellPad * 2)[0] || '';
      ctx.pdf.text(text, startX + ci * colW + cellPad, rowY + 4.8);
    });

    // Vertical cell dividers
    for (let ci = 1; ci < numCols; ci++) {
      ctx.pdf.line(startX + ci * colW, rowY, startX + ci * colW, rowY + rowH);
    }

    ctx.y += rowH;

    if (ctx.y > ctx.pageH - MARGIN - 8) {
      ctx.pdf.addPage();
      ctx.y = MARGIN;
    }
  });

  ctx.y += 3;
}

/* ── Render SQL code block ────────────────────────────────── */
function renderSqlBlock(ctx: PdfContext, sql: string) {
  const startX = MARGIN + 3;
  const blockW = ctx.contentW - 6;
  const pad = 5;

  ctx.pdf.setFont('courier', 'normal');
  ctx.pdf.setFontSize(8);
  const lines = ctx.pdf.splitTextToSize(sql, blockW - pad * 2);
  const blockH = lines.length * LINE_H + pad * 2 + 6;

  ensureSpace(ctx, blockH + 4);

  // "SQL Query" label
  ctx.pdf.setFont('helvetica', 'bold');
  ctx.pdf.setFontSize(8);
  ctx.pdf.setTextColor(100, 100, 100);
  ctx.pdf.text('SQL Query', startX, ctx.y + 4);
  ctx.y += 6;

  // Dark code background
  ctx.pdf.setFillColor(...COLORS.sqlBg);
  ctx.pdf.roundedRect(startX, ctx.y, blockW, lines.length * LINE_H + pad * 2, 2, 2, 'F');

  // Code text
  ctx.pdf.setFont('courier', 'normal');
  ctx.pdf.setFontSize(8);
  ctx.pdf.setTextColor(...COLORS.sqlText);
  let ty = ctx.y + pad + 3;
  for (const line of lines) {
    if (ty > ctx.pageH - MARGIN - 5) {
      ctx.pdf.addPage();
      ty = MARGIN + 5;
    }
    ctx.pdf.text(line, startX + pad, ty);
    ty += LINE_H;
  }

  ctx.y += lines.length * LINE_H + pad * 2 + 4;
}

/* ── Parse & render markdown-aware text ──────────────────── */
function renderMarkdown(ctx: PdfContext, text: string) {
  const rawLines = text.split('\n');
  const startX = MARGIN + 6;
  const textW = ctx.contentW - 12;

  let i = 0;
  while (i < rawLines.length) {
    const raw = rawLines[i];

    // ── Skip empty lines ──
    if (raw.trim() === '') {
      ctx.y += 2;
      i++;
      continue;
    }

    // ── Markdown table (collect consecutive | lines) ──
    if (raw.trim().startsWith('|') && raw.trim().endsWith('|')) {
      const tableLines: string[] = [];
      while (i < rawLines.length && rawLines[i].trim().startsWith('|') && rawLines[i].trim().endsWith('|')) {
        tableLines.push(rawLines[i]);
        i++;
      }
      renderTable(ctx, tableLines);
      continue;
    }

    // ── Headers (## or ###) ──
    const headerMatch = raw.match(/^(#{1,3})\s+(.+)/);
    if (headerMatch) {
      const level = headerMatch[1].length;
      const headerText = stripMd(headerMatch[2]);
      const fontSize = level === 1 ? 13 : level === 2 ? 11.5 : 10;
      ensureSpace(ctx, 10);
      ctx.y += level === 1 ? 4 : 2;
      ctx.pdf.setFont('helvetica', 'bold');
      ctx.pdf.setFontSize(fontSize);
      ctx.pdf.setTextColor(...COLORS.dark);
      ctx.pdf.text(headerText, startX, ctx.y);
      ctx.y += fontSize * 0.45 + 2;
      i++;
      continue;
    }

    // ── Bold-only line (**text**) ──
    const boldLineMatch = raw.match(/^\*\*(.+?)\*\*\s*$/);
    if (boldLineMatch) {
      const boldText = boldLineMatch[1];
      ensureSpace(ctx, 8);
      ctx.y += 1.5;
      ctx.pdf.setFont('helvetica', 'bold');
      ctx.pdf.setFontSize(10);
      ctx.pdf.setTextColor(...COLORS.dark);
      const wrapped = ctx.pdf.splitTextToSize(boldText, textW);
      for (const wl of wrapped) {
        ensureSpace(ctx, LINE_H + 1);
        ctx.pdf.text(wl, startX, ctx.y);
        ctx.y += LINE_H;
      }
      ctx.y += 1;
      i++;
      continue;
    }

    // ── Numbered list (1. / 2. etc) ──
    const numMatch = raw.match(/^(\s*)\d+\.\s+(.+)/);
    if (numMatch) {
      const indent = numMatch[1].length > 0 ? 6 : 0;
      const itemText = stripMd(numMatch[2]);
      const bullet = raw.match(/^(\s*)(\d+)\./);
      const num = bullet ? bullet[2] + '.' : '•';
      ensureSpace(ctx, LINE_H + 2);
      ctx.pdf.setFont('helvetica', 'bold');
      ctx.pdf.setFontSize(9.5);
      ctx.pdf.setTextColor(...COLORS.dark);
      ctx.pdf.text(num, startX + indent, ctx.y);
      ctx.pdf.setFont('helvetica', 'normal');
      const wrapped = ctx.pdf.splitTextToSize(itemText, textW - 8 - indent);
      for (const wl of wrapped) {
        ensureSpace(ctx, LINE_H + 1);
        ctx.pdf.text(wl, startX + 6 + indent, ctx.y);
        ctx.y += LINE_H;
      }
      ctx.y += 1;
      i++;
      continue;
    }

    // ── Bullet list (- or *) ──
    const bulletMatch = raw.match(/^(\s*)[-*]\s+(.+)/);
    if (bulletMatch) {
      const indent = bulletMatch[1].length > 0 ? 6 : 0;
      const itemText = stripMd(bulletMatch[2]);
      ensureSpace(ctx, LINE_H + 2);
      ctx.pdf.setFont('helvetica', 'normal');
      ctx.pdf.setFontSize(9.5);
      ctx.pdf.setTextColor(...COLORS.dark);
      ctx.pdf.text('•', startX + indent, ctx.y);
      const wrapped = ctx.pdf.splitTextToSize(itemText, textW - 8 - indent);
      for (const wl of wrapped) {
        ensureSpace(ctx, LINE_H + 1);
        ctx.pdf.text(wl, startX + 5 + indent, ctx.y);
        ctx.y += LINE_H;
      }
      ctx.y += 1;
      i++;
      continue;
    }

    // ── Regular paragraph line ──
    const cleanLine = stripMd(raw);
    if (cleanLine) {
      ctx.pdf.setFont('helvetica', 'normal');
      ctx.pdf.setFontSize(9.5);
      ctx.pdf.setTextColor(...COLORS.dark);
      const wrapped = ctx.pdf.splitTextToSize(cleanLine, textW);
      for (const wl of wrapped) {
        ensureSpace(ctx, LINE_H + 1);
        ctx.pdf.text(wl, startX, ctx.y);
        ctx.y += LINE_H;
      }
    }

    i++;
  }
}

/* ── Strip markdown formatting for clean text ─────────────── */
function stripMd(text: string): string {
  return text
    .replace(/\*\*(.+?)\*\*/g, '$1')   // **bold**
    .replace(/\*(.+?)\*/g, '$1')       // *italic*
    .replace(/__(.+?)__/g, '$1')       // __bold__
    .replace(/_(.+?)_/g, '$1')         // _italic_
    .replace(/`(.+?)`/g, '$1')         // `code`
    .replace(/\[(.+?)\]\(.*?\)/g, '$1') // [link](url)
    .trim();
}

/* ═══ Main Export Function ═══════════════════════════════════ */
export async function exportChatAsPdf(
  _sessionId: string,
  sessionTitle: string,
  sessionDate: string,
  msgs: Message[],
  displayName: string,
  includeSql: boolean,
) {
  if (!msgs.length) return;

  const pdf = new jsPDF('p', 'mm', 'a4');
  const pageW = pdf.internal.pageSize.getWidth();
  const pageH = pdf.internal.pageSize.getHeight();
  const contentW = pageW - MARGIN * 2;

  const ctx: PdfContext = { pdf, y: MARGIN, pageW: pageW, pageH: pageH, contentW };

  // ═══ HEADER BAR ═══
  pdf.setFillColor(...COLORS.brand);
  pdf.rect(0, 0, pageW, 26, 'F');

  // Title
  pdf.setFont('helvetica', 'bold');
  pdf.setFontSize(14);
  pdf.setTextColor(...COLORS.dark);
  const title = pdf.splitTextToSize(sessionTitle || 'Chat Export', pageW - MARGIN * 2 - 40)[0];
  pdf.text(title, MARGIN, 11);

  // Subtitle
  pdf.setFont('helvetica', 'normal');
  pdf.setFontSize(8.5);
  pdf.setTextColor(80, 80, 80);
  const dateStr = new Date(sessionDate).toLocaleDateString('en-US', {
    year: 'numeric', month: 'long', day: 'numeric',
  });
  pdf.text(`${dateStr}  •  ${msgs.length} messages`, MARGIN, 18);

  // Thin separator
  ctx.y = 30;
  pdf.setDrawColor(220, 220, 220);
  pdf.setLineWidth(0.3);
  pdf.line(MARGIN, ctx.y, pageW - MARGIN, ctx.y);
  ctx.y += 6;

  // ═══ MESSAGES ═══
  for (const msg of msgs) {
    const isUser = msg.role === 'user';
    const label = isUser ? (displayName || 'You') : 'NexusAI';
    const timestamp = new Date(msg.created_at).toLocaleTimeString([], {
      hour: '2-digit', minute: '2-digit',
    });

    // Pre-compute approximate height for the card background
    pdf.setFont('helvetica', 'normal');
    pdf.setFontSize(9.5);
    const preLines = pdf.splitTextToSize(stripMd(msg.content), contentW - 16);
    const estimatedH = Math.max(preLines.length * LINE_H + 22, 18);

    ensureSpace(ctx, Math.min(estimatedH, 60)); // ensure at least some space

    const cardStartY = ctx.y;

    // ── Role label + timestamp ──
    pdf.setFont('helvetica', 'bold');
    pdf.setFontSize(9);
    pdf.setTextColor(...(isUser ? COLORS.userLabel : COLORS.asstLabel));
    pdf.text(label, MARGIN + 5, ctx.y + 5);

    pdf.setFont('helvetica', 'normal');
    pdf.setFontSize(7.5);
    pdf.setTextColor(...COLORS.muted);
    pdf.text(timestamp, MARGIN + contentW - 5 - pdf.getTextWidth(timestamp), ctx.y + 5);

    ctx.y += 9;

    // ── Message body (markdown-aware) ──
    renderMarkdown(ctx, msg.content);
    ctx.y += 3;

    const cardEndY = ctx.y;

    // We draw accent bars for cards that don't span pages

    // We can only draw accents for cards that don't span pages
    if (cardEndY > cardStartY) {
      // Left accent bar
      pdf.setFillColor(...(isUser ? COLORS.userBorder : COLORS.asstBorder));
      pdf.rect(MARGIN, cardStartY, 2, Math.min(cardEndY - cardStartY, pageH - MARGIN - cardStartY), 'F');

      // Subtle bottom divider
      pdf.setDrawColor(235, 235, 235);
      pdf.setLineWidth(0.2);
      pdf.line(MARGIN + 4, cardEndY, MARGIN + contentW - 4, cardEndY);
    }

    ctx.y += 4;

    // ── Optional SQL block ──
    if (includeSql && msg.role === 'assistant' && msg.metadata_?.sql) {
      const sqlContent = Array.isArray(msg.metadata_.sql)
        ? (msg.metadata_.sql as string[]).join('\n\n')
        : String(msg.metadata_.sql);
      if (sqlContent.trim()) {
        renderSqlBlock(ctx, sqlContent);
      }
    }

    ctx.y += 2;
  }

  // ═══ FOOTER ═══
  const totalPages = pdf.getNumberOfPages();
  for (let p = 1; p <= totalPages; p++) {
    pdf.setPage(p);
    pdf.setFont('helvetica', 'italic');
    pdf.setFontSize(7);
    pdf.setTextColor(...COLORS.muted);
    pdf.text(
      `Generated by NexusAI  •  Page ${p} of ${totalPages}`,
      pageW / 2,
      pageH - 6,
      { align: 'center' }
    );
  }

  pdf.save(`Chat_Export_${new Date().toISOString().split('T')[0]}.pdf`);
}
