import sys
import tempfile
import unittest
from pathlib import Path

HOST = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HOST))

from storage import Product, ProductStore


class StorageTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = ProductStore(Path(self.temp.name) / "test.db",
                                  HOST / "products.json")

    def tearDown(self):
        self.store.close()
        self.temp.cleanup()

    def test_seed_contains_only_expected_ble_products(self):
        products = self.store.list()
        self.assertEqual(22, len(products))
        self.assertEqual({39178, 39179, 39180, 39181},
                         {item.pid for item in products if item.family == "E6D"})

    def test_crud_round_trip(self):
        product = Product(None, "自定义", "CUSTOM", 60000, "T2DSB",
                          100, 200, 5, "timeout",
                          {"version": 2, "temperature": 30, "zero_cross": 1})
        product_id = self.store.add(product)
        loaded = self.store.get(product_id)
        self.assertEqual("CUSTOM", loaded.model)
        self.assertEqual("timeout", loaded.behavior)
        loaded.name = "已修改"
        loaded.ready_final_ms = 300
        self.store.update(loaded)
        updated = self.store.get(product_id)
        self.assertEqual("已修改", updated.name)
        self.assertEqual(300, updated.ready_final_ms)
        self.store.delete(product_id)
        self.assertIsNone(self.store.get(product_id))

    def test_seed_is_not_restored_after_user_deletes_product(self):
        product_id = self.store.list()[0].id
        self.store.delete(product_id)
        self.store.close()
        self.store = ProductStore(Path(self.temp.name) / "test.db",
                                  HOST / "products.json")
        self.assertEqual(21, len(self.store.list()))


if __name__ == "__main__":
    unittest.main()
