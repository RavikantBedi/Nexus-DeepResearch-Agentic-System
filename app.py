import re
import io
import streamlit as st
import time
import os
import json

# ── PDF + Diagram generation ──────────────────────────────────────────────────
try:
    from fpdf import FPDF
    PDF_ENABLED = True
except ImportError:
    PDF_ENABLED = False

try:
    import matplotlib
    matplotlib.use("Agg")          # non-GUI backend — required for Streamlit
    import matplotlib.pyplot as plt
    import matplotlib.patches as mpatches
    from matplotlib.patches import FancyBboxPatch, FancyArrowPatch
    MATPLOTLIB_OK = True
except ImportError:
    MATPLOTLIB_OK = False


# ─────────────────────────────────────────────────────────────────────────────
#  Architecture Diagram Renderer
# ─────────────────────────────────────────────────────────────────────────────
def render_architecture_diagram(diagram_data: dict) -> bytes | None:
    """
    Renders a matplotlib architecture diagram from diagram_data JSON.
    Returns PNG bytes or None on failure.
    """
    if not MATPLOTLIB_OK or not diagram_data:
        return None

    try:
        nodes  = diagram_data.get("nodes", [])
        edges  = diagram_data.get("edges", [])
        title  = diagram_data.get("title", "System Architecture")
        subtitle = diagram_data.get("subtitle", "")

        n = len(nodes)
        if n == 0:
            return None

        # ── colour map per type ───────────────────────────────────────────
        TYPE_STYLE = {
            "input":    {"face": "#0f2942", "edge": "#38bdf8", "text": "#38bdf8"},
            "process":  {"face": "#0f1a2e", "edge": "#818cf8", "text": "#c4b5fd"},
            "decision": {"face": "#1a0f2e", "edge": "#a78bfa", "text": "#ddd6fe"},
            "output":   {"face": "#0a1f1a", "edge": "#34d399", "text": "#6ee7b7"},
            "storage":  {"face": "#1f1209", "edge": "#fb923c", "text": "#fdba74"},
        }
        DEFAULT_STYLE = {"face": "#111827", "edge": "#64748b", "text": "#94a3b8"}

        # ── layout: arrange nodes in a left-to-right flow ─────────────────
        cols = min(n, 4)
        rows = (n + cols - 1) // cols

        fig_w = max(14, cols * 3.5)
        fig_h = max(5,  rows * 3.0 + 2)

        fig, ax = plt.subplots(figsize=(fig_w, fig_h))
        fig.patch.set_facecolor("#050a14")
        ax.set_facecolor("#050a14")
        ax.set_xlim(0, fig_w)
        ax.set_ylim(0, fig_h)
        ax.axis("off")

        # ── title & subtitle ──────────────────────────────────────────────
        ax.text(fig_w / 2, fig_h - 0.45, title,
                ha="center", va="top",
                fontsize=14, fontweight="bold",
                color="#e2e8f0",
                fontfamily="DejaVu Sans")
        if subtitle:
            ax.text(fig_w / 2, fig_h - 0.90, subtitle,
                    ha="center", va="top",
                    fontsize=9, color="#94a3b8",
                    fontfamily="DejaVu Sans")

        # ── compute node centres ──────────────────────────────────────────
        BOX_W = 2.6
        BOX_H = 0.85
        H_GAP = (fig_w - cols * BOX_W) / (cols + 1)
        V_GAP = (fig_h - 1.4 - rows * BOX_H) / (rows + 1)

        centres = {}
        for idx, node in enumerate(nodes):
            col_i = idx % cols
            row_i = idx // cols
            cx = H_GAP * (col_i + 1) + BOX_W * col_i + BOX_W / 2
            cy = fig_h - 1.4 - V_GAP * (row_i + 1) - BOX_H * row_i - BOX_H / 2
            centres[node["id"]] = (cx, cy)

        # ── draw edges first (behind nodes) ──────────────────────────────
        id_set = {n["id"] for n in nodes}
        for edge in edges:
            src_id = edge.get("from", "")
            dst_id = edge.get("to", "")
            if src_id not in centres or dst_id not in centres:
                continue
            x1, y1 = centres[src_id]
            x2, y2 = centres[dst_id]

            # offset start/end to box boundary
            dx, dy = x2 - x1, y2 - y1
            length = (dx**2 + dy**2) ** 0.5 or 1
            ux, uy = dx / length, dy / length

            sx = x1 + ux * (BOX_W / 2 + 0.05)
            sy = y1 + uy * (BOX_H / 2 + 0.05)
            ex = x2 - ux * (BOX_W / 2 + 0.05)
            ey = y2 - uy * (BOX_H / 2 + 0.05)

            ax.annotate(
                "",
                xy=(ex, ey),
                xytext=(sx, sy),
                arrowprops=dict(
                    arrowstyle="-|>",
                    color="#38bdf8",
                    lw=1.4,
                    mutation_scale=14,
                    connectionstyle="arc3,rad=0.05"
                )
            )
            # edge label
            lbl = edge.get("label", "")
            if lbl:
                ax.text((sx + ex) / 2, (sy + ey) / 2 + 0.12,
                        lbl, ha="center", va="bottom",
                        fontsize=7, color="#64748b")

        # ── draw nodes ────────────────────────────────────────────────────
        for node in nodes:
            nid   = node["id"]
            label = node.get("label", nid)
            ntype = node.get("type", "process")
            style = TYPE_STYLE.get(ntype, DEFAULT_STYLE)
            cx, cy = centres[nid]

            # glow shadow
            for offset, alpha in [(0.06, 0.10), (0.04, 0.18), (0.02, 0.30)]:
                glow = FancyBboxPatch(
                    (cx - BOX_W / 2 - offset, cy - BOX_H / 2 - offset),
                    BOX_W + offset * 2, BOX_H + offset * 2,
                    boxstyle="round,pad=0.02",
                    linewidth=0,
                    facecolor=style["edge"],
                    alpha=alpha,
                    zorder=1
                )
                ax.add_patch(glow)

            # box fill
            box = FancyBboxPatch(
                (cx - BOX_W / 2, cy - BOX_H / 2),
                BOX_W, BOX_H,
                boxstyle="round,pad=0.02",
                linewidth=1.6,
                edgecolor=style["edge"],
                facecolor=style["face"],
                zorder=2
            )
            ax.add_patch(box)

            # label — wrap if long
            words = label.split()
            if len(words) > 3:
                mid = len(words) // 2
                label = " ".join(words[:mid]) + "\n" + " ".join(words[mid:])

            ax.text(cx, cy, label,
                    ha="center", va="center",
                    fontsize=9, fontweight="bold",
                    color=style["text"],
                    zorder=3,
                    fontfamily="DejaVu Sans",
                    multialignment="center")

        # ── legend ────────────────────────────────────────────────────────
        legend_items = []
        seen_types = list({n.get("type", "process") for n in nodes})
        for t in seen_types:
            s = TYPE_STYLE.get(t, DEFAULT_STYLE)
            legend_items.append(
                mpatches.Patch(facecolor=s["face"], edgecolor=s["edge"],
                               label=t.capitalize(), linewidth=1.2)
            )
        if legend_items:
            leg = ax.legend(handles=legend_items,
                            loc="lower right",
                            frameon=True,
                            framealpha=0.3,
                            facecolor="#0f172a",
                            edgecolor="#334155",
                            labelcolor="#94a3b8",
                            fontsize=7.5,
                            ncol=len(legend_items))

        plt.tight_layout(pad=0.3)

        buf = io.BytesIO()
        fig.savefig(buf, format="png", dpi=150,
                    facecolor="#050a14", bbox_inches="tight")
        plt.close(fig)
        buf.seek(0)
        return buf.read()

    except Exception as ex:
        st.warning(f"Diagram render error: {ex}")
        try:
            plt.close("all")
        except Exception:
            pass
        return None


