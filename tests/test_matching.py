import unittest

from src.matching import Product, assign_companies, candidate_pairs, clean_product_name, detect_family, detect_product_type, match_row, package_relation, parse_product


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
        self.assertEqual(product.quantity, 4)
        self.assertEqual(product.total_weight_g, 688)
        self.assertTrue(product.is_bundle)

    def test_decimal_comma_weight_is_preserved(self):
        product = Product("vn", "VND", "2026-07-03", 1, "Shop", 2, "Bánh gạo túi 134,4g", "Richy", 30000, 1, None, None, None, None, False, False)
        parse_product(product)
        self.assertEqual(product.weight_g, 134.4)
        self.assertEqual(product.total_weight_g, 134.4)

    def test_combo_total_weight_and_pack_relation(self):
        single = Product("vn", "VND", "2026-07-03", 1, "A", 1, "Bánh yến mạch túi 220g", "Richy", 30000, 1, None, None, None, None, False, False)
        combo = Product("vn", "VND", "2026-07-03", 2, "B", 2, "Combo 3 túi bánh yến mạch 220g", "Richy", 80000, 1, None, None, None, None, False, False)
        parse_product(single); parse_product(combo)
        self.assertEqual(single.total_weight_g, 220)
        self.assertEqual(combo.total_weight_g, 660)
        self.assertEqual(package_relation(single, combo), "different_quantity")

    def test_quantity_range_is_ambiguous(self):
        product = Product("vn", "VND", "2026-07-03", 1, "Shop", 2, "Combo 2-4 bịch bánh quy 192g", "Richy", 100000, 1, None, None, None, None, False, False)
        parse_product(product)
        self.assertTrue(product.package_ambiguous)
        self.assertIsNone(product.total_weight_g)

    def test_multiple_marketplace_variations_block_price_comparison(self):
        product = Product(
            "vn", "VND", "2026-07-03", 1, "Shop", 2,
            "Combo bánh mì Fe'sta", "Richy", 45000, 1,
            None, None, None, None, False, False,
            "Phân loại", '["Combo 2", "Combo 6", "Combo 10"]',
        )
        parse_product(product)
        self.assertEqual(product.variation_count, 3)
        self.assertTrue(product.price_variant_ambiguous)

    def test_carton_quantity_drives_total_weight(self):
        product = Product("vn", "VND", "2026-07-03", 1, "Shop", 2, "Thùng 48 bánh Karo 26g/gói", "Richy", 400000, 1, None, None, None, None, False, False)
        parse_product(product)
        self.assertEqual(product.quantity, 48)
        self.assertEqual(product.total_weight_g, 1248)

    def test_flavour_is_extracted_as_variant(self):
        pepper = Product("vn", "VND", "2026-07-03", 1, "A", 1, "Bánh gạo Jinju vị bò nướng tiêu 134,4g", "Richy", 30000, 1, None, None, None, None, False, False)
        salt = Product("vn", "VND", "2026-07-03", 2, "B", 2, "Bánh gạo Jinju vị muối hồng 134,4g", "Richy", 30000, 1, None, None, None, None, False, False)
        parse_product(pepper); parse_product(salt)
        self.assertEqual(pepper.variant_signature, "bò nướng tiêu")
        self.assertEqual(salt.variant_signature, "muối hồng")
        self.assertNotEqual(pepper.variant_signature, salt.variant_signature)

    def test_product_family_is_extracted(self):
        self.assertEqual(detect_family("banh gao richy jinju vi pho mai"), "Jinju")
        self.assertEqual(detect_family("banh yen mach mini bite"), "Mini Bite")

    def test_same_owner_different_distributors_can_be_compared(self):
        north = parse_product(Product("vn", "VND", "2026-07-03", 1, "Richy Bắc", 11, "Bánh gạo Jinju 100g", "Richy", 30000, 7, None, None, None, None, False, False))
        south = parse_product(Product("vn", "VND", "2026-07-03", 2, "Richy Nam", 22, "Bánh gạo Jinju 100g", "Richy", 30000, 7, None, None, None, None, False, False))
        other = parse_product(Product("vn", "VND", "2026-07-03", 3, "Orion", 33, "Bánh gạo An 100g", "Orion", 30000, 7, None, None, None, None, False, False))
        assign_companies([north, south, other], {
            ("vn", 1): ("richy", "Richy", "richy_north", "Richy Bắc"),
            ("vn", 2): ("richy", "Richy", "richy_south", "Richy Nam"),
            ("vn", 3): ("orion", "Orion", "orion_official", "Orion Official"),
        })
        pairs = candidate_pairs([north, south, other])
        self.assertIn((0, 1), pairs)
        self.assertIn((0, 2), pairs)

    def test_same_distributor_entity_is_excluded(self):
        shop_a = parse_product(Product("vn", "VND", "2026-07-03", 1, "Seller A1", 11, "Bánh gạo Jinju 100g", "Richy", 30000, 7, None, None, None, None, False, False))
        shop_b = parse_product(Product("vn", "VND", "2026-07-03", 2, "Seller A2", 22, "Bánh gạo Jinju 100g", "Richy", 31000, 7, None, None, None, None, False, False))
        assign_companies([shop_a, shop_b], {
            ("vn", 1): ("richy", "Richy", "distributor_a", "Distributor A"),
            ("vn", 2): ("richy", "Richy", "distributor_a", "Distributor A"),
        })
        self.assertNotIn((0, 1), candidate_pairs([shop_a, shop_b]))

    def test_same_sku_across_distributors_is_exact(self):
        north = parse_product(Product("vn", "VND", "2026-07-03", 1, "Richy Bắc", 11, "Bánh gạo Jinju vị cốm sữa 145g", "Richy", 31000, 7, None, None, None, None, False, False))
        south = parse_product(Product("vn", "VND", "2026-07-03", 2, "Richy Nam", 22, "Bánh gạo Jinju vị cốm sữa 145g", "Richy", 30000, 7, None, None, None, None, False, False))
        result = match_row(north, south, 0.99, "test")
        self.assertEqual(result["match_type"], "same_product")

    def test_different_flavour_is_not_a_price_identity_match(self):
        pepper = parse_product(Product("vn", "VND", "2026-07-03", 1, "Richy Bắc", 11, "Bánh gạo Jinju vị bò nướng tiêu 134,4g", "Richy", 30000, 7, None, None, None, None, False, False))
        honey = parse_product(Product("vn", "VND", "2026-07-03", 2, "Richy Nam", 22, "Bánh gạo Jinju vị mật ong 134,4g", "Richy", 30000, 7, None, None, None, None, False, False))
        result = match_row(pepper, honey, 0.95, "test")
        self.assertEqual(result["match_type"], "substitute")


if __name__ == "__main__":
    unittest.main()
