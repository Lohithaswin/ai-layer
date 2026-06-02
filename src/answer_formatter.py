"""Format and clean LLM answers for enterprise manual RAG."""

from __future__ import annotations

import re
from difflib import SequenceMatcher


def _normalize_for_dedupe(text: str) -> str:
    """
    Normalize text for semantic comparison.
    """

    text = re.sub(r'\[\d+\]', '', text)

    text = re.sub(r'[`*_"\']', '', text)

    text = re.sub(r'\s+', ' ', text.lower()).strip()

    text = re.sub(r'[^\w\s]', '', text)

    return text.strip()


def _semantic_similarity(a: str, b: str) -> float:
    """
    Semantic similarity using normalized text.
    """

    return SequenceMatcher(
        None,
        _normalize_for_dedupe(a),
        _normalize_for_dedupe(b),
    ).ratio()


def _remove_inline_citations(text: str) -> str:
    """
    Remove inline [1], [2] citations.
    """

    text = re.sub(
        r'\s*\[\d+\]',
        '',
        text,
    )

    text = re.sub(
        r'\s*\[\d+\s*$',
        '',
        text,
        flags=re.M,
    )

    return text


def _remove_standalone_citations(text: str) -> str:
    """
    Remove citation-only lines.
    """

    lines = []

    previous_idx = None

    for raw in text.split('\n'):

        stripped = raw.strip()

        if re.fullmatch(
            r'(?:\[\d+\]\s*)+',
            stripped,
        ):

            if (
                previous_idx is not None
                and not lines[previous_idx]
                .rstrip()
                .endswith(stripped)
            ):
                lines[previous_idx] = (
                    lines[previous_idx].rstrip()
                    + f' {stripped}'
                )

            continue

        lines.append(raw)

        if stripped:
            previous_idx = len(lines) - 1

    return '\n'.join(lines)


def _remove_copied_source_headers(text: str) -> str:
    """
    Remove copied retrieval/source headers.
    """

    cleaned = []

    source_line = re.compile(
        r'^\s*\[\d+\]\s+.+?\.pdf\s+\(page\s+\d+\)\s*$',
        re.I,
    )

    reference_line = re.compile(
        r'^\s*(references?|source(?:s)?):\s*.*$',
        re.I,
    )

    page_claim = re.compile(
        r'.*\b('
        r'according to|mentioned in|'
        r'refer(?:red)? to|source(?:s)?|'
        r'manual|guide|pdf|document'
        r')\b.*\bpage\s+\d+\b.*',
        re.I,
    )

    doc_title = re.compile(
        r'^\s*(?:PROJECT_MODULE|PROJECT_NAME)\s+'
        r'(?:-|Installation|Security|Web UI|'
        r'User Manual|Installation Guide).*$',
        re.I,
    )

    for line in text.split('\n'):

        stripped = line.strip()

        if source_line.match(stripped):
            continue

        if reference_line.match(stripped):
            continue

        if page_claim.match(stripped):
            continue

        if doc_title.match(stripped):
            continue

        cleaned.append(line)

    return '\n'.join(cleaned)


def _clean_figure_references(text: str) -> str:
    """
    Remove useless PDF figure, screenshot, and diagram references completely.
    """
    # Replace references followed by punctuation (like dot, comma, or end of line)
    text = re.sub(r'\s*(?:as )?shown in (?:the )?(?:following |below )?(?:figure|screenshot|diagram)\b\.?', '.', text, flags=re.I)
    text = re.sub(r'\s*refer to (?:the )?(?:following |below )?(?:figure|screenshot|diagram)\b\.?', '.', text, flags=re.I)
    text = re.sub(r'\s*see (?:the )?(?:following |below )?(?:figure|screenshot|diagram)\b\.?', '.', text, flags=re.I)
    
    # Replace references in the middle of a sentence
    text = re.sub(r'\s*(?:as )?shown in (?:the )?(?:following |below )?(?:figure|screenshot|diagram)\b', '', text, flags=re.I)
    text = re.sub(r'\s*refer to (?:the )?(?:following |below )?(?:figure|screenshot|diagram)\b', '', text, flags=re.I)
    
    # Fix double dots that might have been introduced
    text = text.replace('..', '.')
    return text


def _deduplicate_bullet_points(text: str) -> str:
    """
    Remove duplicate bullets.
    """

    lines = text.split('\n')

    seen = set()

    result = []

    for line in lines:

        stripped = line.strip()

        if (
            stripped.startswith('•')
            or stripped.startswith('-')
            or stripped.startswith('*')
        ):

            normalized = _normalize_for_dedupe(
                re.sub(
                    r'^[•\-*]\s+',
                    '',
                    stripped,
                )
            )

            duplicate = False

            for old in seen:

                if _semantic_similarity(
                    normalized,
                    old,
                ) > 0.90:
                    duplicate = True
                    break

            if duplicate:
                continue

            seen.add(normalized)

        result.append(line)

    return '\n'.join(result)


