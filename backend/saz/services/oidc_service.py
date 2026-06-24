"""OIDC Authorization Code + PKCE login flow.

Two steps:

* ``begin`` builds the IdP authorization URL and a signed transaction token
  (state + nonce + PKCE verifier) the route stashes in a short-lived cookie.
* ``complete`` validates state, exchanges the code for tokens, verifies the
  ID token (signature via JWKS, issuer, audience, nonce), then resolves the
  IdP subject to a local user — linking by verified email or JIT-provisioning
  a viewer when the provider allows it — and opens a refresh session.

The lower-level HTTP/crypto helpers are module-level so tests can substitute
fakes without standing up a real IdP.
"""

import base64
import hashlib
import secrets
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlencode

import httpx
import jwt

from saz.db.models import AuthProvider, User
from saz.db.unit_of_work import UnitOfWork
from saz.domain.literals import Role
from saz.security import hash_password
from saz.services.auth_provider_service import fetch_discovery_document
from saz.services.auth_service import AuthService
from saz.settings import settings

_TX_TYPE = "oidc_tx"
_TX_TTL_SECONDS = 600


class OidcError(Exception):
    """Recoverable OIDC login failure; surfaced to the user as a login error."""


DEFAULT_CALLBACK_PATH = "/api/v1/auth/oidc/callback"


# --- Injectable HTTP/crypto seams (monkeypatched in tests) ---


def exchange_code(
    token_endpoint: str,
    *,
    code: str,
    redirect_uri: str,
    client_id: str,
    client_secret: str | None,
    code_verifier: str,
) -> dict:
    """Exchange an authorization code for tokens.

    Confidential clients send ``client_secret`` (client_secret_post); public
    (PKCE-only) clients omit it and rely on the PKCE ``code_verifier`` alone.
    """
    form = {
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": redirect_uri,
        "client_id": client_id,
        "code_verifier": code_verifier,
    }
    if client_secret:
        form["client_secret"] = client_secret
    resp = httpx.post(token_endpoint, data=form, timeout=10.0)
    resp.raise_for_status()
    data: dict = resp.json()
    return data


def fetch_userinfo(userinfo_endpoint: str, access_token: str) -> dict:
    """Fetch OIDC UserInfo claims with the access token.

    Many IdPs (e.g. GEANT/SATOSA) return only authentication claims in the ID
    token and expose email/profile via UserInfo.
    """
    resp = httpx.get(
        userinfo_endpoint,
        headers={"Authorization": f"Bearer {access_token}"},
        timeout=10.0,
    )
    resp.raise_for_status()
    data: dict = resp.json()
    return data


def verify_id_token(
    id_token: str, *, jwks_uri: str, issuer: str, client_id: str, nonce: str
) -> dict:
    """Verify an ID token's signature and core claims, returning its claims."""
    jwk_client = jwt.PyJWKClient(jwks_uri)
    signing_key = jwk_client.get_signing_key_from_jwt(id_token)
    claims: dict = jwt.decode(
        id_token,
        signing_key.key,
        algorithms=["RS256", "ES256"],
        audience=client_id,
        issuer=issuer,
    )
    if claims.get("nonce") != nonce:
        raise OidcError("ID token nonce mismatch")
    return claims


def _pkce_challenge(verifier: str) -> str:
    digest = hashlib.sha256(verifier.encode()).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode()


