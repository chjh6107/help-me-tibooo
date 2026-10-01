import re

from help_me_tibooo.models import AlertCategory, Post, ResetSourceKind, SourceName


RESET_TERMS = (
    "usage reset",
    "limits reset",
    "banked reset",
    "reset button",
    "reset will",
    "reset availability",
    "reset limit",
)
LIMIT_TERMS = ("usage limit", "rate limit", "weekly limit", "5h limit", "quota")
LAUNCH_TERMS = (
    "release", "releases", "released", "releasing",
    "launch", "launches", "launched", "launching",
    "rollout", "rollouts", "rolling out",
    "ship", "ships", "shipped", "shipping", "landing tomorrow",
)
PLAN_TERMS = ("plus", "pro", "business", "enterprise", "subscription", "subscriptions", "pricing")
NAMED_PLAN_TERMS = ("plus", "pro", "business", "enterprise")
STRONG_INCIDENT_TERMS = (
    "elevated errors",
    "degraded service",
    "investigating an issue",
    "service disruption",
)
GENERIC_INCIDENT_TERMS = ("outage", "degraded", "investigating", "incident", "recovery")
SENTENCE_CHARACTER_PATTERN = r"(?:(?<=\d)\.(?=\d)|[^.!?;])"


def classify(post: Post) -> tuple[AlertCategory, ...]:
    if post.is_repost:
        return ()
    if post.source == SourceName.RESETS:
        return (AlertCategory.RESET,)

    context_text = re.sub(
        r"https?://\S+|(?<![\w@])(?:[a-z0-9-]+\.)+[a-z]{2,}(?::\d+)?(?:[/?#]\S*)?",
        " ",
        post.text.lower(),
    )
    text = " ".join(re.sub(r"(?<!\w)@[a-z0-9_]+", " ", context_text).split())
    has_product_context = _contains_any_term(text, ("openai", "codex", "chatgpt", "astra", "devday")) or bool(
        re.search(r"(?<![a-z0-9])gpt(?:-[a-z0-9]+)?(?![a-z0-9])", text)
    ) or bool(
        re.search(r"(?<![a-z0-9_])@(?:openai|codex|chatgpt)(?![a-z0-9_])", context_text)
    )
    has_reset_context = _contains_any(text, RESET_TERMS)
    categories: set[AlertCategory] = set()

    if post.source_kind in {
        ResetSourceKind.CANDIDATE,
        ResetSourceKind.BANKED,
        ResetSourceKind.SIGNAL,
        ResetSourceKind.ANNOUNCEMENT,
    } and (
        has_reset_context or _contains_any_term(text, ("reset", "resets"))
    ):
        categories.add(AlertCategory.RESET)
    elif has_product_context and has_reset_context:
        categories.add(AlertCategory.RESET)

    if (
        post.source_kind == ResetSourceKind.LIMITS
        and (_contains_any(text, LIMIT_TERMS) or _contains_any_term(text, ("usage", "capacity", "speed", "multiplier")))
    ) or (
        has_product_context and _contains_any(text, LIMIT_TERMS)
    ):
        categories.add(AlertCategory.LIMITS)

    has_ambiguous_news_context = _contains_any_term(text, ("big", "major", "important")) and _contains_any_term(
        text, ("news", "update", "launch")
    )
    has_launch_context = _contains_any_term(text, LAUNCH_TERMS)
    if has_product_context and (has_launch_context or has_ambiguous_news_context):
        categories.add(AlertCategory.LAUNCH)

    has_named_plan_context = _contains_any_term(text, NAMED_PLAN_TERMS)
    if (
        post.source_kind is None
        and _contains_any_term(text, PLAN_TERMS)
        and (has_product_context or has_named_plan_context)
        and _has_plan_information(text)
    ):
        categories.add(AlertCategory.PLANS)

    if _contains_any(text, STRONG_INCIDENT_TERMS) or (
        has_product_context and _contains_any(text, GENERIC_INCIDENT_TERMS)
    ):
        categories.add(AlertCategory.INCIDENT)

    if has_product_context and not categories and (
        _contains_any_term(text, ("devday",)) or _has_news_information(text)
    ):
        categories.add(AlertCategory.NEWS)

    return tuple(category for category in AlertCategory if category in categories)