# ─────────────────────────────────────────────────────────────────────────────
#  PDF Generator  (fpdf2)
# ─────────────────────────────────────────────────────────────────────────────
def safe_text(text: str) -> str:
    if not isinstance(text, str): return text
    replacements = {
        '\u2022': '-', '\u2192': '->', '\u201c': '"', '\u201d': '"',
        '\u2018': "'", '\u2019': "'", '\u2013': '-', '\u2014': '--',
        '✓': 'v', '⟳': '->', '•': '-'
    }
    for k, v in replacements.items():
        text = text.replace(k, v)
    return text.encode('latin-1', errors='ignore').decode('latin-1')


def generate_pdf(
    topic: str,
    report_md: str,
    critic_json: dict,
    diagram_png: bytes | None,
    diagram_title: str = "System Architecture",
) -> bytes:
    """
    Generate a professional research-paper-style PDF.
    Returns bytes on success, raises on failure.
    """
    topic = safe_text(topic)
    report_md = safe_text(report_md)
    diagram_title = safe_text(diagram_title)
    if isinstance(critic_json, dict):
        critic_json["verdict"] = safe_text(critic_json.get("verdict", ""))
        critic_json["strengths"] = [safe_text(s) for s in critic_json.get("strengths", [])]
        critic_json["improvements"] = [safe_text(i) for i in critic_json.get("improvements", [])]

    pdf = FPDF(unit="mm", format="A4")
    pdf.set_auto_page_break(auto=True, margin=22)
    MARGIN = 20

    # ── helper colours ────────────────────────────────────────────────────
    DARK_BLUE   = (10, 50, 100)
    MID_BLUE    = (30, 100, 180)
    LIGHT_BLUE  = (100, 160, 220)
    DARK_GREY   = (40, 40, 40)
    MID_GREY    = (90, 90, 90)
    LIGHT_GREY  = (180, 180, 180)
    WHITE       = (255, 255, 255)
    ACCENT_CYAN = (14, 165, 233)

    # ═══════════════════════════════════════════════════════════════════════
    #  COVER PAGE
    # ═══════════════════════════════════════════════════════════════════════
    pdf.add_page()

    # dark header band
    pdf.set_fill_color(8, 20, 45)
    pdf.rect(0, 0, 210, 80, "F")

    # gradient feel — layered semi-transparent rectangles
    pdf.set_fill_color(14, 40, 90)
    pdf.rect(0, 0, 210, 55, "F")
    pdf.set_fill_color(8, 20, 45)
    pdf.rect(0, 55, 210, 25, "F")

    # accent cyan line
    pdf.set_draw_color(*ACCENT_CYAN)
    pdf.set_line_width(0.8)
    pdf.line(MARGIN, 80, 210 - MARGIN, 80)

    # brand label
    pdf.set_xy(MARGIN, 12)
    pdf.set_font("Helvetica", "B", 9)
    pdf.set_text_color(*LIGHT_BLUE)
    pdf.cell(0, 6, "Nexus AI · Research Division", ln=True)

    # institution / date
    pdf.set_xy(MARGIN, 18)
    pdf.set_font("Helvetica", "", 8)
    pdf.set_text_color(120, 160, 200)
    pdf.cell(0, 5, f"Generated: {time.strftime('%B %d, %Y')}", ln=True)

    # main title
    pdf.set_xy(MARGIN, 32)
    pdf.set_font("Helvetica", "B", 24)
    pdf.set_text_color(*WHITE)
    pdf.multi_cell(210 - 2 * MARGIN, 11, "RESEARCH REPORT", align="C")

    pdf.set_xy(MARGIN, 50)
    pdf.set_font("Helvetica", "", 13)
    pdf.set_text_color(180, 210, 240)
    pdf.multi_cell(210 - 2 * MARGIN, 7, topic, align="C")

    # abstract box
    pdf.set_xy(MARGIN, 92)
    pdf.set_fill_color(240, 246, 255)
    pdf.set_draw_color(*LIGHT_BLUE)
    pdf.set_line_width(0.4)
    abs_h = 35
    pdf.rect(MARGIN, 92, 210 - 2 * MARGIN, abs_h, "FD")

    pdf.set_xy(MARGIN + 4, 95)
    pdf.set_font("Helvetica", "B", 9)
    pdf.set_text_color(*DARK_BLUE)
    pdf.cell(0, 5, "ABSTRACT", ln=True)
    pdf.set_xy(MARGIN + 4, 101)
    pdf.set_font("Helvetica", "", 8.5)
    pdf.set_text_color(*DARK_GREY)
    abstract_text = (
        f"This report presents a comprehensive, multi-agent AI-generated investigation into '{topic}'. "
        "Combining autonomous web-search, deep document reading, structured outlining, and iterative "
        "peer-review refinement, the system synthesises current research into a publication-ready "
        "academic document. All claims are grounded in retrieved evidence; the quality assurance "
        "section at the end records the automated critic score."
    )
    pdf.multi_cell(210 - 2 * MARGIN - 8, 5, abstract_text)

    # metadata row
    score_val = critic_json.get("score", "N/A") if isinstance(critic_json, dict) else "N/A"
    meta_y = 140
    pdf.set_font("Helvetica", "", 8)
    pdf.set_text_color(*MID_GREY)
    pdf.set_xy(MARGIN, meta_y)
    pdf.cell(55, 5, f"Quality Score: {score_val}/10")
    pdf.cell(55, 5, f"Model: LLaMA 3.3-70B (Groq)")
    pdf.cell(0,  5, f"System: Multi-Agent Pipeline", ln=True)

    # horizontal rule
    pdf.set_draw_color(*LIGHT_GREY)
    pdf.set_line_width(0.3)
    pdf.line(MARGIN, meta_y + 7, 210 - MARGIN, meta_y + 7)

    # footer
    pdf.set_xy(MARGIN, 275)
    pdf.set_font("Helvetica", "", 7)
    pdf.set_text_color(*LIGHT_GREY)
    pdf.cell(0, 4, "CONFIDENTIAL  ·  Nexus DeepResearch Platform  ·  AI-Assisted Academic Research", align="C")

    # ═══════════════════════════════════════════════════════════════════════
    #  TABLE OF CONTENTS
    # ═══════════════════════════════════════════════════════════════════════
    pdf.add_page()
    _section_header(pdf, "TABLE OF CONTENTS", MARGIN, DARK_BLUE, ACCENT_CYAN)
    pdf.ln(4)

    sections_list = _extract_sections(report_md)
    pdf.set_font("Helvetica", "", 10)
    pdf.set_text_color(*DARK_GREY)
    for i, sec_title in enumerate(sections_list, 1):
        clean = re.sub(r"^section\s+\d+:\s*", "", sec_title, flags=re.I).strip()
        pdf.cell(0, 7, f"  {i}.  {clean}", ln=True)
        pdf.set_draw_color(*LIGHT_GREY)
        pdf.set_line_width(0.1)
        pdf.line(MARGIN, pdf.get_y(), 210 - MARGIN, pdf.get_y())

    # ═══════════════════════════════════════════════════════════════════════
    #  ARCHITECTURE DIAGRAM PAGE
    # ═══════════════════════════════════════════════════════════════════════
    if diagram_png:
        pdf.add_page()
        _section_header(pdf, "SYSTEM ARCHITECTURE DIAGRAM", MARGIN, DARK_BLUE, ACCENT_CYAN)
        pdf.set_font("Helvetica", "", 9)
        pdf.set_text_color(*MID_GREY)
        pdf.multi_cell(0, 5,
            "The following diagram illustrates the key components and data-flow relationships "
            "identified through the automated research pipeline.", align="L")
        pdf.ln(4)

        # embed PNG from bytes
        png_buf = io.BytesIO(diagram_png)
        img_w = 210 - 2 * MARGIN          # full usable width
        try:
            pdf.image(png_buf, x=MARGIN, y=pdf.get_y(), w=img_w)
        except Exception:
            pass

        # caption
        pdf.set_xy(MARGIN, pdf.get_y() + 2)
        pdf.set_font("Helvetica", "I", 8)
        pdf.set_text_color(*MID_GREY)
        pdf.cell(0, 5, f"Figure 1. {diagram_title}", align="C", ln=True)

    # ═══════════════════════════════════════════════════════════════════════
    #  MAIN REPORT CONTENT
    # ═══════════════════════════════════════════════════════════════════════
    pdf.add_page()
    _render_markdown_to_pdf(pdf, report_md, MARGIN, DARK_BLUE, MID_BLUE, DARK_GREY)

    # ═══════════════════════════════════════════════════════════════════════
    #  QUALITY ASSURANCE PAGE
    # ═══════════════════════════════════════════════════════════════════════
    pdf.add_page()
    _section_header(pdf, "QUALITY ASSURANCE — PEER REVIEW", MARGIN, DARK_BLUE, ACCENT_CYAN)

    if isinstance(critic_json, dict):
        score = critic_json.get("score", "N/A")
        verdict = critic_json.get("verdict", "")
        strengths = critic_json.get("strengths", [])
        improvements = critic_json.get("improvements", [])

        # score badge
        score_val_num = float(score) if str(score).replace(".", "").isdigit() else 0
        badge_color = (34, 197, 94) if score_val_num >= 8.5 else (234, 179, 8) if score_val_num >= 7 else (239, 68, 68)
        pdf.set_fill_color(*badge_color)
        pdf.set_font("Helvetica", "B", 22)
        pdf.set_text_color(*WHITE)
        pdf.set_xy(MARGIN, pdf.get_y() + 2)
        pdf.cell(35, 12, f" {score}/10", fill=True, align="C")
        pdf.set_xy(MARGIN + 38, pdf.get_y() - 10)
        pdf.set_font("Helvetica", "I", 10)
        pdf.set_text_color(*DARK_GREY)
        pdf.multi_cell(0, 6, verdict)
        pdf.ln(5)

        if strengths:
            pdf.set_font("Helvetica", "B", 10)
            pdf.set_text_color(34, 120, 60)
            pdf.cell(0, 6, "STRENGTHS", ln=True)
            pdf.set_font("Helvetica", "", 9.5)
            pdf.set_text_color(*DARK_GREY)
            for s in strengths:
                pdf.multi_cell(0, 5.5, f"    *  {s}")

        pdf.ln(4)

        if improvements:
            pdf.set_font("Helvetica", "B", 10)
            pdf.set_text_color(180, 60, 30)
            pdf.cell(0, 6, "SUGGESTED IMPROVEMENTS", ln=True)
            pdf.set_font("Helvetica", "", 9.5)
            pdf.set_text_color(*DARK_GREY)
            for imp in improvements:
                pdf.multi_cell(0, 5.5, f"    *  {imp}")
    else:
        pdf.set_font("Helvetica", "", 10)
        pdf.set_text_color(*DARK_GREY)
        pdf.multi_cell(0, 6, str(critic_json))

    # ── page numbers footer on every page ─────────────────────────────────
    total = pdf.page
    for pg in range(1, total + 1):
        pdf.page = pg
        pdf.set_xy(0, 285)
        pdf.set_font("Helvetica", "", 7)
        pdf.set_text_color(*LIGHT_GREY)
        pdf.cell(0, 4,
                 f"Nexus DeepResearch Platform  ·  {topic}  ·  Page {pg} of {total}",
                 align="C")

    pdf.page = total   # reset to last page

    return bytes(pdf.output())


