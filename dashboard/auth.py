"""Authentication helpers for the dashboard."""

from __future__ import annotations

import os

import streamlit as st


def get_allowed_emails() -> set[str]:
    """Return lowercased email allowlist from AUTH_ALLOWED_EMAILS."""
    raw_value = os.getenv("AUTH_ALLOWED_EMAILS", "")

    return {
        email.strip().lower()
        for email in raw_value.split(",")
        if email.strip()
    }


def is_oidc_auth_configured() -> bool:
    """Return whether Streamlit OIDC auth appears to be configured."""
    try:
        return "auth" in st.secrets
    except Exception:
        return False


def get_signed_in_email() -> str | None:
    """Return the signed-in user's normalized email, if available."""
    if not getattr(st.user, "is_logged_in", False):
        return None

    email = st.user.get("email")
    if not email:
        return None

    return str(email).strip().lower()


def is_email_allowed(email: str | None) -> bool:
    """Return whether an email is allowed by AUTH_ALLOWED_EMAILS."""
    allowed_emails = get_allowed_emails()

    if not allowed_emails:
        return True

    if email is None:
        return False

    return email.strip().lower() in allowed_emails
