"""
sb_auth.py — Supabase auth for Streamlit (fully native)

All database operations use the Supabase REST API with the user's
access token for RLS compliance, or the service key for operations
that need to bypass RLS.
"""

import streamlit as st
import requests
import secrets
import hashlib
import base64
import urllib.parse
import json
import os
import tempfile
from supabase import create_client, Client


# ─── Supabase client ────────────────────────────────────────────────


def init_supabase() -> Client:
    if "_supabase_client" not in st.session_state:
        url = st.secrets["supabase"]["url"]
        key = st.secrets["supabase"]["key"]
        st.session_state["_supabase_client"] = create_client(url, key)
    return st.session_state["_supabase_client"]


def _auth_headers() -> dict:
    """Get headers with the user's access token for authenticated REST calls."""
    key = st.secrets["supabase"]["key"]
    token = st.session_state.get("_supabase_access_token", "")
    headers = {
        "apikey": key,
        "Content-Type": "application/json",
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"
    else:
        headers["Authorization"] = f"Bearer {key}"
    return headers


def _rest_url() -> str:
    return st.secrets["supabase"]["url"] + "/rest/v1"


# ─── PKCE helpers with file persistence ──────────────────────────────

_VERIFIER_FILE = os.path.join(tempfile.gettempdir(), "segment_app_pkce_verifier.json")


def _generate_pkce_pair():
    verifier = secrets.token_urlsafe(32)
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
    return verifier, challenge


def _save_verifier(verifier: str):
    st.session_state["_pkce_verifier"] = verifier
    try:
        with open(_VERIFIER_FILE, "w") as f:
            json.dump({"verifier": verifier}, f)
    except Exception:
        pass


def _load_verifier() -> str:
    v = st.session_state.get("_pkce_verifier")
    if v:
        return v
    try:
        with open(_VERIFIER_FILE, "r") as f:
            data = json.load(f)
            v = data.get("verifier", "")
            if v:
                st.session_state["_pkce_verifier"] = v
            return v
    except Exception:
        return ""


def _clear_verifier():
    st.session_state.pop("_pkce_verifier", None)
    st.session_state.pop("_pkce_auth_url", None)
    try:
        os.remove(_VERIFIER_FILE)
    except Exception:
        pass


def _build_google_auth_url():
    url = st.secrets["supabase"]["url"]
    # Reuse the existing verifier if we already have one stored. Regenerating
    # on every render causes a race: Streamlit can re-render login_ui() during
    # the OAuth round-trip, overwriting the verifier that matches Google's
    # outstanding code with a new one. Result at callback time:
    #   "code challenge does not match previously saved code verifier"
    # Keeping the verifier stable across renders avoids that.
    existing = _load_verifier()
    import logging as _l_auth

    if existing:
        verifier = existing
        # Re-derive the challenge from the verifier (deterministic SHA-256).
        digest = hashlib.sha256(verifier.encode("ascii")).digest()
        challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
        _l_auth.warning(
            f"[PKCE] AuthURL (reuse): verifier prefix={verifier[:8]}..., "
            f"challenge={challenge[:16]}..."
        )
    else:
        verifier, challenge = _generate_pkce_pair()
        _save_verifier(verifier)
        _l_auth.warning(
            f"[PKCE] AuthURL (new): verifier prefix={verifier[:8]}..., "
            f"challenge={challenge[:16]}..."
        )
    redirect_url = _get_redirect_url()
    params = {
        "provider": "google",
        "redirect_to": redirect_url,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
        # Force Google to show its account picker directly instead of bouncing
        # through the accountchooser intermediate page. On some hosting configs
        # (including Streamlit Cloud), accountchooser returns 403 for reasons
        # that are opaque; prompt=select_account sidesteps it entirely.
        "prompt": "select_account",
    }
    return f"{url}/auth/v1/authorize?{urllib.parse.urlencode(params)}"


def _get_redirect_url() -> str:
    try:
        from streamlit import context as _ctx

        _headers = _ctx.headers
        host = _headers.get("Host", "localhost:8501")

        # X-Forwarded-Proto is unreliable on Streamlit Cloud. Force https for
        # anything that isn't localhost; only use http for local dev.
        if host.startswith("localhost") or host.startswith("127.0.0.1"):
            proto = "http"
        else:
            proto = _headers.get("X-Forwarded-Proto", "https")

        return f"{proto}://{host}/"
    except Exception:
        return "http://localhost:8501/"


def _exchange_code(code: str) -> dict:
    url = st.secrets["supabase"]["url"]
    key = st.secrets["supabase"]["key"]
    verifier = _load_verifier()
    if not verifier:
        raise Exception("No code verifier found")
    # Diagnostic: log the challenge derived from our verifier so we can
    # compare against what was sent in the authorize URL. Use logging.warning
    # so output appears in Streamlit Cloud's stderr-based log stream (print()
    # to stdout may be filtered by the platform).
    import hashlib as _h, base64 as _b, logging as _l

    _digest = _h.sha256(verifier.encode("ascii")).digest()
    _challenge = _b.urlsafe_b64encode(_digest).rstrip(b"=").decode("ascii")
    _l.warning(
        f"[PKCE] Exchange: verifier prefix={verifier[:8]}..., "
        f"challenge={_challenge[:16]}..., code prefix={code[:8]}..."
    )
    resp = requests.post(
        f"{url}/auth/v1/token?grant_type=pkce",
        json={"auth_code": code, "code_verifier": verifier},
        headers={"apikey": key, "Content-Type": "application/json"},
    )
    _l.warning(
        f"[PKCE] Exchange response: status={resp.status_code}, "
        f"body_prefix={resp.text[:120] if resp.text else '(empty)'}"
    )
    if resp.status_code == 200:
        return resp.json()
    raise Exception(f"Token exchange failed ({resp.status_code}): {resp.text}")


# ─── User wrapper ───────────────────────────────────────────────────


class _UserWrapper:
    def __init__(self, data):
        self.id = data.get("id", "")
        self.email = data.get("email", "")
        self.user_metadata = data.get("user_metadata", {})


def _wrap_user(data: dict):
    return _UserWrapper(data)


# ─── Auth UI ────────────────────────────────────────────────────────


def login_ui(sb: Client):
    url = st.secrets["supabase"]["url"]
    key = st.secrets["supabase"]["key"]

    # ── Handle OAuth callback ──
    if "code" in st.query_params:
        code = st.query_params["code"]
        st.query_params.clear()
        try:
            token_data = _exchange_code(code)
            user = token_data.get("user", {})
            if user:
                st.session_state["_supabase_user"] = user
                st.session_state["_supabase_access_token"] = token_data.get(
                    "access_token", ""
                )
                _clear_verifier()
                st.rerun()
        except Exception as e:
            st.sidebar.error(f"Sign-in failed: {e}")
            _clear_verifier()
        return None

    # ── Already signed in? ──
    if "_supabase_user" in st.session_state:
        return _wrap_user(st.session_state["_supabase_user"])

    # ── Google sign-in button ──
    # Reuse the existing verifier/URL across renders (see _build_google_auth_url
    # comment). On success, _clear_verifier() below wipes the verifier so the
    # next sign-in starts fresh; on exchange failure, the verifier is also
    # cleared so a retry regenerates.
    auth_url = _build_google_auth_url()

    # Inject CSS that styles the Google sign-in link_button to match Google's
    # official dark-button branding. Multiple selectors provide robustness
    # against Streamlit DOM changes: st-key-* class (Streamlit 1.38+), plus
    # the legacy href-based and data-testid-based selectors as fallbacks.
    # All three target the same <a> tag — whichever one matches wins.
    st.markdown(
        """
        <style>
        /* Target 1: Streamlit 1.38+ container key class */
        .st-key-gsi-signin a,
        /* Target 2: href fragment match (href-stable) */
        a[href*="/auth/v1/authorize"],
        /* Target 3: legacy data-testid */
        div[data-testid="stLinkButton"] a[href*="provider=google"] {
            background: #131314 !important;
            color: #ffffff !important;
            border: 1px solid #8e918f !important;
            font-family: 'Roboto', 'Helvetica Neue', Arial, sans-serif !important;
            font-weight: 500 !important;
            font-size: 14px !important;
            padding: 10px 16px !important;
            border-radius: 8px !important;
            transition: background 0.15s, box-shadow 0.15s, border-color 0.15s;
            display: flex !important;
            align-items: center !important;
            justify-content: center !important;
            gap: 10px !important;
            text-decoration: none !important;
        }
        .st-key-gsi-signin a:hover,
        a[href*="/auth/v1/authorize"]:hover,
        div[data-testid="stLinkButton"] a[href*="provider=google"]:hover {
            background: #2a2a2c !important;
            border-color: #ffffff40 !important;
            box-shadow: 0 1px 2px rgba(0,0,0,0.3),
                        0 1px 3px 1px rgba(0,0,0,0.15) !important;
        }
        /* Hide Streamlit's default arrow icon inside the link button */
        .st-key-gsi-signin a svg,
        a[href*="/auth/v1/authorize"] svg,
        div[data-testid="stLinkButton"] a[href*="provider=google"] svg {
            display: none !important;
        }
        /* Insert Google G logo via pseudo-element background image */
        .st-key-gsi-signin a > div::before,
        a[href*="/auth/v1/authorize"] > div::before,
        div[data-testid="stLinkButton"] a[href*="provider=google"] > div::before {
            content: "";
            display: inline-block;
            width: 18px;
            height: 18px;
            margin-right: 2px;
            background-image: url("https://www.gstatic.com/firebasejs/ui/2.0.0/images/auth/google.svg");
            background-size: contain;
            background-repeat: no-repeat;
            vertical-align: middle;
            flex-shrink: 0;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )

    # Keyed container so CSS can target this specific link_button. Falls back
    # gracefully on older Streamlit versions via the href-based selectors above.
    # st.link_button navigates via <a> inside Streamlit's main iframe (which
    # has allow-top-navigation-by-user-activation set), giving reliable click
    # behavior — unlike components.v1.html iframes which have stricter sandbox.
    with st.container(key="gsi-signin"):
        st.link_button(
            "Sign in with Google",
            auth_url,
            use_container_width=True,
        )

    # ── Email sign-in ──
    with st.expander("Or sign in with email", expanded=False):
        tab_login, tab_signup = st.tabs(["Sign in", "Create account"])
        with tab_login:
            email = st.text_input(
                "Email", key="_login_email", placeholder="you@example.com"
            )
            password = st.text_input("Password", type="password", key="_login_password")
            if st.button(
                "Sign in", key="_login_btn", type="primary", use_container_width=True
            ):
                if email and password:
                    _email_sign_in(url, key, email, password)
                else:
                    st.warning("Enter email and password")
        with tab_signup:
            new_email = st.text_input(
                "Email", key="_signup_email", placeholder="you@example.com"
            )
            new_password = st.text_input(
                "Password", type="password", key="_signup_password"
            )
            confirm = st.text_input(
                "Confirm password", type="password", key="_signup_confirm"
            )
            if st.button(
                "Create account",
                key="_signup_btn",
                type="primary",
                use_container_width=True,
            ):
                if not new_email or not new_password:
                    st.warning("Enter email and password")
                elif new_password != confirm:
                    st.warning("Passwords don't match")
                elif len(new_password) < 6:
                    st.warning("Password must be at least 6 characters")
                else:
                    _email_sign_up(url, key, new_email, new_password)

    return None


def _email_sign_in(url: str, key: str, email: str, password: str):
    try:
        resp = requests.post(
            f"{url}/auth/v1/token?grant_type=password",
            json={"email": email, "password": password},
            headers={"apikey": key, "Content-Type": "application/json"},
        )
        if resp.status_code == 200:
            data = resp.json()
            st.session_state["_supabase_user"] = data.get("user", {})
            st.session_state["_supabase_access_token"] = data.get("access_token", "")
            st.rerun()
        else:
            err = resp.json()
            st.error(err.get("msg", err.get("error_description", "Sign-in failed")))
    except Exception as e:
        st.error(f"Sign-in error: {e}")


def _email_sign_up(url: str, key: str, email: str, password: str):
    try:
        resp = requests.post(
            f"{url}/auth/v1/signup",
            json={"email": email, "password": password},
            headers={"apikey": key, "Content-Type": "application/json"},
        )
        if resp.status_code in (200, 201):
            data = resp.json()
            user = data.get("user", data)
            if data.get("confirmation_sent_at") or (user.get("identities") == []):
                st.success("✅ Check your email to confirm your account!")
            else:
                st.session_state["_supabase_user"] = user
                st.session_state["_supabase_access_token"] = data.get(
                    "access_token", ""
                )
                st.rerun()
        else:
            err = resp.json()
            st.error(err.get("msg", err.get("error_description", "Sign-up failed")))
    except Exception as e:
        st.error(f"Sign-up error: {e}")


# ─── Session management ─────────────────────────────────────────────


def get_user(sb: Client):
    user_data = st.session_state.get("_supabase_user")
    if user_data:
        return _wrap_user(user_data)
    return None


def logout_ui():
    user_data = st.session_state.get("_supabase_user", {})
    display_name = (
        user_data.get("user_metadata", {}).get("full_name")
        or user_data.get("user_metadata", {}).get("name")
        or user_data.get("email", "User")
    )
    st.caption(f"👤 **{display_name}**")
    if st.button("Sign out", key="_logout_btn", type="secondary"):
        for k in list(st.session_state.keys()):
            if (
                k.startswith("_supabase")
                or k.startswith("_pkce")
                or k.startswith("_user")
            ):
                del st.session_state[k]
        _clear_verifier()
        st.rerun()


def logout(sb: Client):
    st.session_state.pop("_supabase_user", None)
    st.session_state.pop("_user_profile", None)
    st.session_state.pop("_supabase_access_token", None)


# ─── Profile CRUD (REST API with user's token) ──────────────────────


def load_profile(sb: Client, user_id: str) -> dict:
    if "_user_profile" in st.session_state:
        return st.session_state["_user_profile"]
    try:
        resp = requests.get(
            f"{_rest_url()}/user_profiles?id=eq.{user_id}&select=*",
            headers=_auth_headers(),
        )
        if resp.status_code == 200 and resp.json():
            profile = resp.json()[0]
            st.session_state["_user_profile"] = profile
            return profile
    except Exception:
        pass
    return {}


def save_profile(sb: Client, user_id: str, profile_data: dict):
    try:
        resp = requests.patch(
            f"{_rest_url()}/user_profiles?id=eq.{user_id}",
            json=profile_data,
            headers={**_auth_headers(), "Prefer": "return=minimal"},
        )
        if resp.status_code not in (200, 204):
            st.warning(f"Could not save profile: {resp.status_code} {resp.text}")
        st.session_state.pop("_user_profile", None)
    except Exception as e:
        st.warning(f"Could not save profile: {e}")


# ─── Favorites (REST API with user's token) ──────────────────────────


@st.cache_data(ttl=60)
def get_favorites(_user_id: str, _sb_url: str, _sb_key: str) -> set:
    try:
        token = st.session_state.get("_supabase_access_token", "")
        headers = {
            "apikey": _sb_key,
            "Content-Type": "application/json",
            "Authorization": f"Bearer {token}" if token else f"Bearer {_sb_key}",
        }
        resp = requests.get(
            f"{_sb_url}/rest/v1/favorite_segments?user_id=eq.{_user_id}&select=segment_id",
            headers=headers,
        )
        if resp.status_code == 200:
            return {row["segment_id"] for row in resp.json()}
    except Exception:
        pass
    return set()


def toggle_favorite(sb: Client, user_id: str, segment_id: int) -> bool:
    try:
        url = st.secrets["supabase"]["url"]
        headers = _auth_headers()

        # Check if exists
        resp = requests.get(
            f"{_rest_url()}/favorite_segments?user_id=eq.{user_id}&segment_id=eq.{segment_id}&select=id",
            headers=headers,
        )
        if resp.status_code == 200 and resp.json():
            # Remove
            requests.delete(
                f"{_rest_url()}/favorite_segments?user_id=eq.{user_id}&segment_id=eq.{segment_id}",
                headers=headers,
            )
            get_favorites.clear()
            return False
        else:
            # Add
            resp2 = requests.post(
                f"{_rest_url()}/favorite_segments",
                json={"user_id": user_id, "segment_id": segment_id},
                headers={**headers, "Prefer": "return=minimal"},
            )
            if resp2.status_code not in (200, 201):
                st.warning(f"Could not add favorite: {resp2.status_code} {resp2.text}")
            get_favorites.clear()
            return True
    except Exception as e:
        st.warning(f"Could not update favorite: {e}")
        return False


# ─── Per-user exclusions (REST API with user's token) ────────────────
# Parallel to favorites but for segments the user wants hidden from Tab 1b.
# Separate from the global `flagged_segments` table (which applies to all
# users). Backed by the `excluded_segments` Supabase table with columns:
#   user_id uuid, segment_id bigint, created_at timestamptz
# Primary key: (user_id, segment_id). RLS: users can only see/modify rows
# where user_id = auth.uid().


@st.cache_data(ttl=60)
def get_exclusions(_user_id: str, _sb_url: str, _sb_key: str) -> set:
    """Return the set of segment_ids the given user has excluded."""
    try:
        token = st.session_state.get("_supabase_access_token", "")
        headers = {
            "apikey": _sb_key,
            "Content-Type": "application/json",
            "Authorization": f"Bearer {token}" if token else f"Bearer {_sb_key}",
        }
        resp = requests.get(
            f"{_sb_url}/rest/v1/excluded_segments?user_id=eq.{_user_id}&select=segment_id",
            headers=headers,
        )
        if resp.status_code == 200:
            return {row["segment_id"] for row in resp.json()}
    except Exception:
        pass
    return set()


def toggle_exclusion(sb: Client, user_id: str, segment_id: int) -> bool:
    """Add or remove a segment from the user's personal exclusion list.

    Returns True if the segment is now excluded, False if it was un-excluded.
    """
    try:
        headers = _auth_headers()

        # Check if exists
        resp = requests.get(
            f"{_rest_url()}/excluded_segments?user_id=eq.{user_id}&segment_id=eq.{segment_id}&select=segment_id",
            headers=headers,
        )
        if resp.status_code == 200 and resp.json():
            # Remove
            requests.delete(
                f"{_rest_url()}/excluded_segments?user_id=eq.{user_id}&segment_id=eq.{segment_id}",
                headers=headers,
            )
            get_exclusions.clear()
            return False
        else:
            # Add
            resp2 = requests.post(
                f"{_rest_url()}/excluded_segments",
                json={"user_id": user_id, "segment_id": segment_id},
                headers={**headers, "Prefer": "return=minimal"},
            )
            if resp2.status_code not in (200, 201):
                st.warning(f"Could not add exclusion: {resp2.status_code} {resp2.text}")
            get_exclusions.clear()
            return True
    except Exception as e:
        st.warning(f"Could not update exclusion: {e}")
        return False


# ─── Visit tracking ───────────────────────────────────────────────────


def log_visit(sb: Client, user_id: str = None, user_agent: str = None):
    try:
        row = {}
        if user_id:
            row["user_id"] = user_id
        if user_agent:
            row["user_agent"] = user_agent[:500]
        requests.post(
            f"{_rest_url()}/visits",
            json=row,
            headers={**_auth_headers(), "Prefer": "return=minimal"},
        )
    except Exception:
        pass
