import pytest

from help_me_tibooo.classifier import classify
from help_me_tibooo.models import AlertCategory, Post
from help_me_tibooo.sources import parse_reset_feed


@pytest.mark.parametrize(
    ("text", "source_kind", "expected"),
    [
        ("Your Codex usage reset will land at 6pm.", "candidate", (AlertCategory.RESET,)),
        ("We are bringing back the 5h limit for Plus.", "limits", (AlertCategory.LIMITS,)),
        ("We are starting to release GPT-6 Astra.", None, (AlertCategory.LAUNCH,)),
        ("Plus users now get access at no extra cost.", None, (AlertCategory.PLANS,)),
        ("We found elevated errors and are rolling out a fix.", None, (AlertCategory.INCIDENT,)),
    ],
)
def test_classifies_important_news(make_post, text, source_kind, expected) -> None:
    assert classify(make_post(text=text, source_kind=source_kind)) == expected


def test_ignores_plain_repost(make_post) -> None:
    assert classify(make_post(text="GPT-6 launch", is_repost=True)) == ()


def test_ignores_conversational_reset_without_product_context(make_post) -> None:
    assert classify(make_post(text="Feeling reset after sleeping.")) == ()


def test_ordinary_reset_terms_with_product_context_are_classified(make_post) -> None:
    assert classify(make_post(text="Codex usage reset is tonight.")) == (AlertCategory.RESET,)


def test_ordinary_reset_terms_without_product_context_are_ignored(make_post) -> None:
    assert classify(make_post(text="My usage reset is tonight.")) == ()


def test_recall_first_rule_keeps_ambiguous_openai_shipment(make_post) -> None:
    post = make_post(text="Big Codex news is landing tomorrow.")

    assert classify(post) == (AlertCategory.LAUNCH,)


@pytest.mark.parametrize("source_kind", ("candidate", "banked", "signal"))
def test_special_reset_sources_classify_reset_context(make_post, source_kind) -> None:
    assert classify(make_post(text="Usage reset is tonight.", source_kind=source_kind)) == (AlertCategory.RESET,)


def test_special_reset_source_requires_reset_context(make_post) -> None:
    assert classify(make_post(text="Codex availability is improving.", source_kind="signal")) == (AlertCategory.NEWS,)


@pytest.mark.parametrize(
    ("text", "source_kind"),
    [
        ("Sorry Gia. More resets coming next week", "signal"),
        ("Resets all propagated. That will be all. Have a fantastic weekend.", "candidate"),
    ],
)
def test_structured_reset_signal_accepts_plural_resets(make_post, text, source_kind) -> None:
    assert classify(make_post(text=text, source_kind=source_kind)) == (AlertCategory.RESET,)


@pytest.mark.parametrize("text", ("@mark_k DevDay", "See you at DEVDAY."))
def test_devday_is_openai_news_without_a_product_name(make_post, text) -> None:
    assert classify(make_post(text=text)) == (AlertCategory.NEWS,)


@pytest.mark.parametrize(
    ("text", "source_kind"),
    [
        ("The game resets every week.", None),
        ("Presets are coming next week.", "signal"),
        ("My devdaydream was fun.", None),
    ],
)
def test_reset_and_devday_boundaries_ignore_unrelated_text(make_post, text, source_kind) -> None:
    assert classify(make_post(text=text, source_kind=source_kind)) == ()


def test_limits_source_tag_accepts_capacity_information(make_post) -> None:
    assert classify(make_post(text="New capacity details.", source_kind="limits")) == (AlertCategory.LIMITS,)


def test_ordinary_limit_terms_require_product_context(make_post) -> None:
    assert classify(make_post(text="My quota is exhausted.")) == ()


def test_does_not_match_plan_term_inside_an_unrelated_word(make_post) -> None:
    assert classify(make_post(text="OpenAI is improving reliability.")) == (AlertCategory.NEWS,)