# ─────────────────────────────────────────────────────────────────────────────
#  PDF helper functions
# ─────────────────────────────────────────────────────────────────────────────
def _section_header(pdf, text, margin, dark_blue, accent_cyan):
    pdf.set_font("Helvetica", "B", 13)
    pdf.set_text_color(*dark_blue)
    pdf.set_xy(margin, pdf.get_y())
    pdf.cell(0, 8, text, ln=True)
    pdf.set_draw_color(*accent_cyan)
    pdf.set_line_width(0.6)
    pdf.line(margin, pdf.get_y(), 210 - margin, pdf.get_y())
    pdf.ln(3)


def _extract_sections(report_md: str) -> list[str]:
    sections = []
    for line in report_md.split("\n"):
        line = line.strip()
        if line.startswith("## ") and not line.startswith("### "):
            sections.append(line[3:].strip())
        elif re.match(r"^section\s+\d+:", line, re.I):
            sections.append(line)
    return sections


def _render_markdown_to_pdf(pdf, report_md, margin, dark_blue, mid_blue, dark_grey):
    lines = report_md.split("\n")
    in_code = False
    code_buf = []

    for raw_line in lines:
        # ── code block ────────────────────────────────────────────────────
        if raw_line.strip().startswith("```"):
            if in_code:
                in_code = False
                block = "\n".join(code_buf)
                code_buf = []
                # render code box
                pdf.set_font("Courier", "", 7.5)
                pdf.set_fill_color(245, 247, 252)
                pdf.set_text_color(50, 50, 80)
                pdf.set_draw_color(200, 210, 230)
                pdf.set_line_width(0.3)
                pdf.multi_cell(0, 4.5, block, fill=True, border=1)
                pdf.ln(2)
                pdf.set_text_color(*dark_grey)
            else:
                in_code = True
            continue

        if in_code:
            code_buf.append(raw_line)
            continue

        # ── strip inline markdown ──────────────────────────────────────────
        line = re.sub(r"\*\*(.+?)\*\*", r"\1", raw_line)
        line = re.sub(r"\*(.+?)\*",   r"\1", line)
        line = re.sub(r"`(.+?)`",     r"\1", line)
        line = re.sub(r"\[(.+?)\]\(.+?\)", r"\1", line)

        stripped = line.strip()

        # H1
        if stripped.startswith("# ") and not stripped.startswith("## "):
            txt = stripped[2:].strip()
            pdf.set_font("Helvetica", "B", 16)
            pdf.set_text_color(*dark_blue)
            pdf.ln(4)
            pdf.multi_cell(0, 10, txt)
            pdf.set_draw_color(14, 100, 180)
            pdf.set_line_width(0.5)
            pdf.line(margin, pdf.get_y(), 210 - margin, pdf.get_y())
            pdf.ln(3)

        # H2
        elif stripped.startswith("## ") and not stripped.startswith("### "):
            txt = stripped[3:].strip()
            pdf.set_font("Helvetica", "B", 13)
            pdf.set_text_color(*mid_blue)
            pdf.ln(5)
            pdf.multi_cell(0, 8, txt)
            pdf.set_draw_color(180, 210, 240)
            pdf.set_line_width(0.3)
            pdf.line(margin, pdf.get_y(), 210 - margin, pdf.get_y())
            pdf.ln(2)

        # H3
        elif stripped.startswith("### "):
            txt = stripped[4:].strip()
            pdf.set_font("Helvetica", "B", 11)
            pdf.set_text_color(50, 120, 190)
            pdf.ln(3)
            pdf.multi_cell(0, 7, txt)
            pdf.ln(1)

        # Bullet
        elif stripped.startswith("- ") or stripped.startswith("* "):
            txt = "    *  " + stripped[2:].strip()
            pdf.set_font("Helvetica", "", 9.5)
            pdf.set_text_color(*dark_grey)
            pdf.multi_cell(0, 5.5, txt)

        # Numbered list
        elif re.match(r"^\d+\. ", stripped):
            pdf.set_font("Helvetica", "", 9.5)
            pdf.set_text_color(*dark_grey)
            pdf.multi_cell(0, 5.5, "    " + stripped)

        # HR
        elif stripped in ("---", "***", "___"):
            pdf.set_draw_color(200, 200, 210)
            pdf.set_line_width(0.3)
            pdf.ln(2)
            pdf.line(margin, pdf.get_y(), 210 - margin, pdf.get_y())
            pdf.ln(2)

        # Empty line
        elif stripped == "":
            pdf.ln(2.5)

        # Normal paragraph
        else:
            pdf.set_font("Helvetica", "", 10)
            pdf.set_text_color(*dark_grey)
            pdf.multi_cell(0, 6, stripped)