class OidcService:
    def __init__(self, uow: UnitOfWork):
        self.uow = uow
        self.auth = AuthService(uow)

    def _redirect_uri(self, provider: AuthProvider) -> str:
        """The redirect URI registered with the IdP.

        Defaults to the backend's generic callback; a provider may override it
        (e.g. to point at a frontend route) to match its IdP registration. The
        same value is used in the authorization request and the token exchange.
        """
        if provider.redirect_uri:
            return provider.redirect_uri
        base = settings.BACKEND_BASE_URL.rstrip("/")
        return f"{base}{DEFAULT_CALLBACK_PATH}"

    def provider_key_from_tx(self, tx_token: str) -> str:
        """Recover the provider key from a signed transaction token so the
        generic callback can find the provider without it in the URL path."""
        tx = self._decode_tx(tx_token)
        provider_key = tx.get("provider_key")
        if not provider_key:
            raise OidcError("invalid OIDC state")
        return str(provider_key)

    def _provider(self, provider_key: str) -> AuthProvider:
        assert self.uow.auth_providers is not None
        provider = self.uow.auth_providers.get_by_key(provider_key)
        if provider is None or not provider.enabled:
            raise OidcError("unknown or disabled provider")
        return provider

    def _discover(self, issuer: str) -> dict:
        """Fetch discovery, turning network/HTTP failures into an OidcError so
        an unreachable or misconfigured issuer becomes a friendly login error
        rather than a 500."""
        try:
            return fetch_discovery_document(issuer)
        except (httpx.HTTPError, ValueError) as exc:
            raise OidcError(f"could not reach provider discovery: {exc}") from exc

    def begin(self, provider_key: str) -> tuple[str, str]:
        """Return ``(authorization_url, tx_token)`` to start the login."""
        provider = self._provider(provider_key)
        discovery = self._discover(provider.issuer)
        authorization_endpoint = discovery.get("authorization_endpoint")
        if not authorization_endpoint:
            raise OidcError("provider discovery missing authorization_endpoint")

        state = secrets.token_urlsafe(24)
        nonce = secrets.token_urlsafe(24)
        verifier = secrets.token_urlsafe(48)
        redirect_uri = self._redirect_uri(provider)
        params = {
            "response_type": "code",
            "client_id": provider.client_id,
            "redirect_uri": redirect_uri,
            "scope": provider.scopes,
            "state": state,
            "nonce": nonce,
            "code_challenge": _pkce_challenge(verifier),
            "code_challenge_method": "S256",
        }
        # offline_access (refresh token) requires explicit consent; some IdPs
        # (e.g. GEANT/SATOSA) reject the request outright without it.
        if "offline_access" in provider.scopes.split():
            params["prompt"] = "consent"
        url = f"{authorization_endpoint}?{urlencode(params)}"
        # Persist the exact redirect_uri so the token exchange uses an identical
        # value (IdPs require the two to match byte-for-byte).
        tx = self._encode_tx(
            {
                "provider_key": provider_key,
                "state": state,
                "nonce": nonce,
                "verifier": verifier,
                "redirect_uri": redirect_uri,
            }
        )
        return url, tx

    def complete(
        self,
        provider_key: str,
        *,
        code: str,
        state: str,
        tx_token: str,
        ip: str | None = None,
        user_agent: str | None = None,
    ) -> tuple[str, datetime, str]:
        """Finish login. Returns ``(access_token, expires_at, refresh_secret)``."""
        tx = self._decode_tx(tx_token)
        if tx.get("provider_key") != provider_key or tx.get("state") != state:
            raise OidcError("invalid OIDC state")

        provider = self._provider(provider_key)
        discovery = self._discover(provider.issuer)
        token_endpoint = discovery.get("token_endpoint")
        jwks_uri = discovery.get("jwks_uri")
        disc_issuer = discovery.get("issuer", provider.issuer)
        if not token_endpoint or not jwks_uri:
            raise OidcError("provider discovery missing token_endpoint or jwks_uri")

        from saz.security.secret_box import decrypt_secret

        try:
            token_resp = exchange_code(
                token_endpoint,
                code=code,
                redirect_uri=str(tx["redirect_uri"]),
                client_id=provider.client_id,
                client_secret=(
                    decrypt_secret(provider.client_secret_encrypted)
                    if provider.client_secret_encrypted
                    else None
                ),
                code_verifier=str(tx["verifier"]),
            )
        except httpx.HTTPError as exc:
            raise OidcError(f"token exchange failed: {exc}") from exc
        id_token = token_resp.get("id_token")
        if not id_token:
            raise OidcError("token response missing id_token")
        try:
            claims = verify_id_token(
                id_token,
                jwks_uri=jwks_uri,
                issuer=disc_issuer,
                client_id=provider.client_id,
                nonce=str(tx["nonce"]),
            )
        except OidcError:
            raise
        except Exception as exc:  # jwt / JWKS verification failures
            raise OidcError(f"ID token verification failed: {exc}") from exc

        # Many IdPs return email/profile only from UserInfo, not the ID token;
        # merge those claims (verifying the subject matches) before resolving.
        userinfo_endpoint = discovery.get("userinfo_endpoint")
        access_token = token_resp.get("access_token")
        if userinfo_endpoint and access_token:
            try:
                userinfo = fetch_userinfo(userinfo_endpoint, access_token)
            except httpx.HTTPError as exc:
                raise OidcError(f"userinfo request failed: {exc}") from exc
            if str(userinfo.get("sub")) != str(claims.get("sub")):
                raise OidcError("userinfo subject does not match ID token")
            claims = {**claims, **userinfo}

        user = self._resolve_user(provider, claims)
        token, expires_at, secret, _session = self.auth.start_session(
            user, auth_method="oidc", provider_key=provider_key, ip=ip, user_agent=user_agent
        )
        self.uow.commit()
        return token, expires_at, secret

    # --- Identity resolution ---

    def _resolve_user(self, provider: AuthProvider, claims: dict[str, Any]) -> User:
        assert self.uow.external_identities is not None
        assert self.uow.users is not None
        issuer = str(claims.get("iss"))
        subject = str(claims.get("sub"))
        if not subject or subject == "None":
            raise OidcError("ID token missing subject")

        # 1) Already linked → sign in as that user.
        identity = self.uow.external_identities.get_by_subject(issuer, subject)
        if identity is not None:
            user = self.uow.users.get(identity.user_id)
            if user is None or not user.is_active:
                raise OidcError("the linked account is unavailable")
            identity.last_login_at = datetime.now(UTC)
            return user

        email_raw = claims.get("email")
        email = email_raw.strip().lower() if isinstance(email_raw, str) else None
        # Some trusted IdPs (e.g. GEANT) never emit email_verified; allow an
        # opt-in per-provider override to treat a released email as verified.
        verified = bool(claims.get("email_verified")) or provider.trust_email_verified
        self._check_domain(provider, email)

        # 2) Verified email matches an existing local user → link.
        if email and verified:
            existing = self.uow.users.get_by_email(email)
            if existing is not None:
                self.uow.external_identities.link(
                    user_id=existing.id,
                    provider_key=provider.provider_key,
                    issuer=issuer,
                    subject=subject,
                    email=email,
                    email_verified=verified,
                )
                return existing

        # 3) JIT provisioning (when enabled and email is verified).
        if provider.jit_enabled:
            if not (email and verified):
                raise OidcError("a verified email is required to create an account")
            user = self._jit_create(provider, claims, email)
            self.uow.external_identities.link(
                user_id=user.id,
                provider_key=provider.provider_key,
                issuer=issuer,
                subject=subject,
                email=email,
                email_verified=verified,
            )
            return user

        raise OidcError("no Saz account is linked to this identity")

    def _check_domain(self, provider: AuthProvider, email: str | None) -> None:
        if not provider.allowed_domains:
            return
        allowed = {d.strip().lower() for d in provider.allowed_domains.split(",") if d.strip()}
        domain = email.split("@")[-1] if email and "@" in email else ""
        if domain not in allowed:
            raise OidcError("your email domain is not allowed for this provider")

    def _jit_create(self, provider: AuthProvider, claims: dict[str, Any], email: str) -> User:
        assert self.uow.users is not None
        username = self._unique_username(email)
        display_name = claims.get("name") if isinstance(claims.get("name"), str) else None
        # SSO users authenticate via the IdP; give them an unusable random
        # local password so the local login path can never match.
        user = self.uow.users.create(
            username=username,
            email=email,
            password_hash=hash_password(secrets.token_urlsafe(32)),
            display_name=display_name,
            role=Role(provider.default_role),
            is_active=True,
            must_change_password=False,
        )
        return user

    def _unique_username(self, email: str) -> str:
        assert self.uow.users is not None
        base = "".join(c for c in email.split("@")[0] if c.isalnum() or c in "_.-")[:48] or "user"
        if len(base) < 3:
            base = f"{base}_sso"
        candidate = base
        suffix = 0
        while self.uow.users.get_by_username(candidate) is not None:
            suffix += 1
            candidate = f"{base}{suffix}"
        return candidate

    # --- Transaction token (state/nonce/verifier) ---

    def _encode_tx(self, data: dict[str, str]) -> str:
        now = datetime.now(UTC)
        payload = {
            **data,
            "type": _TX_TYPE,
            "iat": int(now.timestamp()),
            "exp": int(now.timestamp()) + _TX_TTL_SECONDS,
        }
        return jwt.encode(payload, settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM)

    def _decode_tx(self, tx_token: str) -> dict[str, Any]:
        try:
            payload: dict = jwt.decode(
                tx_token, settings.JWT_SECRET_KEY, algorithms=[settings.JWT_ALGORITHM]
            )
        except jwt.InvalidTokenError as exc:
            raise OidcError("OIDC transaction expired or invalid") from exc
        if payload.get("type") != _TX_TYPE:
            raise OidcError("invalid OIDC transaction")
        return payload
