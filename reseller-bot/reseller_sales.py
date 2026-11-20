"""Sales integration for the scoped 3x-ui-aether endpoint."""
import copy
import os
import re
import secrets
from urllib.parse import urlencode, urlsplit

import aiohttp
from cryptography.fernet import Fernet, InvalidToken


class SalesError(RuntimeError):
    pass


class PlanUnavailable(SalesError):
    pass


class InsufficientFunds(SalesError):
    pass


class SalesAPI:
    def __init__(self, base_url, token):
        url = urlsplit(base_url)
        if (url.scheme != "https" or not url.hostname or url.username or url.password
                or url.query or url.fragment or len(token) < 32
                or any(ord(char) < 33 or ord(char) > 126 for char in token)):
            raise SalesError("Sales API requires HTTPS and a scoped token.")
        self.base_url = base_url.rstrip("/")
        self.token = token

    @classmethod
    def from_env(cls):
        return cls(os.getenv("SANAEI_URL", ""), os.getenv("SANAEI_SALES_TOKEN", ""))

    async def request(self, method, path, **kwargs):
        try:
            async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=15)) as session:
                async with session.request(
                    method, self.base_url + "/delegate-sales/v1" + path,
                    headers={"Authorization": f"Bearer {self.token}"},
                    allow_redirects=False, **kwargs,
                ) as response:
                    data = await response.json()
                    if not isinstance(data, dict):
                        raise SalesError("Unexpected response from Sanaei.")
                    if (path == "/orders" and response.status == 409
                            and data.get("msg") == "sales plan or group unavailable"):
                        raise PlanUnavailable("Sales plan or group unavailable.")
                    if response.status != 200 or data.get("success") is not True:
                        raise SalesError(f"Sanaei rejected the request ({response.status}).")
                    return data.get("obj")
        except (aiohttp.ClientError, ValueError, TimeoutError) as exc:
            raise SalesError("Sanaei could not confirm the request.") from exc

    async def catalog(self):
        return await self.request("GET", "/catalog")

    async def create_plan(self, name, quota):
        return await self.request("POST", "/plans", data={
            "name": name, "quotaGiB": str(quota), "enabled": "1",
        })

    async def provision(self, reference, order, password):
        return await self.request("POST", "/orders", json={
            "reference": reference, "planId": order["plan"], "groupId": order["group"],
            "quotaGiB": order["quota"], "password": password,
        })

    def login_url(self, username):
        if not re.fullmatch(r"sale-[0-9a-f]{24}", username):
            raise SalesError("Unexpected delegated username.")
        return self.base_url + "/delegate/?" + urlencode({"account": username})


class WalletSales:
    """Persist an order and its wallet debit in the same atomic JSON replacement."""

    def __init__(self, users, save, key):
        self.users = users
        self.save = save
        try:
            self.cipher = Fernet(key.encode())
        except ValueError as exc:
            raise SalesError("A valid RESELLER_FERNET_KEY is required.") from exc

    def orders(self, uid):
        return self.users[str(uid)].get("reseller_orders", {})

    def _commit(self, uid, user):
        if not self.save({**self.users, str(uid): user}):
            raise SalesError("Could not persist the wallet operation.")
        self.users[str(uid)].update(user)

    def reserve(self, uid, reference, quote):
        if order := self.orders(uid).get(reference):
            return order
        user = copy.deepcopy(self.users[str(uid)])
        if quote["price"] <= 0 or user["balance"] < quote["price"]:
            raise InsufficientFunds("Insufficient wallet funds.")
        order = {
            **quote, "state": "pending",
            "secret": self.cipher.encrypt(secrets.token_urlsafe(24).encode()).decode(),
        }
        user["balance"] -= quote["price"]
        user.setdefault("reseller_orders", {})[reference] = order
        self._commit(uid, user)
        return order

    def complete(self, uid, reference, result):
        user = copy.deepcopy(self.users[str(uid)])
        order = user["reseller_orders"][reference]
        if order["state"] != "pending":
            return order, False
        if (result["quotaGiB"] != order["quota"] or result["groupId"] != order["group"]
                or not isinstance(result["id"], int) or result["id"] < 1
                or not re.fullmatch(r"sale-[0-9a-f]{24}", result["username"])):
            raise SalesError("The account returned did not match the order.")
        order.update(state="ready", account=result["id"], username=result["username"])
        user["has_purchased"] = True
        user["total_purchases"] += 1
        user["total_spent"] += order["price"]
        self._commit(uid, user)
        return order, True

    def refund(self, uid, reference):
        user = copy.deepcopy(self.users[str(uid)])
        order = user["reseller_orders"][reference]
        if order["state"] == "pending":
            user["balance"] += order["price"]
            order["state"] = "refunded"
            order.pop("secret")
            self._commit(uid, user)

    def password(self, order):
        try:
            return self.cipher.decrypt(order["secret"].encode()).decode()
        except InvalidToken as exc:
            raise SalesError("Could not decrypt the order credentials.") from exc
