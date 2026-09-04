import pytest

from help_me_tibooo.classifier import classify
from help_me_tibooo.models import AlertCategory
from help_me_tibooo.sources import parse_reset_feed


@pytest.mark.parametrize(
    ("text", "source_kind", "expected"),
    [
        ("Your Codex usage reset will land at 6pm.", "candidate", (AlertCategory.RESET,)),
        ("We are bringing back the 5h limit for Plus.", "limits", (AlertCategory.LIMITS,)),
        ("We are starting to release GPT-6 Astra.", None, (AlertCategory.LAUNCH,)),
        ("Plus users now get access at no extra cost.", None, (AlertCategory.PLANS,)),
        ("OpenAI found elevated errors and is mitigating the issue.", None, (AlertCategory.INCIDENT,)),
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
    assert classify(make_post(text="Codex availability is improving.", source_kind="signal")) == ()


def test_limits_source_kind_is_classified_without_limit_wording(make_post) -> None:
    assert classify(make_post(text="New capacity details.", source_kind="limits")) == (AlertCategory.LIMITS,)


def test_ordinary_limit_terms_require_product_context(make_post) -> None:
    assert classify(make_post(text="My quota is exhausted.")) == ()


def test_does_not_match_plan_term_inside_an_unrelated_word(make_post) -> None:
    assert classify(make_post(text="OpenAI is improving reliability.")) == ()


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


@pytest.mark.parametrize("plan_name", ("Plus", "Pro", "Business", "Enterprise"))
def test_named_openai_plan_is_strong_product_context(make_post, plan_name) -> None:
    assert classify(make_post(text=f"{plan_name} users now get more access.")) == (
        AlertCategory.PLANS,
    )