# ─────────────────────────────────────────────────────────────────────────────
#  Retry wrapper
# ─────────────────────────────────────────────────────────────────────────────
def _parse_retry_seconds(err_str: str) -> float:
    """
    Extract the suggested wait from a Groq 429 message like:
      'Please try again in 5m6.72s.'
    Returns seconds as a float, or 30.0 if not parseable.
    """
    import re as _re
    # e.g. "5m6.72s" or "30.5s" or "2m"
    m = _re.search(r'try again in\s+(?:(\d+)m)?(?:([\d.]+)s)?', err_str)
    if m:
        mins = float(m.group(1) or 0)
        secs = float(m.group(2) or 0)
        total = mins * 60 + secs
        return max(total, 1.0)
    # fallback: check for just seconds
    m2 = _re.search(r'([\d.]+)\s*s', err_str)
    if m2:
        return float(m2.group(1))
    return 30.0


def invoke_with_retry(chain_or_agent, params, max_retries=5):
    """
    Invoke a LangChain chain/agent with smart retry logic:
    - 429 rate-limit  → waits the exact time Groq asks for (capped at 120 s)
    - TPD daily limit → warns and raises immediately (no point retrying)
    - Other errors    → exponential back-off (3 s, 6 s, 9 s …)
    """
    for attempt in range(max_retries):
        try:
            return chain_or_agent.invoke(params)
        except Exception as e:
            err_str = str(e)

            is_rate_limit = "429" in err_str or "rate_limit_exceeded" in err_str
            is_daily_limit = "tokens per day" in err_str or "TPD" in err_str
            is_too_large = "413" in err_str or "too large" in err_str.lower() or "tokens per minute (TPM)" in err_str

            # Request too large (Token limit exceeded for a single request)
            if is_too_large:
                raise RuntimeError(
                    f"Message size too large for the model's TPM limit (Error 413). "
                    f"Switch to a model with a higher TPM, or reduce the report size. "
                    f"Original error: {e}"
                ) from e

            # Daily token limit — cannot recover by waiting a few seconds
            if is_daily_limit:
                wait_secs = _parse_retry_seconds(err_str)
                # cap at 120 s so we don't freeze the app forever
                wait_secs = min(wait_secs, 120.0)
                if attempt == max_retries - 1:
                    raise RuntimeError(
                        f"Groq daily token limit hit. "
                        f"Switch to a lighter model or wait ~{wait_secs:.0f}s. "
                        f"Original error: {e}"
                    ) from e
                st.warning(
                    f"⏳ Groq daily token limit — waiting **{wait_secs:.0f}s** before retry "
                    f"(attempt {attempt + 1}/{max_retries})…"
                )
                time.sleep(wait_secs)
                continue

            # Per-minute / per-request rate limit
            if is_rate_limit:
                wait_secs = min(_parse_retry_seconds(err_str), 120.0)
                if attempt == max_retries - 1:
                    raise e
                st.warning(
                    f"⏳ Rate limit — waiting **{wait_secs:.0f}s** "
                    f"(attempt {attempt + 1}/{max_retries})…"
                )
                time.sleep(wait_secs)
                continue

            # Generic error — exponential back-off
            if attempt == max_retries - 1:
                raise e
            time.sleep(3 * (attempt + 1))


# ═════════════════════════════════════════════════════════════════════════════
#  STREAMLIT APP
# ═════════════════════════════════════════════════════════════════════════════
st.set_page_config(
    page_title="Nexus · DeepResearch",
    page_icon="🌌",
    layout="wide",
    initial_sidebar_state="collapsed",
)

# ── Stunning CSS ──────────────────────────────────────────────────────────────
st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Space+Grotesk:wght@300;400;500;600;700&family=Orbitron:wght@400;700;900&family=JetBrains+Mono:wght@400;700&display=swap');

