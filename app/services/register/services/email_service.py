"""Email service for temporary inbox creation."""
from __future__ import annotations

import os
import random
import string
from typing import Tuple, Optional

import requests

from app.core.config import get_config


class EmailService:
    """Email service wrapper."""

    def __init__(
        self,
        worker_domain: Optional[str] = None,
        email_domain: Optional[str] = None,
        admin_password: Optional[str] = None,
    ) -> None:
        self.worker_domain = (
            (worker_domain or get_config("register.worker_domain", "") or os.getenv("WORKER_DOMAIN", "")).strip()
        )
        self.email_domain = (
            (email_domain or get_config("register.email_domain", "") or os.getenv("EMAIL_DOMAIN", "")).strip()
        )
        self.admin_password = (
            (admin_password or get_config("register.admin_password", "") or os.getenv("ADMIN_PASSWORD", "")).strip()
        )

        if not all([self.worker_domain, self.email_domain, self.admin_password]):
            raise ValueError(
                "Missing required email settings: register.worker_domain, register.email_domain, "
                "register.admin_password"
            )

        self._domain_index: Optional[int] = None

    def _auth_headers(self) -> dict:
        return {
            "Authorization": f"Bearer {self.admin_password}",
            "Content-Type": "application/json",
        }

    def _get_domain_index(self) -> int:
        """Resolve the index of email_domain from /api/domains. Falls back to 0."""
        if self._domain_index is not None:
            return self._domain_index
        try:
            res = requests.get(
                f"https://{self.worker_domain}/api/domains",
                headers=self._auth_headers(),
                timeout=10,
            )
            if res.status_code == 200:
                domains = res.json()
                if isinstance(domains, list):
                    domain_lower = self.email_domain.lower()
                    for i, d in enumerate(domains):
                        if str(d).lower() == domain_lower:
                            self._domain_index = i
                            return i
        except Exception as exc:  # pragma: no cover - network/remote errors
            print(f"[-] Failed to fetch domains: {exc}")
        self._domain_index = 0
        return 0

    def _generate_random_name(self) -> str:
        letters1 = "".join(random.choices(string.ascii_lowercase, k=random.randint(4, 6)))
        numbers = "".join(random.choices(string.digits, k=random.randint(1, 3)))
        letters2 = "".join(random.choices(string.ascii_lowercase, k=random.randint(0, 5)))
        return letters1 + numbers + letters2

    def create_email(self) -> Tuple[Optional[str], Optional[str]]:
        """Create a temporary mailbox. Returns (address, address) — jwt slot reused as address for fetch."""
        url = f"https://{self.worker_domain}/api/create"
        try:
            domain_index = self._get_domain_index()
            random_name = self._generate_random_name()
            res = requests.post(
                url,
                json={
                    "local": random_name,
                    "domainIndex": domain_index,
                },
                headers=self._auth_headers(),
                timeout=10,
            )
            if res.status_code == 200:
                data = res.json()
                address = data.get("email")
                # Return address in both slots; fetch_first_email uses it as mailbox identifier.
                return address, address
            print(f"[-] Email create failed: {res.status_code} - {res.text}")
        except Exception as exc:  # pragma: no cover - network/remote errors
            print(f"[-] Email create error ({url}): {exc}")
        return None, None

    def fetch_first_email(self, mailbox: str) -> Optional[str]:
        """Fetch the first email payload for the mailbox address."""
        try:
            res = requests.get(
                f"https://{self.worker_domain}/api/emails",
                params={"mailbox": mailbox, "limit": 10},
                headers=self._auth_headers(),
                timeout=10,
            )
            if res.status_code == 200:
                data = res.json()
                if isinstance(data, list) and data:
                    first = data[0]

                    code = str(first.get("verification_code") or "").strip().upper()
                    if not code:
                        subject = str(first.get("subject") or "").strip().upper()
                        import re

                        match = re.search(r"\b([A-Z0-9]{3}-[A-Z0-9]{3})\b", subject)
                        if match:
                            code = match.group(1)
                        else:
                            compact = re.search(r"\b([A-Z0-9]{6})\b", subject)
                            if compact:
                                raw = compact.group(1)
                                code = f"{raw[:3]}-{raw[3:]}"

                    if code:
                        if "-" in code:
                            return f">{code}<"
                        if len(code) == 6:
                            return f">{code[:3]}-{code[3:]}<"
                        return f">{code}<"

                    return first.get("raw") or first.get("html_content") or first.get("content")
            return None
        except Exception as exc:  # pragma: no cover - network/remote errors
            print(f"Email fetch failed: {exc}")
            return None

    def clear_emails(self, mailbox: str) -> dict:
        """Clear all emails for one mailbox."""
        normalized = str(mailbox or "").strip().lower()
        if not normalized:
            return {"success": False, "mailbox": "", "error": "Missing mailbox"}

        try:
            res = requests.delete(
                f"https://{self.worker_domain}/api/emails",
                params={"mailbox": normalized},
                headers=self._auth_headers(),
                timeout=10,
            )
            if res.status_code in {200, 204}:
                payload: dict = {"success": True, "mailbox": normalized, "status_code": res.status_code}
                try:
                    body = res.json()
                    if isinstance(body, dict):
                        payload.update(body)
                except Exception:
                    text = (res.text or "").strip()
                    if text:
                        payload["message"] = text
                return payload

            return {
                "success": False,
                "mailbox": normalized,
                "status_code": res.status_code,
                "error": (res.text or "").strip() or f"HTTP {res.status_code}",
            }
        except Exception as exc:  # pragma: no cover - network/remote errors
            return {"success": False, "mailbox": normalized, "error": str(exc)}
