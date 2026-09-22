"""Context-aware cleanup and validation for model-generated replies."""
from dataclasses import dataclass
import json
import re


NORMAL_CHAT = 'normal_chat'
PERSONA_CHAT = 'persona_chat'
CUSTOM_GEN = 'custom_gen'
CONTEXT_TYPES = frozenset((NORMAL_CHAT, PERSONA_CHAT, CUSTOM_GEN))
DEFAULT_MAX_CHARS = 12000

_FENCED_CODE = re.compile(r'```.*?```', re.DOTALL)
_INLINE_CODE = re.compile(r'`[^`\r\n]+`')
_URL = re.compile(r'https?://[^\s<>()]+', re.IGNORECASE)
_PATH = re.compile(
    r'(?<!\w)(?:[A-Za-z]:[\\/](?:[^\s<>:"|?*\r\n]+[\\/]?)+|'
    r'/(?:[A-Za-z0-9._~+\-]+/)*[A-Za-z0-9._~+\-]+)'
)
_JSON_LINE = re.compile(r'(?m)^[ \t]*(?:\{[^\r\n]*\}|\[[^\r\n]*\])[ \t]*$')
_HEADING = re.compile(r'(?m)^[ \t]{0,3}#{1,6}[ \t]+(?=\S)')
_HASH_ONLY = re.compile(r'(?m)^[ \t]*#{3,}[ \t]*$')
_AI_SELF_REFERENCE = re.compile(
    r'(?:作为(?:一个)?(?:AI|人工智能|语言模型)|我是(?:一个)?(?:AI|人工智能|语言模型))',
    re.IGNORECASE,
)
_PREFIXES = (
    re.compile(r'^\s*作为(?:一个)?(?:AI|人工智能|语言模型)[，,:：。\s]*', re.IGNORECASE),
    re.compile(r'^\s*以下是(?:我的|我给出的)?回答[，,:：。\s]*'),
    re.compile(r'^\s*根据你的要求[，,:：。\s]*'),
    re.compile(r'^\s*当然可以[！!，,。\s]*(?:以下是(?:我的|我给出的)?回答[，,:：。\s]*)?'),
)


@dataclass(frozen=True)
class ReplyResult:
    text: str
    retry: bool = False
    reason: str | None = None


def _context(value):
    if value not in CONTEXT_TYPES:
        raise ValueError('unsupported reply context: '+str(value))
    return value


def _max_chars(value):
    if value is None:
        return DEFAULT_MAX_CHARS
    try:
        value = int(value)
    except (TypeError, ValueError):
        return DEFAULT_MAX_CHARS
    return min(100000, max(1, value))


def _protect(text):
    values = []

    def stash(value):
        token = '\ue000'+str(len(values))+'\ue001'
        values.append(value)
        return token

    text = _FENCED_CODE.sub(lambda match: stash(match.group(0)), text)

    def protect_json(match):
        candidate = match.group(0)
        try:
            json.loads(candidate.strip())
        except (TypeError, ValueError, json.JSONDecodeError):
            return candidate
        return stash(candidate)

    text = _JSON_LINE.sub(protect_json, text)
    for pattern in (_INLINE_CODE, _URL, _PATH):
        text = pattern.sub(lambda match: stash(match.group(0)), text)

    def restore(value):
        for index in range(len(values)-1, -1, -1):
            value = value.replace('\ue000'+str(index)+'\ue001', values[index])
        return value

    return text, restore


def _strip_markdown(text):
    text = re.sub(r'\*\*(?=\S)(.+?)(?<=\S)\*\*', r'\1', text)

    def emphasis(match):
        inner = match.group(1)
        if re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*', inner):
            return match.group(0)
        return inner

    text = re.sub(r'__(?=\S)(.+?)(?<=\S)__', emphasis, text)
    text = _HEADING.sub('', text)
    return _HASH_ONLY.sub('', text)


def _remove_template_prefixes(text):
    previous = None
    while text != previous:
        previous = text
        for pattern in _PREFIXES:
            text = pattern.sub('', text, count=1)
    return text


def _dedupe_sentences(text):
    output_lines = []
    previous_line = None
    for line in text.splitlines():
        parts = re.findall(r'.+?(?:[。！？!?]+|$)', line)
        kept = []
        previous = None
        for part in parts:
            normalized = part.strip()
            if normalized and normalized == previous:
                continue
            kept.append(part)
            if normalized:
                previous = normalized
        cleaned = ''.join(kept).rstrip()
        normalized_line = cleaned.strip()
        if normalized_line and normalized_line == previous_line:
            continue
        output_lines.append(cleaned)
        previous_line = normalized_line or None
    return '\n'.join(output_lines)


def _safe_truncate(text, limit, tail=None):
    if len(text) <= limit:
        return text, False
    cut = limit
    window = text[:cut]
    boundaries = [window.rfind(mark) for mark in ('\n', '。', '！', '？', '!', '?')]
    boundary = max(boundaries)
    if boundary >= int(limit*0.6):
        cut = boundary+1
    for pattern in (_FENCED_CODE, _INLINE_CODE, _URL, _PATH):
        for match in pattern.finditer(text):
            if match.start() < cut < match.end():
                cut = match.start() if match.start() >= int(limit*0.5) else match.end()
                break
    shortened = text[:cut].rstrip()
    if tail and shortened and not shortened.endswith(tail):
        shortened = shortened[:max(0, limit - len(tail))].rstrip() + tail
    return shortened, True


def clean_reply(text, context_type=NORMAL_CHAT):
    """Clean model text without changing protected code, URLs, paths or JSON lines."""
    context_type = _context(context_type)
    value = str(text or '').replace('\r\n', '\n').replace('\r', '\n')
    value, restore = _protect(value)
    value = _strip_markdown(value)
    if context_type in (NORMAL_CHAT, PERSONA_CHAT):
        value = _remove_template_prefixes(value)
    value = re.sub(r'[ \t]+$', '', value, flags=re.MULTILINE)
    value = re.sub(r'\n[ \t]*\n(?:[ \t]*\n)+', '\n\n', value)
    value = _dedupe_sentences(value)
    return restore(value).strip()


def validate_reply(text, context_type=NORMAL_CHAT, ooc_check=None):
    """Return the retry decision and reason for unmodified model text."""
    context_type = _context(context_type)
    value = str(text or '')
    if not value.strip():
        return context_type == PERSONA_CHAT, 'empty_reply'
    if context_type == PERSONA_CHAT and ooc_check is not None and ooc_check(value):
        return True, 'persona_ooc'
    if context_type in (NORMAL_CHAT, PERSONA_CHAT) and _AI_SELF_REFERENCE.search(value):
        return context_type == PERSONA_CHAT, 'ai_self_reference'
    if context_type in (NORMAL_CHAT, PERSONA_CHAT) and any(pattern.search(value) for pattern in _PREFIXES[1:]):
        return False, 'template_prefix'
    return False, None


def process_reply(text, context_type=NORMAL_CHAT, max_chars=None, ooc_check=None, tail=None):
    """Clean, validate and length-bound one model-generated reply."""
    context_type = _context(context_type)
    retry, reason = validate_reply(text, context_type, ooc_check=ooc_check)
    cleaned = clean_reply(text, context_type)
    if not cleaned and not retry:
        cleaned = str(text or '').strip()
        reason = reason or 'empty_after_cleanup'
    cleaned, truncated = _safe_truncate(cleaned, _max_chars(max_chars), tail)
    if truncated:
        reason = reason or 'max_length'
    return ReplyResult(cleaned, retry, reason)
