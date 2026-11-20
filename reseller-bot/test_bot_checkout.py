import asyncio
import os
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from cryptography.fernet import Fernet

# Import the entry point with fake Telegram settings and an isolated data directory.
data_dir = tempfile.TemporaryDirectory()
with patch.dict(os.environ, {"BOT_TOKEN": "123456789:test-only", "SUPER_ADMIN_ID": "17",
                             "BOT_DATA_DIR": data_dir.name}):
    import bot as app


class BotCheckoutTests(unittest.IsolatedAsyncioTestCase):
    async def test_duplicate_checkout_notifies_buyer_and_owner_once(self):
        uid, ref = 71, "test-quote"
        quote = {"price": 500_000, "plan": 2, "group": 7, "quota": 150, "name": "نمایندگی"}
        user = {"balance": 600_000, "total_spent": 0, "total_purchases": 0}
        account = {"id": 13, "username": "sale-" + "a" * 24, "quotaGiB": 150, "groupId": 7}
        api = SimpleNamespace(provision=AsyncMock(return_value=account),
                              login_url=lambda _: "https://example.test/base/delegate/")
        callback = SimpleNamespace(from_user=SimpleNamespace(id=uid), data="rsbuy:" + ref,
                                   message=SimpleNamespace(answer=AsyncMock()))
        with (
            patch.dict(os.environ, {"RESELLER_FERNET_KEY": Fernet.generate_key().decode()}),
            patch.object(app, "SUPER_ADMIN_ID", 17),
            patch.object(app, "USERS", {str(uid): user}),
            patch.object(app, "SETTINGS", {"reseller_prices": {"2": 500_000}}),
            patch.object(app, "sale_quotes", {uid: {ref: quote}}),
            patch.object(app, "sale_lock", asyncio.Lock()),
            patch.object(app, "save_json", return_value=True),
            patch.object(app, "force_join_gate", new=AsyncMock(return_value=False)),
            patch.object(app, "safe_answer", new=AsyncMock()),
            patch.object(app.SalesAPI, "from_env", return_value=api),
            patch.object(app.bot, "send_message", new=AsyncMock()) as send,
        ):
            await app.pay_reseller_wallet(callback)
            await app.pay_reseller_wallet(callback)
            self.assertEqual(user["balance"], 100_000)
            self.assertEqual(user["reseller_orders"][ref]["state"], "ready")
            self.assertEqual(user["total_purchases"], 1)
            api.provision.assert_awaited_once()
            self.assertEqual([call.args[0] for call in send.await_args_list], [71, 17])
            for call in send.await_args_list:
                self.assertIn("delegate/", call.args[1])
                self.assertTrue(call.kwargs["protect_content"])

    async def test_group_chat_cannot_reach_checkout(self):
        callback = app.CallbackQuery.model_validate({
            "id": "fake", "from": {"id": 71, "is_bot": False, "first_name": "Buyer"},
            "chat_instance": "fake", "data": "rsbuy:test",
            "message": {"message_id": 1, "date": 1, "chat": {"id": -71, "type": "group"}},
        })
        handler = AsyncMock()
        with patch.object(app, "safe_answer", new=AsyncMock()):
            await app.private_sales_middleware(handler, callback, {})
        handler.assert_not_awaited()
