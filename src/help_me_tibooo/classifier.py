import re

from help_me_tibooo.models import AlertCategory, Post, ResetSourceKind


PRODUCT_TERMS = ("openai", "codex", "chatgpt", "gpt-", "astra")
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
LAUNCH_TERMS = ("release", "launch", "rollout", "rolling out", "ship", "landing tomorrow")
PLAN_TERMS = ("plus", "pro", "business", "enterprise", "subscription", "pricing", "access")
NAMED_PLAN_TERMS = ("plus", "pro", "business", "enterprise")
INCIDENT_TERMS = ("outage", "degraded", "elevated errors", "investigating", "incident", "recovery")


def classify(post: Post) -> tuple[AlertCategory, ...]:
    if post.is_repost:
        return ()

    text = post.text.lower()
    has_product_context = _contains_any(text, PRODUCT_TERMS)
    has_reset_context = _contains_any(text, RESET_TERMS)
    categories: set[AlertCategory] = set()

    if post.source_kind in {
        ResetSourceKind.CANDIDATE,
        ResetSourceKind.BANKED,
        ResetSourceKind.SIGNAL,
        ResetSourceKind.ANNOUNCEMENT,
    } and (
        has_reset_context or _contains_any_term(text, ("reset",))
    ):
        categories.add(AlertCategory.RESET)
    elif has_product_context and has_reset_context:
        categories.add(AlertCategory.RESET)

    if post.source_kind == ResetSourceKind.LIMITS or (
        has_product_context and _contains_any(text, LIMIT_TERMS)
    ):
        categories.add(AlertCategory.LIMITS)

    has_ambiguous_news_context = _contains_any(text, ("big", "major", "important")) and _contains_any(
        text, ("news", "update", "launch")
    )
    if has_product_context and (_contains_any(text, LAUNCH_TERMS) or has_ambiguous_news_context):
        categories.add(AlertCategory.LAUNCH)

    has_named_plan_context = _contains_any_term(text, NAMED_PLAN_TERMS)
    if (
        post.source_kind is None
        and _contains_any_term(text, PLAN_TERMS)
        and (has_product_context or has_named_plan_context)
    ):
        categories.add(AlertCategory.PLANS)

    if has_product_context and _contains_any(text, INCIDENT_TERMS):
        categories.add(AlertCategory.INCIDENT)

    return tuple(category for category in AlertCategory if category in categories)


def _contains_any(text: str, terms: tuple[str, ...]) -> bool:
    return any(term in text for term in terms)


def _contains_any_term(text: str, terms: tuple[str, ...]) -> bool:
    return any(re.search(rf"(?<![a-z0-9]){re.escape(term)}(?![a-z0-9])", text) for term in terms)
