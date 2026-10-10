"""Email templates: every email dotrix sends, in one layout, as HTML and plain text.

An email is a heading, a few short paragraphs, one action (a button, with its link also
written out for clients that block buttons), and a footer note. Everything put into the
HTML is escaped here, so callers pass plain text (names, workspace names, links).

The layout uses tables and inline styles only: that's what email clients render reliably
(no external CSS, no web fonts, no images).
"""
from __future__ import annotations

import html
from dataclasses import dataclass, field

from .email import EmailMessage

PRODUCT = "dotrix"
BRAND = "#155dfc"  # the app's brand colour (--brand, light theme)


@dataclass(frozen=True)
class EmailContent:
    subject: str
    heading: str
    paragraphs: list[str] = field(default_factory=list)
    action_label: str | None = None
    action_url: str | None = None
    note: str | None = None  # small print under the action: expiry, "ignore this if…"


def render(to: str, content: EmailContent) -> EmailMessage:
    return EmailMessage(to=to, subject=content.subject, body=_text(content), html=_html(content))


def _text(content: EmailContent) -> str:
    parts = [content.heading, *content.paragraphs]
    if content.action_url:
        parts.append(f"{content.action_label}: {content.action_url}")
    if content.note:
        parts.append(content.note)
    parts.append(f"— {PRODUCT}")
    return "\n\n".join(parts)


def _html(content: EmailContent) -> str:
    e = html.escape
    paragraphs = "".join(
        f'<p style="margin:0 0 16px;font-size:15px;line-height:1.6;color:#27272a">{e(p)}</p>'
        for p in content.paragraphs
    )
    action = ""
    if content.action_url and content.action_label:
        url = e(content.action_url, quote=True)
        action = (
            '<table role="presentation" cellspacing="0" cellpadding="0" style="margin:8px 0 20px">'
            f'<tr><td style="border-radius:8px;background:{BRAND}">'
            f'<a href="{url}" style="display:inline-block;padding:12px 20px;font-size:15px;font-weight:600;'
            f'color:#ffffff;text-decoration:none;border-radius:8px">{e(content.action_label)}</a>'
            "</td></tr></table>"
            '<p style="margin:0 0 16px;font-size:13px;line-height:1.5;color:#71717a">'
            f'Or copy this link into your browser:<br><a href="{url}" style="color:{BRAND};word-break:break-all">{url}</a></p>'
        )
    note = (
        f'<p style="margin:0;font-size:13px;line-height:1.5;color:#71717a">{e(content.note)}</p>' if content.note else ""
    )
    return (
        "<!doctype html>"
        '<html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
        f"<title>{e(content.subject)}</title></head>"
        '<body style="margin:0;padding:0;background:#f4f4f5">'
        '<table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="background:#f4f4f5">'
        '<tr><td align="center" style="padding:32px 16px">'
        '<table role="presentation" width="100%" cellspacing="0" cellpadding="0" '
        'style="max-width:520px;background:#ffffff;border-radius:12px;border:1px solid #e4e4e7">'
        '<tr><td style="padding:28px 32px 8px;font-family:-apple-system,BlinkMacSystemFont,Segoe UI,Roboto,Helvetica,Arial,sans-serif">'
        f'<p style="margin:0 0 24px;font-size:14px;font-weight:700;color:{BRAND};letter-spacing:.2px">{PRODUCT}</p>'
        f'<h1 style="margin:0 0 16px;font-size:20px;line-height:1.3;color:#18181b">{e(content.heading)}</h1>'
        f"{paragraphs}{action}{note}"
        "</td></tr>"
        '<tr><td style="padding:16px 32px 28px;font-family:-apple-system,BlinkMacSystemFont,Segoe UI,Roboto,Helvetica,Arial,sans-serif">'
        f'<p style="margin:0;font-size:12px;color:#a1a1aa">Sent by {PRODUCT}. You get this email because of '
        "your account or an invitation.</p>"
        "</td></tr></table></td></tr></table></body></html>"
    )


# -- the emails ---------------------------------------------------------------------------


def verify_email(to: str, link: str) -> EmailMessage:
    return render(to, EmailContent(
        subject=f"Verify your {PRODUCT} email",
        heading="Confirm your email address",
        paragraphs=["Confirm this address to finish setting up your account."],
        action_label="Verify email",
        action_url=link,
        note="If you didn't create an account, you can ignore this email.",
    ))


def reset_password(to: str, link: str, ttl_minutes: int) -> EmailMessage:
    return render(to, EmailContent(
        subject=f"Reset your {PRODUCT} password",
        heading="Reset your password",
        paragraphs=["Someone (hopefully you) asked to reset the password for this account."],
        action_label="Choose a new password",
        action_url=link,
        note=f"This link expires in {ttl_minutes} minutes and works once. "
        "If you didn't ask for this, you can ignore this email: your password stays the same.",
    ))


def magic_link(to: str, link: str, ttl_minutes: int) -> EmailMessage:
    return render(to, EmailContent(
        subject=f"Your {PRODUCT} sign-in link",
        heading=f"Sign in to {PRODUCT}",
        paragraphs=["Use the button below to sign in. No password needed."],
        action_label="Sign in",
        action_url=link,
        note=f"This link expires in {ttl_minutes} minutes and works once. "
        "If you didn't ask to sign in, you can ignore this email.",
    ))


def finish_signup(to: str, link: str, ttl_minutes: int) -> EmailMessage:
    """For someone who asked for a sign-in link but has no account yet."""
    return render(to, EmailContent(
        subject=f"Finish creating your {PRODUCT} account",
        heading=f"Welcome to {PRODUCT}",
        paragraphs=[
            "There's no account for this address yet. Use the button below to create one: "
            "you'll just add your name. No password needed."
        ],
        action_label="Create my account",
        action_url=link,
        note=f"This link expires in {ttl_minutes} minutes and works once. "
        "If you didn't ask for this, you can ignore this email: no account is created.",
    ))


def invite(to: str, *, inviter: str, workspace: str, role: str, link: str, ttl_days: int) -> EmailMessage:
    return render(to, EmailContent(
        subject=f"{inviter} invited you to {workspace} on {PRODUCT}",
        heading=f"Join {workspace}",
        paragraphs=[f"{inviter} invited you to join {workspace} as {role}."],
        action_label="Accept the invite",
        action_url=link,
        note=f"This invite expires in {ttl_days} days and only works for {to}.",
    ))