/* ── Global reset ─────────────────────────────────────────────── */
*, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }
html, body, [class*="css"] {
    font-family: 'Space Grotesk', sans-serif;
    color: #e2e8f0;
}
#MainMenu, footer, header { visibility: hidden; }

/* ── App background ───────────────────────────────────────────── */
.stApp {
    background: #020817;
    background-image:
        radial-gradient(ellipse 80% 50% at 20% 0%, rgba(14,165,233,0.12) 0%, transparent 60%),
        radial-gradient(ellipse 60% 40% at 80% 0%, rgba(139,92,246,0.10) 0%, transparent 60%),
        radial-gradient(ellipse 40% 60% at 50% 100%, rgba(16,185,129,0.06) 0%, transparent 70%);
    min-height: 100vh;
}
.block-container {
    padding: 2rem 3rem 5rem !important;
    max-width: 1300px !important;
    margin: auto !important;
}

/* ── Animated grid overlay ────────────────────────────────────── */
.stApp::before {
    content: '';
    position: fixed;
    inset: 0;
    background-image:
        linear-gradient(rgba(14,165,233,0.04) 1px, transparent 1px),
        linear-gradient(90deg, rgba(14,165,233,0.04) 1px, transparent 1px);
    background-size: 50px 50px;
    pointer-events: none;
    z-index: 0;
    animation: gridPulse 8s ease-in-out infinite;
}
@keyframes gridPulse {
    0%, 100% { opacity: 0.6; }
    50%       { opacity: 1.0; }
}