def test_returns_multiple_categories_in_declaration_order_without_duplicates(make_post) -> None:
    post = make_post(text="OpenAI is rolling out GPT-6 Plus after elevated errors.")

    assert classify(post) == (
        AlertCategory.LAUNCH,
        AlertCategory.PLANS,
        AlertCategory.INCIDENT,
    )


def test_major_product_update_is_treated_as_launch_news(make_post) -> None:
    assert classify(make_post(text="Major OpenAI update coming soon.")) == (AlertCategory.LAUNCH,)


def test_reset_fixture_posts_are_classified_as_reset_news(load_json_fixture) -> None:
    posts = parse_reset_feed(load_json_fixture("codex_reset_feed.json"))

    assert [classify(post) for post in posts] == [
        (AlertCategory.RESET,),
        (AlertCategory.RESET,),
    ]


@pytest.mark.parametrize(
    "text",
    (
        "The reset availability at the gym was expanded.",
        "That reset limit applies to the board game too.",
    ),
)
def test_reset_announcement_phrases_need_product_or_structured_context(
    make_post,
    text,
) -> None:
    assert classify(make_post(text=text, source_kind=None)) == ()


def test_generic_access_does_not_match_plan_news(make_post) -> None:
    assert classify(make_post(text="I now have access to the venue")) == ()


def test_personal_outage_does_not_match_incident_news(make_post) -> None:
    assert classify(make_post(text="The outage at home is fixed")) == ()


@pytest.mark.parametrize(
    "text",
    (
        "Users are seeing degraded service.",
        "We are investigating an issue affecting requests.",
        "A service disruption is affecting customers.",
    ),
)
def test_strong_service_incident_phrases_do_not_need_product_name(make_post, text) -> None:
    assert classify(make_post(text=text)) == (AlertCategory.INCIDENT,)


@pytest.mark.parametrize(
    "text",
    (
        "The incident at home is over.",
        "My recovery after the race is going well.",
        "The old building looks degraded.",
    ),
)
def test_generic_incident_words_without_product_context_are_ignored(make_post, text) -> None:
    assert classify(make_post(text=text)) == ()


def test_generic_incident_word_with_product_context_is_classified(make_post) -> None:
    assert classify(make_post(text="The OpenAI outage is resolved.")) == (
        AlertCategory.INCIDENT,
    )


@pytest.mark.parametrize("plan_name", ("Plus", "Pro", "Business", "Enterprise"))
def test_named_openai_plan_is_strong_product_context(make_post, plan_name) -> None:
    assert classify(make_post(text=f"{plan_name} users now get more access.")) == (
        AlertCategory.PLANS,
    )


@pytest.mark.parametrize("is_reply", (False, True))
@pytest.mark.parametrize(
    "text",
    (
        "@imjustnewatai For the Pro 200 shenanigans",
        "@_bgian @OpenAI Thanks for playing",
        "@AbdoKerdawy @OpenAI @OpenAIDevs Agree, except with the cursing, be nice to your dot!",
        "@melvindvivas 👁️codex👁️",
        "New Pro plan!",
        "For the Pro $200 shenanigans",
        "@OpenAI Thanks for playing https://example.com/releases/plus",
        "@pro @capacity Thanks for playing",
        "OpenAI leadership is great.",
        "Thanks for playing www.openai.com/releases",
        "Thanks for playing openai.com/launch",
        "Pro 200 launch shenanigans",
        "Pro users, what should we ship next?",
        "@OpenAI I am available for a chat.",
        "Pro is available for a chat.",
        "What is ChatGPT",
        "Pro users have been great. I need access to the gym.",
        "@OpenAI Thanks for improving my mood. Access to the gym is great.",
        "I use ChatGPT. You can now access the gym.",
        "ChatGPT is fun. Tickets are available for all users.",
        "I use ChatGPT; You can now access the gym.",
        "I use GPT-6.1. You can now access the gym.",
        "I use @OpenAI. You can now access the gym.",
        "I use Pro. Tickets cost $200.",
        "Pro is fun. Gym access has expanded.",
    ),
)
def test_product_names_without_information_do_not_trigger_alerts(make_post, text, is_reply) -> None:
    assert classify(make_post(text=text, is_reply=is_reply)) == ()


