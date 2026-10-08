from pmagent_backend.core import email_templates
from pmagent_backend.core.email_templates import EmailContent, render


def test_every_email_has_text_and_html_with_the_link() -> None:
    link = "http://app.test/magic-link?token=abc&x=1"
    for message in (
        email_templates.verify_email("ada@example.com", link),
        email_templates.reset_password("ada@example.com", link, 60),
        email_templates.magic_link("ada@example.com", link, 15),
        email_templates.finish_signup("grace@example.com", link, 15),
        email_templates.invite("bob@example.com", inviter="Ada", workspace="Kunemi", role="member", link=link, ttl_days=7),
    ):
        assert message.subject and message.body and message.html
        assert link in message.body  # plain text: the link as is, on its own
        assert 'href="http://app.test/magic-link?token=abc&amp;x=1"' in message.html  # escaped in HTML
        assert message.html.startswith("<!doctype html>") and "dotrix" in message.html


def test_everything_put_into_html_is_escaped() -> None:
    message = email_templates.invite(
        "bob@example.com", inviter='<script>alert("x")</script>', workspace="R&D <team>", role="member",
        link="http://app.test/invites/accept?token=t", ttl_days=7,
    )
    assert "<script>" not in message.html
    assert "&lt;script&gt;" in message.html and "R&amp;D &lt;team&gt;" in message.html
    assert "R&D <team>" in message.body  # the text part stays readable


def test_the_magic_link_email_says_when_it_expires() -> None:
    message = email_templates.magic_link("ada@example.com", "http://app.test/magic-link?token=t", 15)
    assert message.subject == "Your dotrix sign-in link"
    assert "expires in 15 minutes and works once" in message.body


def test_an_email_without_an_action() -> None:
    message = render("ada@example.com", EmailContent(subject="Hello", heading="Hi", paragraphs=["Just saying."]))
    assert "href" not in message.html and message.body.startswith("Hi\n\nJust saying.")