def _contains_any(text: str, terms: tuple[str, ...]) -> bool:
    return any(term in text for term in terms)


def _contains_any_term(text: str, terms: tuple[str, ...]) -> bool:
    return any(re.search(rf"(?<![a-z0-9]){re.escape(term)}(?![a-z0-9])", text) for term in terms)


def _has_plan_information(text: str) -> bool:
    return _has_availability_information(text) or any(re.search(pattern, text) for pattern in (
        rf"\b(?:can|will)\s+now\s+use\b{SENTENCE_CHARACTER_PATTERN}{{0,80}}\b(?:subscription|plan)\b",
        rf"\b(?:users?|subscribers?)\b{SENTENCE_CHARACTER_PATTERN}{{0,40}}\b(?:get|have|receive|keep)\b{SENTENCE_CHARACTER_PATTERN}{{0,40}}\b(?:access|usage|credits?|limits?|features?)\b",
        r"\b(?:costs?|priced at|price is|pricing is)\s+(?:now\s+)?[$€£]\s*\d",
        r"\b(?:subscriptions?|plans?)\s+(?:are|is)\s+(?:now\s+)?open(?:\s+again)?\b",
        rf"\b(?:rolling out|releasing|launching|shipping)\b{SENTENCE_CHARACTER_PATTERN}{{0,60}}\b(?:plus|pro|business|enterprise)\b",
        rf"\b(?:paus(?:e|es|ed|ing)|re[- ]?open(?:s|ed|ing)?|chang(?:e|es|ed|ing)|increas(?:e|es|ed|ing)|reduc(?:e|es|ed|ing))\b{SENTENCE_CHARACTER_PATTERN}{{0,80}}\b(?:plans?|subscriptions?|pricing|prices?|cost|access|usage|limits?|credits?|benefits?)\b",
        rf"\b(?:plans?|subscriptions?|pricing|prices?|cost|access|usage|limits?|credits?|benefits?)\b{SENTENCE_CHARACTER_PATTERN}{{0,60}}\b(?:paused|re[- ]?open(?:ed|ing)?|chang(?:e|es|ed|ing)|increas(?:e|es|ed|ing)|reduc(?:e|es|ed|ing))\b",
    ))


def _has_news_information(text: str) -> bool:
    return _has_availability_information(text) or any(re.search(pattern, text) for pattern in (
        r"\b(?:can|will)\s+now\s+(?:use|access|build|deploy|create|run|connect|host)\b",
        r"\bnow\s+(?:supports?|allows?|includes?|offers?)\b",
        rf"\b(?:improv(?:e|es|ed|ing)|increas(?:e|es|ed|ing)|reduc(?:e|es|ed|ing)|expand(?:s|ed|ing)?)\b{SENTENCE_CHARACTER_PATTERN}{{0,60}}\b(?:reliability|availability|capacity|speed|performance|access|usage|limits?|quota)\b",
        rf"\b(?:reliability|availability|capacity|speed|performance|access|usage|limits?|quota)\b{SENTENCE_CHARACTER_PATTERN}{{0,60}}\b(?:improv(?:e|es|ed|ing)|increas(?:e|es|ed|ing)|reduc(?:e|es|ed|ing)|better|faster)\b",
        r"\b(?:better|faster)\s+(?:performance|speed|reliability|availability)\b",
        r"\b(?:more|extra|additional)\s+(?:capacity|compute)\s+(?:is\s+|are\s+)?online\b",
    ))


def _has_availability_information(text: str) -> bool:
    return any(re.search(pattern, text) for pattern in (
        r"\b(?:included|available|enabled)\s+(?:in|with)\s+(?:(?:your|our|the|a)\s+)?(?:plans?|subscriptions?|codex|chatgpt)\b",
        r"\b(?:available|enabled)\s+(?:for|to)\s+(?:(?:all|paid|free|plus|pro|business|enterprise)\s+)*(?:users?|subscribers?|everyone)\b",
        r"\b(?:codex|chatgpt|astra|plus|pro)\s+(?:(?:is|are|will be)\s+)?(?:now\s+)?available(?:\s+(?:now|today|again))?(?=[.!?]|$)",
        r"\bfor everyone\b",
    ))
