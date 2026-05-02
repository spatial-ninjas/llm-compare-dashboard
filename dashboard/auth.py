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


def require_auth() -> bool:
    """Render auth gate when OIDC is configured.

    Returns True when the app should continue rendering.
    Returns False when the caller should stop.
    """
    if not is_oidc_auth_configured():
        return True

    if not st.user.is_logged_in:
        st.title("llm-compare-dashboard")
        st.info("Sign in with Google to continue.")

        if st.button("Sign in with Google"):
            st.login("google")

        return False

    email = get_signed_in_email()

    if not is_email_allowed(email):
        st.title("Access denied")
        st.error(
            f"`{email or 'This account'}` is not allowed to access this dashboard."
        )

        if st.button("Log out"):
            st.logout()

        return False

    return True


def render_auth_sidebar() -> None:
    """Render signed-in user details and logout button."""
    if not is_oidc_auth_configured():
        return

    if not st.user.is_logged_in:
        return

    with st.sidebar:
        email = get_signed_in_email()
        if email:
            st.caption(f"Signed in as `{email}`")

        if st.button("Log out"):
            st.logout()
