import unittest

from src.matching import Product, clean_product_name, detect_product_type, parse_product


class MatchingUnitTest(unittest.TestCase):
    def test_marketing_noise_is_removed_but_bundle_is_kept(self):
        value = clean_product_name("[TẶNG QUẠT ĐƠN TỪ 250K] Combo 4 Bánh AFC 172g")
        self.assertNotIn("tang quat", value)
        self.assertIn("combo 4", value)
        self.assertIn("172g", value)

    def test_vietnam_product_type(self):
        self.assertEqual(detect_product_type("vn", "combo banh quy afc 172g"), "banh_quy")

    def test_vietnam_specific_type_is_not_generic(self):
        self.assertEqual(detect_product_type("vn", "combo banh kem xop 230g"), "banh_kem_xop")

    def test_indonesia_product_type(self):
        self.assertEqual(detect_product_type("id", "glad2glow moisturizer niacinamide"), "moisturizer")

    def test_attributes(self):
        product = Product("vn", "VND", "2026-07-03", 1, "Shop", 2, "Combo 4 Bánh Quy AFC 172g", "AFC", 100000, 100629, None, None, None, None, False, False)
        parse_product(product)
        self.assertEqual(product.product_type, "banh_quy")
        self.assertEqual(product.weight_g, 172)
        self.assertEqual(product.bundle_count, 4)
        self.assertTrue(product.is_bundle)


if __name__ == "__main__":
    unittest.main()