/* ── Hero section ─────────────────────────────────────────────── */
.hero-wrap {
    text-align: center;
    padding: 3rem 0 1.5rem;
    position: relative;
}
.hero-badge {
    display: inline-block;
    background: rgba(14,165,233,0.12);
    border: 1px solid rgba(14,165,233,0.35);
    border-radius: 999px;
    padding: 5px 18px;
    font-size: 0.75rem;
    font-weight: 600;
    letter-spacing: 3px;
    text-transform: uppercase;
    color: #38bdf8;
    margin-bottom: 1.2rem;
    animation: badgePulse 3s ease-in-out infinite;
}
@keyframes badgePulse {
    0%, 100% { box-shadow: 0 0 0 0 rgba(14,165,233,0); }
    50%       { box-shadow: 0 0 0 8px rgba(14,165,233,0.08); }
}
.hero-title {
    font-family: 'Orbitron', sans-serif;
    font-size: clamp(2.8rem, 6vw, 5rem);
    font-weight: 900;
    line-height: 1.1;
    letter-spacing: -1px;
    background: linear-gradient(135deg, #ffffff 0%, #38bdf8 40%, #818cf8 70%, #c084fc 100%);
    -webkit-background-clip: text;
    -webkit-text-fill-color: transparent;
    background-clip: text;
    text-shadow: none;
    margin-bottom: 1rem;
    animation: titleShimmer 6s ease-in-out infinite;
    background-size: 200% auto;
}
@keyframes titleShimmer {
    0%   { background-position: 0% center; }
    50%  { background-position: 100% center; }
    100% { background-position: 0% center; }
}
.hero-sub {
    font-size: 1.1rem;
    font-weight: 400;
    color: #64748b;
    max-width: 700px;
    margin: 0 auto 0.5rem;
    line-height: 1.7;
}
.hero-sub span { color: #38bdf8; font-weight: 500; }

/* ── Stat pills ───────────────────────────────────────────────── */
.stat-row {
    display: flex;
    justify-content: center;
    gap: 1rem;
    margin: 1.5rem 0 2.5rem;
    flex-wrap: wrap;
}
.stat-pill {
    background: rgba(255,255,255,0.03);
    border: 1px solid rgba(255,255,255,0.08);
    border-radius: 999px;
    padding: 8px 20px;
    font-size: 0.82rem;
    color: #94a3b8;
    transition: all 0.3s ease;
}
.stat-pill b { color: #e2e8f0; }

/* ── Input card ───────────────────────────────────────────────── */
.input-card {
    background: rgba(255,255,255,0.025);
    backdrop-filter: blur(20px);
    -webkit-backdrop-filter: blur(20px);
    border: 1px solid rgba(14,165,233,0.2);
    border-radius: 24px;
    padding: 2rem 2.5rem;
    margin-bottom: 2rem;
    box-shadow: 0 8px 40px rgba(0,0,0,0.4), 0 0 0 1px rgba(255,255,255,0.03);
    transition: border-color 0.3s ease;
}
.input-card:hover { border-color: rgba(14,165,233,0.4); }
.input-label {
    font-size: 0.78rem;
    font-weight: 600;
    letter-spacing: 2px;
    text-transform: uppercase;
    color: #38bdf8;
    margin-bottom: 1rem;
}

/* Streamlit widget overrides */
.stTextInput > label { display: none !important; }
.stTextInput input {
    background: rgba(0,0,0,0.35) !important;
    border: 1.5px solid rgba(14,165,233,0.3) !important;
    border-radius: 14px !important;
    color: #f1f5f9 !important;
    font-size: 1.05rem !important;
    font-family: 'Space Grotesk', sans-serif !important;
    padding: 0.85rem 1.2rem !important;
    transition: all 0.3s ease !important;
}
.stTextInput input:focus {
    border-color: #38bdf8 !important;
    box-shadow: 0 0 0 3px rgba(14,165,233,0.15), 0 0 20px rgba(14,165,233,0.1) !important;
    outline: none !important;
}
.stTextInput input::placeholder { color: #475569 !important; }

/* ── Buttons ──────────────────────────────────────────────────── */
.stButton > button {
    background: linear-gradient(135deg, #0ea5e9 0%, #6366f1 60%, #8b5cf6 100%) !important;
    color: white !important;
    font-family: 'Orbitron', sans-serif !important;
    font-weight: 700 !important;
    font-size: 0.85rem !important;
    letter-spacing: 2px !important;
    text-transform: uppercase !important;
    border-radius: 14px !important;
    border: none !important;
    padding: 0.85rem 1.5rem !important;
    width: 100% !important;
    transition: all 0.3s cubic-bezier(0.4,0,0.2,1) !important;
    box-shadow: 0 4px 20px rgba(14,165,233,0.3) !important;
    position: relative !important;
    overflow: hidden !important;
}
.stButton > button:hover {
    transform: translateY(-3px) !important;
    box-shadow: 0 8px 30px rgba(14,165,233,0.5) !important;
}
.stButton > button:active { transform: translateY(0) !important; }

/* Download buttons */
.stDownloadButton > button {
    background: rgba(14,165,233,0.1) !important;
    border: 1px solid rgba(14,165,233,0.4) !important;
    color: #38bdf8 !important;
    font-family: 'Space Grotesk', sans-serif !important;
    font-weight: 600 !important;
    font-size: 0.88rem !important;
    border-radius: 12px !important;
    padding: 0.7rem 1rem !important;
    transition: all 0.3s ease !important;
}
.stDownloadButton > button:hover {
    background: rgba(14,165,233,0.2) !important;
    box-shadow: 0 0 20px rgba(14,165,233,0.25) !important;
    transform: translateY(-2px) !important;
}

/* ── Agent pipeline cards ─────────────────────────────────────── */
.stStatus {
    background: rgba(255,255,255,0.02) !important;
    border: 1px solid rgba(255,255,255,0.06) !important;
    border-radius: 16px !important;
}

/* ── Results section ──────────────────────────────────────────── */
.results-card {
    background: rgba(255,255,255,0.022);
    backdrop-filter: blur(16px);
    border: 1px solid rgba(255,255,255,0.07);
    border-radius: 24px;
    padding: 2.5rem;
    margin-bottom: 2rem;
    box-shadow: 0 20px 60px rgba(0,0,0,0.5);
}
.results-header {
    font-family: 'Orbitron', sans-serif;
    font-size: 1rem;
    font-weight: 700;
    letter-spacing: 3px;
    text-transform: uppercase;
    color: #38bdf8;
    margin-bottom: 1.5rem;
    padding-bottom: 1rem;
    border-bottom: 1px solid rgba(14,165,233,0.2);
}

/* ── Markdown report styles ───────────────────────────────────── */
.report-body h1 {
    font-family: 'Space Grotesk', sans-serif;
    font-size: 1.7rem; font-weight: 700;
    color: #f1f5f9; border-bottom: 2px solid #0ea5e9;
    padding-bottom: 0.5rem; margin: 2rem 0 1rem;
}
.report-body h2 {
    font-size: 1.25rem; font-weight: 600;
    color: #38bdf8; margin: 1.8rem 0 0.8rem;
    font-family: 'Space Grotesk', sans-serif;
}
.report-body h3 {
    font-size: 1.05rem; font-weight: 600;
    color: #818cf8; margin: 1.4rem 0 0.6rem;
}
.report-body p { line-height: 1.85; color: #cbd5e1; margin-bottom: 1rem; }
.report-body ul, .report-body ol { color: #cbd5e1; margin: 0.5rem 0 1rem 1.5rem; }
.report-body li { margin-bottom: 0.4rem; line-height: 1.7; }
.report-body code {
    background: rgba(14,165,233,0.1); color: #38bdf8;
    padding: 2px 6px; border-radius: 4px; font-size: 0.88em;
    font-family: 'JetBrains Mono', monospace;
}
.report-body pre {
    background: rgba(0,0,0,0.5);
    border: 1px solid rgba(255,255,255,0.08);
    border-radius: 12px; padding: 1.2rem; overflow-x: auto;
    margin: 1rem 0;
}
.report-body pre code { background: none; padding: 0; color: #94a3b8; }
.report-body blockquote {
    border-left: 3px solid #0ea5e9;
    background: rgba(14,165,233,0.05);
    padding: 0.8rem 1.2rem; border-radius: 0 8px 8px 0;
    color: #94a3b8; margin: 1rem 0;
}
.report-body hr { border: none; border-top: 1px solid rgba(255,255,255,0.08); margin: 2rem 0; }

/* ── Score badge ──────────────────────────────────────────────── */
.score-badge {
    display: inline-flex; align-items: center; gap: 0.5rem;
    background: linear-gradient(135deg, rgba(34,197,94,0.15), rgba(16,185,129,0.08));
    border: 1px solid rgba(34,197,94,0.4);
    border-radius: 12px; padding: 0.6rem 1.2rem;
    font-size: 1.4rem; font-weight: 700;
    color: #4ade80; font-family: 'Orbitron', sans-serif;
}
.score-badge.warn {
    background: linear-gradient(135deg, rgba(234,179,8,0.15), rgba(202,138,4,0.08));
    border-color: rgba(234,179,8,0.4); color: #facc15;
}
.score-badge.fail {
    background: linear-gradient(135deg, rgba(239,68,68,0.15), rgba(220,38,38,0.08));
    border-color: rgba(239,68,68,0.4); color: #f87171;
}

/* ── QA columns ───────────────────────────────────────────────── */
.qa-box {
    background: rgba(255,255,255,0.02);
    border-radius: 16px; padding: 1.5rem;
    border: 1px solid rgba(255,255,255,0.06);
}
.qa-box h4 {
    font-size: 0.75rem; letter-spacing: 2px; text-transform: uppercase;
    font-weight: 700; margin-bottom: 1rem;
}
.qa-box.strengths h4 { color: #4ade80; }
.qa-box.improvements h4 { color: #fb923c; }
.qa-box ul { list-style: none; padding: 0; }
.qa-box li { padding: 0.4rem 0; border-bottom: 1px solid rgba(255,255,255,0.04); font-size: 0.92rem; line-height: 1.6; }
.qa-box li:last-child { border-bottom: none; }
.qa-box.strengths li::before { content: "✓  "; color: #4ade80; }
.qa-box.improvements li::before { content: "→  "; color: #fb923c; }

/* ── Diagram section ──────────────────────────────────────────── */
.diagram-wrap {
    background: rgba(5,10,20,0.7);
    border: 1px solid rgba(14,165,233,0.2);
    border-radius: 20px; padding: 1.5rem;
    margin: 2rem 0;
}
.diagram-title {
    font-family: 'Orbitron', sans-serif;
    font-size: 0.8rem; letter-spacing: 3px;
    text-transform: uppercase; color: #38bdf8;
    margin-bottom: 1rem;
}

/* ── Divider ──────────────────────────────────────────────────── */
.fancy-divider {
    display: flex; align-items: center; gap: 1rem;
    margin: 2.5rem 0;
}
.fancy-divider::before, .fancy-divider::after {
    content: ''; flex: 1;
    height: 1px;
    background: linear-gradient(90deg, transparent, rgba(14,165,233,0.3), transparent);
}
.fancy-divider span {
    font-size: 0.7rem; letter-spacing: 4px;
    text-transform: uppercase; color: #334155;
}

/* Streamlit expander */
.streamlit-expanderHeader {
    background: rgba(255,255,255,0.02) !important;
    border-radius: 12px !important;
}
</style>
""", unsafe_allow_html=True)

# ── Session State ─────────────────────────────────────────────────────────────
_defaults = {
    "report_generated": False,
    "final_report": "",
    "critic_json": {},
    "pdf_bytes": None,
    "diagram_png": None,
    "diagram_data": None,
    "topic_used": "",
}
for k, v in _defaults.items():
    if k not in st.session_state:
        st.session_state[k] = v

# ═════════════════════════════════════════════════════════════════════════════
#  HERO
# ═════════════════════════════════════════════════════════════════════════════
st.markdown("""
<div class="hero-wrap">
    <div class="hero-badge">⚡ Multi-Agent AI Research System</div>
    <h1 class="hero-title">Nexus <span>DeepResearch</span></h1>
    <p class="hero-sub">
        Autonomous deep-research powered by <span>6 AI agents</span> working in concert —
        search, read, outline, write, critique, and refine.
    </p>
</div>
<div class="stat-row">
    <div class="stat-pill">📄 <b>5–10 Page</b> Academic Reports</div>
    <div class="stat-pill">🔄 <b>Auto Quality</b> Refinement Loop</div>
    <div class="stat-pill">📊 <b>Architecture</b> Diagrams</div>
    <div class="stat-pill">📑 <b>PDF Export</b> Included</div>
</div>
""", unsafe_allow_html=True)

# ═════════════════════════════════════════════════════════════════════════════
#  INPUT CARD
# ═════════════════════════════════════════════════════════════════════════════
st.markdown('<div class="input-card">', unsafe_allow_html=True)
st.markdown('<p class="input-label">🔬 Research Topic</p>', unsafe_allow_html=True)

col_inp, col_btn = st.columns([4, 1])
with col_inp:
    topic = st.text_input(
        "topic",
        placeholder="e.g. Large Language Models in Drug Discovery",
        label_visibility="collapsed",
        key="topic_input"
    )
with col_btn:
    st.markdown("<br/>", unsafe_allow_html=True)   # vertical alignment
    run_btn = st.button("🚀 INITIATE", key="run_button")

st.markdown("</div>", unsafe_allow_html=True)


# ═════════════════════════════════════════════════════════════════════════════
#  PIPELINE
# ═════════════════════════════════════════════════════════════════════════════
if run_btn:
    if not topic.strip():
        st.error("⚠️ Please enter a research topic to begin.")
    else:
        # reset state
        for k, v in _defaults.items():
            st.session_state[k] = v
        st.session_state["topic_used"] = topic.strip()

        with st.status("🤖 **Neural Agents Initialising…**", expanded=True) as pipeline_status:
            try:
                from agents import (
                    build_reader_agent, build_search_agent,
                    outline_chain, section_writer_chain,
                    critic_chain, refiner_chain, diagram_chain
                )
                # ── Agent 1: Search ───────────────────────────────────────
                st.write("🌐 **Agent 1 · Searcher** — Scanning global knowledge base…")
                search_agent = build_search_agent()
                search_raw = invoke_with_retry(
                    search_agent,
                    {"messages": [("user", f"Find recent, reliable and detailed information about: {topic}")]}
                )
                search_res = search_raw["messages"][-1][1] if isinstance(search_raw["messages"][-1], tuple) else search_raw["messages"][-1].content if hasattr(search_raw["messages"][-1], 'content') else str(search_raw["messages"][-1])
                st.write("  ✅ Web intelligence gathered.")

                # ── Agent 2: Reader ───────────────────────────────────────
                st.write("📖 **Agent 2 · Reader** — Deep-reading top sources…")
                reader_agent = build_reader_agent()
                reader_raw = invoke_with_retry(
                    reader_agent,
                    {"messages": [("user", f"Based on these results about '{topic}', scrape the most relevant URL:\n{search_res[:1000]}")]}
                )
                read_res = reader_raw["messages"][-1][1] if isinstance(reader_raw["messages"][-1], tuple) else reader_raw["messages"][-1].content if hasattr(reader_raw["messages"][-1], 'content') else str(reader_raw["messages"][-1])
                st.write("  ✅ Source content extracted.")

                combined_research = f"SEARCH RESULTS:\n{search_res}\n\nSCRAPED CONTENT:\n{read_res}"
                research_summary  = combined_research[:2000]

                # ── Diagram Chain ─────────────────────────────────────────
                st.write("🗺️ **Diagram Agent** — Mapping system architecture…")
                diagram_data = None
                diagram_png  = None
                try:
                    diagram_data = invoke_with_retry(
                        diagram_chain,
                        {"topic": topic, "research_summary": research_summary}
                    )
                    diagram_png = render_architecture_diagram(diagram_data)
                    if diagram_png:
                        st.write("  ✅ Architecture diagram rendered.")
                    else:
                        st.write("  ⚠️ Diagram render skipped (matplotlib unavailable).")
                except Exception as de:
                    st.write(f"  ⚠️ Diagram generation note: {de}")

                # ── Agent 3: Outline ──────────────────────────────────────
                st.write("📐 **Agent 3 · Architect** — Structuring 6-8 section outline…")
                outline = invoke_with_retry(
                    outline_chain,
                    {"topic": topic, "research": combined_research}
                )
                sections = [s.strip() for s in outline.split("\n") if s.strip().startswith("Section")]
                if not sections:
                    sections = [s.strip() for s in outline.split("\n") if s.strip()][:8]
                st.write(f"  ✅ {len(sections)} sections planned.")

                # ── Agent 4: Writer ───────────────────────────────────────
                st.write(f"✍️ **Agent 4 · Writer** — Composing {len(sections)} sections…")
                full_report = f"# Research Report: {topic}\n\n---\n\n"
                progress = st.progress(0, text="Initialising writer…")

                for idx, section in enumerate(sections):
                    st.write(f"   ↳ Writing **{section}**…")
                    sec_content = invoke_with_retry(
                        section_writer_chain,
                        {
                            "topic":         topic,
                            "outline":       outline,
                            "section_title": section,
                            "research":      combined_research
                        }
                    )
                    full_report += f"\n\n---\n\n## {section}\n\n{sec_content}\n\n"
                    progress.progress((idx + 1) / len(sections),
                                      text=f"Section {idx+1}/{len(sections)} written")

                st.write("  ✅ Full draft compiled.")

                # ── Agent 5 + 6: Critic / Refiner loop ───────────────────
                st.write("🧐 **Agent 5 · Critic** — Peer-reviewing the draft…")
                MAX_ITER     = 3
                iteration    = 0
                final_score  = 0.0
                critic_result = {}

                while iteration < MAX_ITER:
                    st.write(f"   ↳ Quality check pass {iteration + 1}…")
                    try:
                        critic_result = invoke_with_retry(critic_chain, {"report": full_report})
                        final_score = float(critic_result.get("score", 0))
                    except Exception as ce:
                        st.write(f"   ⚠️ Critic error or rate limit reached: {ce}")
                        st.write("   ⚠️ Proceeding to PDF generation with current draft...")
                        break  # Break out of loop to ensure PDF is generated

                    emoji = "🟢" if final_score >= 8.5 else "🟡" if final_score >= 7 else "🔴"
                    st.write(f"   {emoji} Score: **{final_score}/10**")

                    if final_score >= 8.5:
                        st.write("  ✅ Quality target achieved!")
                        break
                    else:
                        iteration += 1
                        if iteration < MAX_ITER:
                            st.write(f"   🔄 **Agent 6 · Refiner** — Improving draft (pass {iteration})…")
                            try:
                                feedback = "\n".join(critic_result.get("improvements", []))
                                full_report = invoke_with_retry(
                                    refiner_chain,
                                    {"topic": topic, "report": full_report, "feedback": feedback}
                                )
                            except Exception as re:
                                st.write(f"   ⚠️ Refiner error or rate limit reached: {re}")
                                st.write("   ⚠️ Proceeding to PDF generation with current draft...")
                                break  # Break out of loop to ensure PDF is generated
                        else:
                            st.write(f"   ℹ️ Max iterations reached — final score: {final_score}/10")

                # ── PDF Generation ────────────────────────────────────────
                st.write("📄 **System** — Generating professional PDF with diagrams…")
                pdf_bytes = None
                if PDF_ENABLED:
                    try:
                        diag_title = diagram_data.get("title", "System Architecture") if diagram_data else "System Architecture"
                        pdf_bytes = generate_pdf(
                            topic       = topic,
                            report_md   = full_report,
                            critic_json = critic_result,
                            diagram_png = diagram_png,
                            diagram_title = diag_title,
                        )
                        st.write(f"  ✅ PDF generated — {len(pdf_bytes):,} bytes.")
                    except Exception as pe:
                        st.write(f"  ⚠️ PDF error: {pe}")
                else:
                    st.write("  ⚠️ fpdf2 not installed — PDF unavailable.")

                pipeline_status.update(label="⚡ Research Pipeline Complete!", state="complete", expanded=False)

                # ── Persist to session state ──────────────────────────────
                st.session_state["final_report"]      = full_report
                st.session_state["critic_json"]       = critic_result
                st.session_state["pdf_bytes"]         = pdf_bytes
                st.session_state["diagram_png"]       = diagram_png
                st.session_state["diagram_data"]      = diagram_data
                st.session_state["report_generated"]  = True
                st.rerun()

            except Exception as fatal:
                pipeline_status.update(label="❌ Pipeline Failed", state="error", expanded=True)
                st.error(f"**Fatal Error:** {fatal}")
                import traceback
                st.code(traceback.format_exc(), language="python")


# ═════════════════════════════════════════════════════════════════════════════
#  RESULTS
# ═════════════════════════════════════════════════════════════════════════════
if st.session_state.get("report_generated"):
    used_topic   = st.session_state["topic_used"]
    critic_json  = st.session_state["critic_json"]
    final_report = st.session_state["final_report"]
    pdf_bytes    = st.session_state["pdf_bytes"]
    diagram_png  = st.session_state["diagram_png"]
    diagram_data = st.session_state["diagram_data"]

    score_val = float(critic_json.get("score", 0)) if isinstance(critic_json, dict) else 0
    score_cls = "score-badge" if score_val >= 8.5 else "score-badge warn" if score_val >= 7 else "score-badge fail"

    # ── top ribbon ────────────────────────────────────────────────────────
    st.markdown(f"""
    <div style="display:flex; align-items:center; justify-content:space-between;
                background:rgba(255,255,255,0.02); border:1px solid rgba(255,255,255,0.06);
                border-radius:16px; padding:1.2rem 2rem; margin-bottom:1.5rem;">
        <div>
            <div style="font-size:0.72rem;letter-spacing:3px;text-transform:uppercase;color:#38bdf8;margin-bottom:4px;">
                RESEARCH COMPLETE
            </div>
            <div style="font-size:1.1rem;font-weight:600;color:#f1f5f9;">{used_topic}</div>
        </div>
        <div class="{score_cls}">
            {score_val:.1f} <span style="font-size:0.9rem;opacity:0.6;">/ 10</span>
        </div>
    </div>
    """, unsafe_allow_html=True)

    # ── download row ──────────────────────────────────────────────────────
    dl1, dl2, dl3 = st.columns([2, 1, 1])
    with dl2:
        st.download_button(
            label="⬇️ Download Markdown",
            data=final_report,
            file_name=f"Report_{used_topic.replace(' ', '_')[:40]}.md",
            mime="text/markdown",
            use_container_width=True
        )
    with dl3:
        if pdf_bytes:
            st.download_button(
                label="⬇️ Download PDF",
                data=pdf_bytes,
                file_name=f"Report_{used_topic.replace(' ', '_')[:40]}.pdf",
                mime="application/pdf",
                use_container_width=True
            )
        else:
            st.button("PDF N/A", disabled=True, use_container_width=True)

    st.markdown('<div class="fancy-divider"><span>Architecture</span></div>', unsafe_allow_html=True)

    # ── Architecture diagram ───────────────────────────────────────────────
    if diagram_png:
        diag_title = diagram_data.get("title", "System Architecture") if diagram_data else "System Architecture"
        diag_sub   = diagram_data.get("subtitle", "") if diagram_data else ""
        st.markdown(f"""
        <div class="diagram-wrap">
            <div class="diagram-title">📊 Figure 1 · {diag_title}</div>
            {"<div style='font-size:0.85rem;color:#64748b;margin-bottom:0.8rem;'>" + diag_sub + "</div>" if diag_sub else ""}
        </div>
        """, unsafe_allow_html=True)
        st.image(diagram_png, use_column_width=True, caption=diag_title)

    st.markdown('<div class="fancy-divider"><span>Research Report</span></div>', unsafe_allow_html=True)

    # ── Report body ───────────────────────────────────────────────────────
    st.markdown('<div class="results-card"><div class="report-body">', unsafe_allow_html=True)
    st.markdown(final_report)
    st.markdown("</div></div>", unsafe_allow_html=True)

    st.markdown('<div class="fancy-divider"><span>Quality Assurance</span></div>', unsafe_allow_html=True)

    # ── QA section ────────────────────────────────────────────────────────
    if isinstance(critic_json, dict):
        verdict = critic_json.get("verdict", "")
        strengths    = critic_json.get("strengths", [])
        improvements = critic_json.get("improvements", [])

        if verdict:
            st.markdown(f"""
            <div style="background:rgba(14,165,233,0.06);border:1px solid rgba(14,165,233,0.2);
                        border-radius:14px;padding:1rem 1.5rem;margin-bottom:1.5rem;
                        font-style:italic;color:#94a3b8;line-height:1.7;">
                " {verdict} "
            </div>
            """, unsafe_allow_html=True)

        qa_col1, qa_col2 = st.columns(2)
        with qa_col1:
            items_html = "".join(f"<li>{s}</li>" for s in strengths)
            st.markdown(f"""
            <div class="qa-box strengths">
                <h4>✓ Strengths</h4>
                <ul>{items_html}</ul>
            </div>
            """, unsafe_allow_html=True)
        with qa_col2:
            items_html = "".join(f"<li>{i}</li>" for i in improvements)
            st.markdown(f"""
            <div class="qa-box improvements">
                <h4>→ Suggested Improvements</h4>
                <ul>{items_html}</ul>
            </div>
            """, unsafe_allow_html=True)

    # ── footer ────────────────────────────────────────────────────────────
    st.markdown("""
    <div style="text-align:center;padding:3rem 0 1rem;color:#1e293b;font-size:0.78rem;letter-spacing:1px;">
        Nexus DeepResearch · Multi-Agent Research Platform · Powered by LLaMA 3.1-8B via Groq
    </div>
    """, unsafe_allow_html=True)