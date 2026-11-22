import unittest
import core
import fill


class FillTests(unittest.TestCase):
    def rows(self):
        return [core.new_row(core.DEFAULTS) for _ in range(8)]

    def test_ip_series_carries_to_next_octet_and_keeps_ipv6(self):
        self.assertEqual(fill.increment("10.0.0.255", 1), "10.0.1.0")
        self.assertEqual(fill.increment("2001:db8::ff", 1), "2001:db8::100")
        self.assertEqual(fill.increment("10.0.1.0", -1), "10.0.0.255")

    def test_padded_server_names_and_numbers(self):
        self.assertEqual(fill.increment("app-009", 1), "app-010")
        self.assertEqual(fill.increment("009", 2), "011")
        self.assertEqual(fill.increment("-1", 1), "0")
        self.assertEqual(fill.increment("server", 5), "server")
        with self.assertRaises(ValueError):
            fill.increment("255.255.255.255", 1)

    def test_plain_drag_repeats_whole_multirow_multicolumn_block(self):
        rows = self.rows()
        rows[0].update(host="192.0.2.10", name="first")
        rows[1].update(host="192.0.2.20", name="second")
        copied = fill.fill(rows, core.FIELDS, (0, 0, 1, 2), (0, 0, 5, 2))
        self.assertEqual([r["host"] for r in copied[:6]], ["192.0.2.10", "192.0.2.20"] * 3)
        self.assertEqual([r["name"] for r in copied[:6]], ["first", "second"] * 3)
        self.assertEqual(rows[2]["host"], "")
        self.assertEqual(copied[2]["user"], "opc")

    def test_ctrl_drag_increments_each_selected_column_by_one(self):
        rows = self.rows()
        rows[0].update(host="192.0.2.10", name="node-001")
        copied = fill.fill(rows, core.FIELDS, (0, 0, 0, 2), (0, 0, 3, 2), series=True)
        self.assertEqual([r["host"] for r in copied[:4]], ["192.0.2.10", "192.0.2.11", "192.0.2.12", "192.0.2.13"])
        self.assertEqual([r["name"] for r in copied[:4]], ["node-001", "node-002", "node-003", "node-004"])
        self.assertTrue(all(r["protocol"] == "SSH" for r in copied[:4]))

    def test_series_multirow_seed_uses_last_number_then_step_one(self):
        rows = self.rows()
        rows[0]["host"], rows[1]["host"] = "192.0.2.10", "192.0.2.40"
        result = fill.fill(rows, core.FIELDS, (0, 0, 1, 0), (0, 0, 3, 0), series=True)
        self.assertEqual([r["host"] for r in result[:4]], ["192.0.2.10", "192.0.2.40", "192.0.2.41", "192.0.2.42"])

    def test_upwards_and_horizontal_copy(self):
        rows = self.rows()
        rows[3]["host"] = "192.0.2.10"
        up = fill.fill(rows, core.FIELDS, (3, 0, 3, 0), (0, 0, 3, 0), series=True)
        self.assertEqual([r["host"] for r in up[:4]], ["192.0.2.7", "192.0.2.8", "192.0.2.9", "192.0.2.10"])
        rows[0]["host"], rows[0]["protocol"] = "A", "B"
        across = fill.fill(rows, core.FIELDS, (0, 0, 0, 1), (0, 0, 0, 5))
        self.assertEqual([across[0][f] for f in core.FIELDS[:6]], ["A", "B"] * 3)

    def test_nonnumeric_seed_tiles_in_ctrl_drag(self):
        rows = self.rows()
        rows[0]["name"], rows[1]["name"] = "alpha", "beta"
        result = fill.fill(rows, core.FIELDS, (0, 2, 1, 2), (0, 2, 5, 2), series=True)
        self.assertEqual([r["name"] for r in result[:6]], ["alpha", "beta"] * 3)


if __name__ == "__main__":
    unittest.main()