@pytest.mark.parametrize(
    "text",
    (
        "@stemonteduro You main Sol? And out of curiosity, you never buy credits?",
        "@capacity Thanks for playing",
        "https://example.com/usage/ Thanks for playing",
    ),
)
def test_limits_tag_requires_operational_information(make_post, text) -> None:
    assert classify(make_post(text=text, source_kind="limits")) == ()


@pytest.mark.parametrize(
    "text",
    (
        "We are re-opening Pro $200 subscriptions tomorrow.",
        "Pro now costs $200/month.",
        "Pro subscriptions are paused.",
    ),
)
def test_limits_tag_without_limit_evidence_preserves_plan_updates(make_post, text) -> None:
    assert classify(make_post(text=text, source_kind="limits")) == (AlertCategory.PLANS,)


@pytest.mark.parametrize("source_kind", (None, "limits"))
@pytest.mark.parametrize(
    "text",
    (
        "We are expanding access for Pro users.",
        "Pro access has expanded.",
        "We expanded benefits for Plus users.",
        "Pro access expands tomorrow.",
    ),
)
def test_expanded_plan_entitlements_are_classified(make_post, text, source_kind) -> None:
    assert classify(make_post(text=text, source_kind=source_kind)) == (AlertCategory.PLANS,)


@pytest.mark.parametrize(
    ("text", "expected"),
    (
        ("@OpenAI is rolling out a new model.", (AlertCategory.LAUNCH,)),
        ("ChatGPT can now build and deploy MCP servers, and restrict their access.", (AlertCategory.NEWS,)),
        ("We are re-opening Pro $200 subscriptions tomorrow.", (AlertCategory.PLANS,)),
        ("You can now use your ChatGPT subscription in partner products.", (AlertCategory.PLANS,)),
        ("Pro subscriptions are paused.", (AlertCategory.PLANS,)),
        ("ChatGPT now supports MCP servers.", (AlertCategory.NEWS,)),
        ("Codex has more capacity online.", (AlertCategory.NEWS,)),
        ("Codex speed should get much better in the coming hours.", (AlertCategory.NEWS,)),
        ("Pro now costs $200/month.", (AlertCategory.PLANS,)),
        ("Pro price is now $200.", (AlertCategory.PLANS,)),
        ("Codex Plus subscriptions are open again.", (AlertCategory.PLANS,)),
        ("Codex available now.", (AlertCategory.NEWS,)),
        ("Codex now has faster performance.", (AlertCategory.NEWS,)),
        ("Plus users now get GPT-6.1 access.", (AlertCategory.PLANS,)),
        ("@OpenAI You can now build MCP servers.", (AlertCategory.NEWS,)),
        ("GPT-6.1 is included in your plan.", (AlertCategory.NEWS,)),
        ("I use ChatGPT. Codex has more capacity online.", (AlertCategory.NEWS,)),
        ("A Codex task will be drawing usage as usual.", (AlertCategory.NEWS,)),
    ),
)
def test_substantive_short_announcements_keep_their_category(make_post, text, expected) -> None:
    assert classify(make_post(text=text, is_reply=True)) == expected


def test_live_classification_corpus(load_json_fixture) -> None:
    corpus = load_json_fixture("notification_classification_corpus.json")
    for case in corpus["cases"]:
        post = Post(
            id=case["id"],
            text=case["text"],
            created_at=None,
            url=case["url"],
            source=case["source"],
            is_reply=case["is_reply"],
            is_repost=case["is_repost"],
            source_kind=case["source_kind"],
        )
        assert classify(post) == tuple(AlertCategory(value) for value in case["expected"]), case
