import unittest

from cryptography.fernet import Fernet

from reseller_sales import InsufficientFunds, SalesAPI, SalesError, WalletSales


class WalletSalesTests(unittest.TestCase):
    def setUp(self):
        self.users = {"71": {
            "balance": 600_000, "total_purchases": 0, "total_spent": 0,
        }}
        self.key = Fernet.generate_key().decode()
        self.writes = []
        self.ledger = WalletSales(self.users, lambda record: self.writes.append(record) or True, self.key)
        self.quote = {"price": 500_000, "plan": 2, "group": 7, "quota": 150, "name": "forosh"}
        self.result = {"id": 31, "username": "sale-" + "b" * 24, "groupId": 7, "quotaGiB": 150}

    def test_one_debit_and_one_fulfillment(self):
        order = self.ledger.reserve(71, "receipt", self.quote)
        self.assertEqual(order, self.ledger.reserve(71, "receipt", self.quote))
        self.assertEqual(len(self.writes), 1)
        self.assertEqual(self.writes[0]["71"]["balance"], 100_000)
        self.assertEqual(self.writes[0]["71"]["reseller_orders"]["receipt"]["state"], "pending")
        cleartext = self.ledger.password(order)
        self.assertEqual(len(cleartext), 32)
        self.assertNotIn(cleartext, order["secret"])
        self.assertTrue(self.ledger.complete(71, "receipt", self.result)[1])
        self.assertFalse(self.ledger.complete(71, "receipt", self.result)[1])
        self.assertEqual(self.users["71"]["total_purchases"], 1)

    def test_refund_is_idempotent(self):
        self.ledger.reserve(71, "receipt", self.quote)
        self.ledger.refund(71, "receipt")
        self.ledger.refund(71, "receipt")
        self.assertEqual(self.users["71"]["balance"], 600_000)
        self.assertEqual(self.ledger.orders(71)["receipt"]["state"], "refunded")

    def test_insufficient_funds_and_failed_write(self):
        with self.assertRaises(InsufficientFunds):
            self.ledger.reserve(71, "receipt", {**self.quote, "price": 700_000})
        broken = WalletSales(self.users, lambda _: False, self.key)
        with self.assertRaises(SalesError):
            broken.reserve(71, "receipt", self.quote)
        self.assertEqual(self.ledger.orders(71), {})
        self.assertEqual(self.users["71"]["balance"], 600_000)

    def test_mismatched_group_never_delivers(self):
        self.ledger.reserve(71, "receipt", self.quote)
        with self.assertRaises(SalesError):
            self.ledger.complete(71, "receipt", {**self.result, "groupId": 8})
        self.assertEqual(self.ledger.orders(71)["receipt"]["state"], "pending")

    def test_login_url_always_uses_the_delegated_path(self):
        api = SalesAPI("https://panel.example.test/base/", "x" * 32)
        self.assertEqual(api.login_url(self.result["username"]),
                         "https://panel.example.test/base/delegate/?account=sale-" + "b" * 24)
        with self.assertRaises(SalesError):
            api.login_url("https://another.example/admin")
        with self.assertRaises(SalesError):
            SalesAPI("http://panel.example.test", "x" * 32)