def _deduplicate_paragraphs(text: str) -> str:
    """
    Remove repeated paragraphs.
    """

    blocks = re.split(r'\n\s*\n', text)

    seen = []

    result = []

    for block in blocks:

        normalized = _normalize_for_dedupe(block)

        if not normalized:
            continue

        duplicate = False

        for old in seen:

            if _semantic_similarity(
                normalized,
                old,
            ) > 0.90:
                duplicate = True
                break

        if duplicate:
            continue

        seen.append(normalized)

        result.append(block.strip())

    return '\n\n'.join(result)


def _deduplicate_sentences(text: str) -> str:
    """
    Remove repeated prose sentences.
    """

    lines = []

    seen = []

    for line in text.split('\n'):

        stripped = line.strip()

        if not stripped:
            lines.append(line)
            continue

        # preserve procedural steps
        if re.match(r'^\d+[.)]\s+', stripped):
            lines.append(line)
            continue

        # preserve table/config rows
        if (
            "|" in stripped
            or "=" in stripped
            or ":" in stripped[:40]
        ):
            lines.append(line)
            continue

        pieces = re.split(
            r'(?<=[.!?])\s+',
            stripped,
        )

        unique_pieces = []

        for piece in pieces:

            normalized = _normalize_for_dedupe(piece)

            if not normalized:
                continue

            duplicate = False

            for old in seen:

                if _semantic_similarity(
                    normalized,
                    old,
                ) > 0.92:
                    duplicate = True
                    break

            if duplicate:
                continue

            seen.append(normalized)

            unique_pieces.append(piece)

        if unique_pieces:
            lines.append(
                ' '.join(unique_pieces)
            )

    return '\n'.join(lines)


def _remove_duplicate_step_sequences(text: str) -> str:
    """
    Remove repeated numbered procedural steps.
    """

    lines = text.split('\n')

    seen_steps = []

    result = []

    for line in lines:

        match = re.match(
            r'^(\s*\d+[.)]\s+)(.+)$',
            line,
        )

        if not match:
            result.append(line)
            continue

        content = match.group(2)

        normalized = _normalize_for_dedupe(content)

        duplicate = False

        for old in seen_steps:

            if _semantic_similarity(
                normalized,
                old,
            ) > 0.90:
                duplicate = True
                break

        if duplicate:
            continue

        seen_steps.append(normalized)

        result.append(line)

    return '\n'.join(result)


def _remove_redundant_step_intros(text: str) -> str:
    """
    Remove duplicated procedural-intro filler.
    """

    lines = text.split('\n')

    result = []

    saw_action = False

    for line in lines:

        stripped = line.strip()

        if (
            re.match(
                r'^\d+[.)]\s+',
                stripped,
            )
            or re.match(
                r'^(open|set|save|select|enter|'
                r'click|restart|modify|change)\b',
                stripped,
                re.I,
            )
        ):
            saw_action = True

        if (
            saw_action
            and len(stripped) < 120
            and re.search(
                r'\b('
                r'can be configured|'
                r'as explained|'
                r'following steps|'
                r'follow these steps'
                r')\b',
                stripped,
                re.I,
            )
        ):
            continue

        result.append(line)

    return '\n'.join(result)


def _clean_leaked_source_headers(text: str) -> str:
    """
    Replace leaked source headers like '[1] PROJECT_MODULE_User Manual.pdf (page 31)' 
    with just the clean inline citation '[1]'.
    """
    # Match [1] followed by a PDF filename (optional spaces, path, extension) and (page X)
    pattern = r'(\[\d+\])\s+[A-Za-z0-9_\-\s\(\)]+\.pdf\s+\(page\s+\d+\)'
    text = re.sub(pattern, r'\1', text, flags=re.I)
    
    # Also handle references without .pdf if they have the page suffix
    pattern2 = r'(\[\d+\])\s+[A-Za-z0-9_\-\s\(\)]+\s+\(page\s+\d+\)'
    text = re.sub(pattern2, r'\1', text, flags=re.I)
    
    return text

def clean_procedural_answer(answer: str) -> str:
    """
    Final enterprise-grade answer cleanup pipeline.
    """

    if not answer:
        return answer

    answer = answer.replace('\r\n', '\n')

    # remove copied retrieval/source text and leaked headers first so duplicates match exactly
    answer = _remove_copied_source_headers(answer)
    answer = _clean_leaked_source_headers(answer)

    # figure cleanup
    answer = _clean_figure_references(answer)

    # dedupe pipeline
    answer = _deduplicate_bullet_points(answer)
    answer = _deduplicate_paragraphs(answer)
    answer = _deduplicate_sentences(answer)
    answer = _remove_duplicate_step_sequences(answer)
    answer = _remove_redundant_step_intros(answer)

    # citation cleanup (ensure standalone citations are appended, but do not strip inline ones)
    answer = _remove_standalone_citations(answer)

    # whitespace cleanup
    answer = re.sub(
        r'\n{3,}',
        '\n\n',
        answer,
    )

    answer = re.sub(
        r'[ \t]+',
        ' ',
        answer,
    )

    return answer.strip()