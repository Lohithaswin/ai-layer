"""
Strict section-title classifier + batched DB update.

Key validation rules:
- Real headings: "6.5.2. Map roles to Groups", "9. MFA Login Process"
- NOT headings: numbered list steps ("2. In the left navigation pane...")
- NOT headings: truncated chunks ending mid-word ("3. Role Based a")
"""
import psycopg2
import psycopg2.extras
import re

DB = dict(host="localhost", port=5433, database="rag_db", user="postgres", password="password")

# Matches candidate headings (flat)
_FLAT_RE = re.compile(
    r"(?:^|\n)[ \t]*(\d+(?:\.\d+)*\.?\s+[A-Z][^\n]{2,80})",
    re.MULTILINE,
)

# TOC dot-leaders / page numbers
_TOC_RE = re.compile(r"\.{3,}|\s{3,}\d{1,4}\s*$|^\s*\d{1,4}\s*$", re.M)

# Action verbs that mark a numbered STEP, not a heading
_STEP_STARTS = re.compile(
    r"^(?:"
    r"In\s+the\b|Click\b|Select\b|Go\s+to\b|Open\b|Enter\b|Type\b|Navigate\b|"
    r"Ensure\b|Verify\b|Check\b|Under\b|After\b|Before\b|Once\b|When\b|"
    r"Use\b|Run\b|Execute\b|Perform\b|Follow\b|Refer\b|Note\b|"
    r"If\b|The\b|This\b|These\b|For\b|On\b|At\b|To\b|From\b|With\b"
    r")",
    re.IGNORECASE,
)

# Common short words that signal a truncated heading (chunk cut mid-word)
_TRUNCATION_ENDINGS = re.compile(
    r"\s+[a-z]{1,2}$"       # ends with single or double lowercase letter: "Role Based a"
    r"|\s+(?:an?|the|of|in|on|at|to|by|or|and|but|for|with|from|into|over|also|that|this|these|those)$",
    re.IGNORECASE,
)


def _is_real_heading(raw: str, text: str = "") -> bool:
    """Return True only if raw looks like a genuine section heading."""
    title = raw.strip()

    if not title:
        return False

    # Too long = sentence, not a heading
    if len(title) > 120:
        return False

    # TOC dot-leaders
    if _TOC_RE.search(title):
        return False

    # Strip leading number to get body
    body = re.sub(r"^\d+(?:\.\d+)*\.?\s*", "", title).strip()
    if len(body) < 3:
        return False

    # ── TRUNCATION CHECK ──────────────────────────────────────────────────────
    # If the heading ends at (or very near) the end of the text chunk,
    # it was almost certainly cut mid-word by the chunker.
    if text:
        # Where does this title appear in the text?
        pos = text.find(title)
        if pos != -1:
            end_pos = pos + len(title)
            remaining = text[end_pos:].strip()
            # If there's no newline after the title and no content,
            # it's at the chunk boundary = truncated
            if not remaining and not title.endswith((")", "]", "'", '"')):
                # Allow only if title ends with a real complete word (4+ chars)
                last_word = title.split()[-1] if title.split() else ""
                if len(last_word) <= 3 and not last_word[-1].isupper():
                    return False

    # Reject if body ends with truncation signals (single char, articles)
    if _TRUNCATION_ENDINGS.search(title):
        return False

    # Heading bodies shouldn't end with a period or colon (that's a sentence/step)
    if body.endswith(".") or body.endswith(":"):
        return False

    num_part = re.match(r"^(\d+(?:\.\d+)*)", title)
    depth = len(num_part.group(1).split(".")) if num_part else 1

    # Steps are usually sentences, which we caught with `.endswith(".")`.
    # But just in case, check verbs.
    if _STEP_STARTS.match(body):
        return False

    if depth == 1:
        words = body.split()
        if len(words) > 10:
            return False
        if "," in body:
            return False

    elif depth == 2:
        words = body.split()
        if len(words) > 12:
            return False

    # depth >= 3 → always accept (e.g. 6.5.2. Configure something)
    return True


def run():
    conn = psycopg2.connect(**DB)
    conn.autocommit = False

    print("Loading document IDs…")
    with conn.cursor() as cur:
        cur.execute("SELECT id FROM documents ORDER BY id")
        doc_ids = [r[0] for r in cur.fetchall()]
    print(f"  {len(doc_ids)} documents")

    total = 0

    for doc_id in doc_ids:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                """SELECT id, text, parent_text
                   FROM document_chunks
                   WHERE document_id = %s
                   ORDER BY page ASC, chunk_index ASC""",
                (doc_id,),
            )
            chunks = cur.fetchall()

        if not chunks:
            continue

        current = None
        updates = []

        for chunk in chunks:
            text = chunk["text"] or ""
            parent = chunk["parent_text"] or ""

            candidates = [
                m.group(1).strip()
                for m in _FLAT_RE.finditer(text)
                if _is_real_heading(m.group(1), text)
            ]

            if candidates:
                current = candidates[-1]
            elif current is None and parent:
                p_cands = [
                    m.group(1).strip()
                    for m in _FLAT_RE.finditer(parent)
                    if _is_real_heading(m.group(1), parent)
                ]
                if p_cands:
                    current = p_cands[-1]

            updates.append((current, chunk["id"]))

        with conn.cursor() as cur:
            psycopg2.extras.execute_batch(
                cur,
                "UPDATE document_chunks SET section_title = %s WHERE id = %s",
                updates,
                page_size=3000,
            )
        conn.commit()
        total += len(updates)

    conn.close()
    print(f"Done — {total} chunks updated.")


if __name__ == "__main__":
    run()
