from __future__ import annotations

import base64
import importlib.util
import json
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[3]
PLUGIN = ROOT / "plugins.v2" / "ptdatastatistics"


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


package = types.ModuleType("ptdatastatistics")
package.__path__ = [str(PLUGIN)]
sys.modules.setdefault("ptdatastatistics", package)
core = load_module("ptdatastatistics.core", PLUGIN / "core.py")
ptd_cookiecloud = load_module("ptdatastatistics.ptd_cookiecloud", PLUGIN / "ptd_cookiecloud.py")
site_rules_builtin = sys.modules["ptdatastatistics.site_rules_builtin"]


class PTDCookieCloudTests(unittest.TestCase):
    def test_empty_or_unidentified_list_returns_controlled_error(self):
        for records in ([], [{}], [{"bonusPerHour": 3}], {"userInfo": []}):
            with self.subTest(records=records):
                with self.assertRaises(ptd_cookiecloud.PTDCookieCloudError):
                    ptd_cookiecloud._extract_metrics(records)

    def test_extracts_only_latest_seeding_metrics_per_site(self):
        values = ptd_cookiecloud._extract_metrics(
            {
                "audiences": {
                    "2026-09-10": {
                        "site": "audiences",
                        "updateAt": 100,
                        "seedingBonus": 1000,
                        "seedingBonusPerHour": 2.5,
                        "uploaded": 999,
                        "uploads": 4,
                    },
                    "2026-09-11": {
                        "site": "audiences",
                        "updateAt": 200,
                        "seedingBonus": 1200,
                        "bonusPerHour": 3.5,
                        "uploaded": 1999,
                    },
                }
            }
        )

        self.assertEqual(values[0]["seeding_points"], 1200)
        self.assertEqual(values[0]["estimated_bonus_hourly"], 3.5)
        self.assertEqual(values[0]["seeding_points_hourly"], 2.5)
        self.assertEqual(values[0]["torrent_uploads"], 4)
        self.assertNotIn("uploaded", values[0])

    def test_uses_bonus_rate_instead_of_seeding_points_rate_for_hourly_magic(self):
        values = ptd_cookiecloud._extract_metrics(
            {
                "hhanclub": {
                    "site": "hhanclub",
                    "siteName": "憨憨",
                    "seedingBonus": 439_222,
                    "bonusPerHour": 41.35,
                    "seedingBonusPerHour": 12.45,
                    "uploads": 0,
                }
            }
        )

        self.assertEqual(values[0]["seeding_points"], 439_222)
        self.assertEqual(values[0]["estimated_bonus_hourly"], 41.35)
        self.assertEqual(values[0]["seeding_points_hourly"], 12.45)
        self.assertEqual(values[0]["torrent_uploads"], 0)

    def test_extracts_torrent_uploads_without_bonus_metrics(self):
        values = ptd_cookiecloud._extract_metrics({
            "pterclub": {
                "site": "pterclub",
                "siteName": "猫站",
                "levelName": "Power User",
                "uploads": 12,
                "updateAt": 100,
            }
        })

        self.assertEqual(values[0]["ptd_site"], "pterclub")
        self.assertEqual(values[0]["user_level"], "Power User")
        self.assertEqual(values[0]["torrent_uploads"], 12)
        self.assertIsNone(values[0]["seeding_points"])

    def test_extracts_user_level_without_other_metrics(self):
        values = ptd_cookiecloud._extract_metrics({
            "pttime": {"site": "pttime", "levelName": "Elite User"}
        })

        self.assertEqual(values[0]["user_level"], "Elite User")
        self.assertIsNone(values[0]["torrent_uploads"])

    def test_extracts_latest_user_level_from_new_list_export(self):
        values = ptd_cookiecloud._extract_metrics([
            {"site": "pttime", "date": "2026-09-12", "levelName": "Peasant"},
            {"site": "pttime", "date": "2026-09-13", "levelName": "(幼儿园)User"},
            {"site": "pter", "date": "2026-09-13", "levelName": "加菲猫 POWER USER"},
        ])

        by_site = {item["ptd_site"]: item for item in values}
        self.assertEqual(by_site["pttime"]["user_level"], "(幼儿园)User")
        self.assertEqual(by_site["pter"]["user_level"], "加菲猫 POWER USER")

    def test_ptd_bonus_rate_is_used_for_seeding_points_eta_when_dedicated_rate_is_missing(self):
        values = ptd_cookiecloud._extract_metrics(
            {
                "audiences": {
                    "site": "audiences",
                    "seedingBonus": 70_260,
                    "bonusPerHour": 42.85,
                }
            }
        )

        self.assertEqual(values[0]["estimated_bonus_hourly"], 42.85)
        self.assertEqual(values[0]["seeding_points_hourly"], 42.85)

    def test_ptd_bonus_rate_fallback_applies_to_every_site(self):
        values = ptd_cookiecloud._extract_metrics(
            {
                "hhanclub": {
                    "site": "hhanclub",
                    "seedingBonus": 56_000,
                    "bonusPerHour": 10_000,
                }
            }
        )

        self.assertEqual(values[0]["seeding_points_hourly"], 10_000)

    def test_matches_known_alias_metadata_and_manual_mapping(self):
        configured = [
            {"id": 1, "name": "观众", "domain": "audiences.me"},
            {"id": 2, "name": "示例站", "domain": "tracker.example"},
            {"id": 3, "name": "PT时间", "domain": "pttime.org"},
        ]
        values = [
            {"ptd_site": "audiences", "seeding_points": 10},
            {"ptd_site": "custom", "estimated_bonus_hourly": 4},
            {"ptd_site": "pttime", "user_level": "Elite User"},
        ]

        matched = ptd_cookiecloud.match_metrics(
            values,
            {},
            configured,
            "custom=tracker.example",
        )

        self.assertEqual(
            {item["domain"] for item in matched},
            {"audiences.me", "tracker.example", "pttime.org"},
        )
        pttime = next(item for item in matched if item["domain"] == "pttime.org")
        self.assertEqual(pttime["user_level"], "Elite User")

    def test_decrypts_cookiecloud_legacy_payload(self):
        from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
        from cryptography.hazmat.primitives.padding import PKCS7

        uuid = "ptd-test"
        password = "secret"
        clear = json.dumps({"ptd_data": {"userInfo": {}}, "manifest": {}}).encode()
        passphrase = __import__("hashlib").md5(f"{uuid}-{password}".encode()).hexdigest()[:16].encode()
        salt = b"12345678"
        key, iv = ptd_cookiecloud._evp_bytes_to_key(passphrase, salt)
        padder = PKCS7(128).padder()
        padded = padder.update(clear) + padder.finalize()
        encryptor = Cipher(algorithms.AES(key), modes.CBC(iv)).encryptor()
        encrypted = base64.b64encode(b"Salted__" + salt + encryptor.update(padded) + encryptor.finalize()).decode()

        self.assertEqual(
            ptd_cookiecloud._decrypt(encrypted, uuid=uuid, password=password)["ptd_data"],
            {"userInfo": {}},
        )

    def test_parses_current_ptd_cookiecloud_payload(self):
        payload = {
            "ptd_data": {
                "userInfo": {
                    "audiences": {
                        "site": "audiences",
                        "seedingBonus": 1200,
                        "seedingBonusPerHour": 3.5,
                    }
                },
                "metadata": {"siteNameMap": {"audiences": "观众"}},
            },
            "manifest": {"fileName": "PTD_backup_current"},
        }
        with patch.object(ptd_cookiecloud, "_decrypt", return_value=payload):
            backup = ptd_cookiecloud.parse_backup_response(
                response={"encrypted": "ciphertext"},
                uuid="ptd-only",
                password="secret",
            )

        self.assertEqual(backup.name, "PTD_backup_current")
        self.assertEqual(backup.metrics[0]["seeding_points"], 1200)
        self.assertIsNone(backup.metrics[0]["estimated_bonus_hourly"])
        self.assertEqual(backup.metrics[0]["seeding_points_hourly"], 3.5)

class DeltaTests(unittest.TestCase):
    def test_formats_capacity_with_binary_units(self):
        self.assertEqual(core.format_bytes(1024**3), "1.00 GB")
        self.assertEqual(core.format_bytes(10 * 1024**3), "10.00 GB")
        self.assertEqual(core.format_bytes(120 * 1024**3), "120.0 GB")

    def test_requires_exact_previous_server_day(self):
        current = {"updated_day": "2026-09-05", "upload": 500, "download": 200}
        result = core.compute_daily_delta(
            current,
            {"updated_day": "2026-09-03", "upload": 100, "download": 50},
        )
        self.assertFalse(result["baseline_valid"])
        self.assertEqual(result["daily_upload"], 0)

    def test_calculates_strict_daily_deltas(self):
        result = core.compute_daily_delta(
            {"updated_day": "2026-09-05", "upload": 500, "download": 220},
            {"updated_day": "2026-09-04", "upload": 110, "download": 20, "err_msg": ""},
        )
        self.assertEqual(result["daily_upload"], 390)
        self.assertEqual(result["daily_download"], 200)
        self.assertTrue(result["baseline_valid"])

    def test_counter_reset_is_clamped_and_flagged(self):
        result = core.compute_daily_delta(
            {"updated_day": "2026-09-05", "upload": 10, "download": 2},
            {"updated_day": "2026-09-04", "upload": 100, "download": 1, "err_msg": ""},
        )
        self.assertEqual(result["daily_upload"], 0)
        self.assertEqual(result["daily_download"], 1)
        self.assertTrue(result["counter_reset"])

    def test_failed_previous_day_is_not_a_baseline(self):
        result = core.compute_daily_delta(
            {"updated_day": "2026-09-05", "upload": 200, "download": 100},
            {"updated_day": "2026-09-04", "upload": 100, "download": 50, "err_msg": "超时"},
        )
        self.assertFalse(result["baseline_valid"])

    def test_estimates_hourly_bonus_from_successive_snapshots(self):
        result = core.estimate_bonus_hourly(
            {"bonus": 148, "source_updated_at": "2026-09-05 08:00:00"},
            {"bonus": 100, "source_updated_at": "2026-09-04 08:00:00"},
        )
        self.assertEqual(result, 2.0)

    def test_hourly_bonus_does_not_guess_after_points_are_spent(self):
        result = core.estimate_bonus_hourly(
            {"bonus": 80, "source_updated_at": "2026-09-05 08:00:00"},
            {"bonus": 100, "source_updated_at": "2026-09-04 08:00:00"},
        )
        self.assertIsNone(result)

    def test_builds_hourly_traffic_from_real_mp_samples(self):
        result = core.build_hourly_traffic(
            [
                {
                    "domain": "example.test",
                    "updated_day": "2026-09-06",
                    "updated_time": "23:30:00",
                    "upload": 100,
                    "download": 50,
                },
                {
                    "domain": "example.test",
                    "updated_day": "2026-09-07",
                    "updated_time": "00:10:00",
                    "upload": 150,
                    "download": 70,
                },
                {
                    "domain": "example.test",
                    "updated_day": "2026-09-07",
                    "updated_time": "00:50:00",
                    "upload": 180,
                    "download": 75,
                },
                {
                    "domain": "example.test",
                    "updated_day": "2026-09-07",
                    "updated_time": "02:00:00",
                    "upload": 200,
                    "download": 90,
                },
            ],
            "2026-09-07",
        )

        self.assertTrue(result["baseline_valid"])
        self.assertEqual(result["sample_count"], 2)
        self.assertEqual(result["points"][0]["upload"], 30)
        self.assertEqual(result["points"][0]["download"], 5)
        self.assertEqual(result["points"][1]["samples"], 0)
        self.assertEqual(result["points"][2]["upload"], 20)
        self.assertEqual(result["points"][2]["download"], 15)

    def test_hourly_traffic_does_not_invent_first_sample_delta(self):
        result = core.build_hourly_traffic(
            [{
                "domain": "example.test",
                "updated_day": "2026-09-07",
                "updated_time": "08:00:00",
                "upload": 999,
                "download": 500,
            }],
            "2026-09-07",
        )

        self.assertFalse(result["baseline_valid"])
        self.assertEqual(sum(point["upload"] for point in result["points"]), 0)

    def test_hourly_traffic_does_not_treat_previous_day_as_an_hourly_baseline(self):
        result = core.build_hourly_traffic(
            [
                {
                    "domain": "example.test",
                    "updated_day": "2026-09-06",
                    "updated_time": "09:00:00",
                    "upload": 100,
                    "download": 50,
                },
                {
                    "domain": "example.test",
                    "updated_day": "2026-09-07",
                    "updated_time": "09:00:00",
                    "upload": 200,
                    "download": 80,
                },
            ],
            "2026-09-07",
        )

        self.assertFalse(result["baseline_valid"])
        self.assertEqual(result["sample_count"], 0)
        self.assertEqual(sum(point["upload"] for point in result["points"]), 0)
        self.assertEqual(sum(point["download"] for point in result["points"]), 0)


class TwelveAndExportTests(unittest.TestCase):
    def test_ourbits_is_named_our_castle(self):
        configured = [{"id": 12, "name": "OurBits"}]
        progress = core.build_twelve_progress(
            configured,
            {12: {"err_msg": "", "join_at": "2025-01-02"}},
        )
        target = next(item for item in progress["items"] if item["key"] == "ourbits")
        self.assertEqual(target["name"], "我堡")
        self.assertEqual(target["state"], "joined")

    def test_waiting_and_missing_states_are_distinct(self):
        progress = core.build_twelve_progress(
            [{"id": 1, "name": "皇后"}],
            {},
        )
        states = {item["key"]: item["state"] for item in progress["items"]}
        self.assertEqual(states["queen"], "waiting")
        self.assertEqual(states["ttg"], "missing")

    def test_chinese_ttg_name_is_recognized(self):
        progress = core.build_twelve_progress(
            [{"id": 1, "name": "听听歌"}],
            {1: {"err_msg": "", "join_at": "2025-01-02"}},
        )

        target = next(item for item in progress["items"] if item["key"] == "ttg")
        self.assertEqual(target["name"], "听听歌")
        self.assertEqual(target["state"], "joined")

    def test_u2_is_not_part_of_twelve_sites(self):
        progress = core.build_twelve_progress(
            [{"id": 1, "name": "U2"}],
            {1: {"err_msg": "", "join_at": "2025-01-02"}},
        )

        self.assertNotIn("u2", {item["key"] for item in progress["items"]})
        self.assertEqual(progress["joined"], 0)

    def test_joined_twelve_sites_are_sorted_by_join_date(self):
        progress = core.build_twelve_progress(
            [
                {"id": 1, "name": "TTG"},
                {"id": 2, "name": "皇后"},
                {"id": 3, "name": "M-Team"},
            ],
            {
                1: {"err_msg": "", "join_at": "2024-08-01"},
                2: {"err_msg": "", "join_at": "2023-06-02"},
                3: {"err_msg": "", "join_at": ""},
            },
        )
        joined = [item for item in progress["items"] if item["state"] == "joined"]
        self.assertEqual([item["key"] for item in joined], ["queen", "ttg", "mteam"])

    def test_joined_twelve_sites_use_full_join_timestamp_order(self):
        progress = core.build_twelve_progress(
            [
                {"id": 1, "name": "TTG"},
                {"id": 2, "name": "皇后"},
                {"id": 3, "name": "M-Team"},
            ],
            {
                1: {"err_msg": "", "join_at": "2026-09-08 18:30:00"},
                2: {"err_msg": "", "join_at": "2026-09-08 08:15:00"},
                3: {"err_msg": "", "join_at": "2026-09-08 12:00:00"},
            },
        )
        joined = [item for item in progress["items"] if item["state"] == "joined"]
        self.assertEqual([item["key"] for item in joined], ["queen", "mteam", "ttg"])

    def test_retirement_progress_does_not_guess_missing_rules(self):
        progress = core.build_retirement_progress(
            [{"site_id": 1, "site_name": "示例", "user_level": "User"}],
        )
        self.assertEqual(progress["rule_missing"], 1)
        self.assertEqual(progress["sites"][0]["status"], "rule_missing")

    def test_retirement_progress_marks_target_level(self):
        progress = core.build_retirement_progress(
            [{
                "site_id": 1,
                "site_name": "示例",
                "user_level": "Power User",
                "join_at": "2026-01-01",
                "updated_day": "2026-09-05",
                "upload": 500,
            }],
            {"示例": {
                "retirement_level": "Power User",
                "levels": [
                    {"name": "User"},
                    {"name": "Power User", "min_join_days": 30, "min_upload": 200},
                ],
            }},
        )
        self.assertEqual(progress["retired"], 1)
        self.assertEqual(progress["sites"][0]["status"], "retired")

    def test_cafe_short_english_levels_match_correct_route(self):
        levels = core.DEFAULT_RETIREMENT_RULES["咖啡"]["levels"]
        for index, level in enumerate(levels):
            english_name = level["name"].rsplit(" ", 1)[0]
            for text in (english_name, level["name"], f"等级：{level['name']}（当前）"):
                with self.subTest(text=text):
                    self.assertEqual(core._match_level_index(text, levels), index)

    def test_cafe_new_user_is_upgrading_with_five_levels_remaining(self):
        progress = core.build_retirement_progress([{
            "site_id": 1,
            "site_name": "咖啡",
            "user_level": "User",
            "join_at": "2026-09-24",
            "updated_day": "2026-10-04",
            "download": int(7.57 * 1024**3),
            "ratio": 5.36,
            "seeding_points": 19093,
        }])
        site = progress["sites"][0]
        self.assertEqual(progress["retired"], 0)
        self.assertEqual(site["status"], "upgrading")
        self.assertEqual(site["levels_remaining"], 5)
        self.assertEqual(site["next_level"], "Power User 速溶小白")
        self.assertEqual([item["name"] for item in site["route"] if item["is_current"]],
                         ["User 咖啡新人"])

    def test_level_matching_preserves_exact_alias_and_specific_contained_name(self):
        levels = [
            {"name": "User"},
            {"name": "Power User", "aliases": ["资深用户"]},
            {"name": "Ultimate User 咖啡巨星"},
        ]
        for text, expected in (("User", 0), ("资深用户", 1), ("等级：Power User（当前）", 1),
                               ("", -1), ("未知等级", -1)):
            with self.subTest(text=text):
                self.assertEqual(core._match_level_index(text, iter(levels)), expected)
        self.assertEqual(core._match_level_index("User", levels[1:]), 0)

    def test_retirement_target_does_not_use_substring_matching(self):
        result = core.build_retirement_progress(
            [{"site_name": "示例", "user_level": "Power User"}],
            {"示例": {"retirement_level": "User", "levels": [{"name": "Power User"}]}},
        )
        self.assertEqual(result["sites"][0]["status"], "rule_missing")

    def test_retirement_alias_normalizes_case_and_punctuation(self):
        result = core.build_retirement_progress(
            [{"site_name": "示例", "user_level": "Veteran User"}],
            {"示例": {
                "retirement_level": " KEEP-ACCOUNT ",
                "levels": [{"name": "User"}, {"name": "Veteran User", "aliases": ["Keep Account"]}],
            }},
        )
        self.assertEqual(result["sites"][0]["status"], "retired")
        self.assertEqual(result["sites"][0]["retirement_level"], "Veteran User")

    def test_fixed_source_rules_include_queen_alternatives_and_ttg(self):
        self.assertEqual(len(site_rules_builtin.SITE_LEVEL_RULES), 234)
        self.assertEqual(
            site_rules_builtin.SOURCE_COMMIT,
            "7480ca57a96254680c47bed2b1f74bacb6018f42",
        )
        self.assertEqual(len(core.DEFAULT_RETIREMENT_RULES), 196)
        queen = core.DEFAULT_RETIREMENT_RULES["皇后"]
        veteran = next(level for level in queen["levels"] if level["name"] == "Veteran User")
        self.assertEqual(queen["retirement_level"], "Veteran User")
        self.assertEqual(
            veteran["alternatives"],
            [{"min_download": 600 * core.GIB}, {"min_torrent_uploads": 200}],
        )
        self.assertEqual(core.DEFAULT_RETIREMENT_RULES["听听歌"]["retirement_level"], "BrontoByte")
        home_source = next(rule for rule in site_rules_builtin.SITE_LEVEL_RULES if rule["name"] == "家园")
        self.assertTrue(all("nameAka" not in level for level in home_source["levels"]))
        self.assertTrue(all(not level["aliases"] for level in core.DEFAULT_RETIREMENT_RULES["家园"]["levels"]))

    def test_moviepilot_site_names_match_fixed_source_rules(self):
        adapter = sys.modules["ptdatastatistics.site_rule_adapter"]
        expected_aliases = {
            "Monikadesign": ("莫妮卡",),
            "MyPT": ("我的PT",),
            "传道院": ("修道院",),
            "PTTime": ("PT时间",),
        }
        for source_name, moviepilot_names in expected_aliases.items():
            self.assertEqual(
                adapter._SITE_COMPATIBILITY_ALIASES[source_name],
                moviepilot_names,
            )

        rules = core.DEFAULT_RETIREMENT_RULES
        expected_matches = {
            "藏宝阁": "藏宝阁",
            "皇后": "皇后",
            "莫妮卡": "Monikadesign",
            "我的PT": "MyPT",
            "修道院": "传道院",
            "朱雀": "朱雀",
            "PT时间": "PTTime",
            "RailgunPT": "RailgunPT",
        }
        for moviepilot_name, source_name in expected_matches.items():
            self.assertIs(core._match_named_rule(moviepilot_name, rules), rules[source_name])

        self.assertEqual(
            {
                source_name: rules[source_name]["retirement_level"]
                for source_name in ("Monikadesign", "MyPT", "传道院", "朱雀", "PTTime")
            },
            {
                "Monikadesign": "Archivist",
                "MyPT": "Nexus Master",
                "传道院": "Nexus Master",
                "朱雀": "真仙",
                "PTTime": "Nexus Master",
            },
        )

        queen_levels = rules["皇后"]["levels"]
        for traditional_name in (
            "貴人-正六品",
            "容華-正四品",
            "貴嬪-正三品",
            "淑儀-正二品",
            "貴妃-正一品",
        ):
            self.assertGreaterEqual(core._match_level_index(traditional_name, queen_levels), 0)

        self.assertEqual(
            core._match_level_index("Power User", rules["藏宝阁"]["levels"]),
            1,
        )
        self.assertEqual(
            core._match_level_index("Power User", rules["RailgunPT"]["levels"]),
            1,
        )

    def test_rule_size_parser_uses_binary_capacity_units(self):
        adapter = sys.modules["ptdatastatistics.site_rule_adapter"]
        self.assertEqual(adapter._size_bytes("10 GB"), 10 * 1024**3)
        self.assertEqual(adapter._size_bytes("10 GiB"), 10 * 1024**3)

    def test_site_without_retirement_target_keeps_level_route(self):
        progress = core.build_retirement_progress([{
            "site_id": 1,
            "site_name": "Aither",
            "user_level": "Harmonia",
            "join_at": "2026-01-01",
            "updated_day": "2026-09-13",
        }])
        site = progress["sites"][0]
        self.assertEqual(progress["rule_missing"], 0)
        self.assertEqual(progress["upgrading"], 1)
        self.assertEqual(site["status"], "upgrading")
        self.assertEqual(site["retirement_level"], "")
        self.assertEqual(site["next_level"], "Zeus")
        self.assertEqual([level["name"] for level in site["route"]], [
            "Phobos",
            "Harmonia",
            "Zeus",
            "Helios",
            "Prometheus",
            "Oceanus",
            "Gigantes",
            "Titan",
        ])
        self.assertFalse(any(level["is_retirement"] for level in site["route"]))

        highest = core.build_retirement_progress([{
            "site_id": 1,
            "site_name": "Aither",
            "user_level": "Titan",
            "updated_day": "2026-09-13",
        }])
        self.assertEqual(highest["upgrading"], 1)
        self.assertEqual(highest["sites"][0]["status"], "upgrading")
        self.assertEqual(highest["sites"][0]["next_level"], "")

    def test_user_supplied_rules_update_eight_site_names(self):
        rules = core.DEFAULT_RETIREMENT_RULES
        spring = rules["春天"]
        self.assertNotIn("不可说", spring["aliases"])
        self.assertEqual(spring["retirement_level"], "传说(Legend)")
        spring_elite = next(level for level in spring["levels"] if level["source_id"] == 2)
        self.assertIsNone(spring_elite["min_download"])
        self.assertEqual(spring_elite["min_join_days"], 35)
        self.assertEqual(len(spring_elite["alternatives"]), 4)
        self.assertTrue(spring_elite["alternatives"][0]["min_download_strict"])
        self.assertEqual(spring_elite["alternatives"][0]["min_download"], 500 * 1024**3)
        self.assertEqual(spring_elite["alternatives"][2]["unsupported_requirements"][0]["target"], "> 2048 GB")
        self.assertTrue(spring_elite["min_ratio_strict"])
        self.assertTrue(spring_elite["alternatives"][0]["min_torrent_uploads_strict"])
        spring_immortal = next(level for level in spring["levels"] if level["source_id"] == 5)
        self.assertEqual(len(spring_immortal["alternatives"]), 2)
        self.assertEqual(
            [item["target"] for item in spring_immortal["alternatives"][0]["unsupported_requirements"]],
            ["不少于 300 GB", "前 65 名"],
        )
        self.assertEqual(
            spring_immortal["alternatives"][1]["unsupported_requirements"][0]["target"],
            "前 15 名",
        )
        spring_progress = core.build_retirement_progress([{
            "site_id": 1,
            "site_name": "春天",
            "user_level": "神仙(God)",
            "updated_day": "2026-09-12",
        }])
        spring_site = spring_progress["sites"][0]
        immortal_route = next(level for level in spring_site["route"] if level["name"] == "神王(Immortal)")
        self.assertEqual(spring_site["status"], "upgrading")
        self.assertEqual(spring_site["next_level"], "神王(Immortal)")
        self.assertEqual(len(immortal_route["alternatives"]), 2)
        self.assertTrue(any("任选条件未达成" in item for item in immortal_route["missing"]))
        spring_statuses = core.build_retirement_progress([
            {"site_id": 1, "site_name": "春天", "user_level": "神王(Immortal)", "updated_day": "2026-10-04"},
            {"site_id": 2, "site_name": "春天", "user_level": "传说(Legend)", "updated_day": "2026-10-04"},
        ])
        self.assertEqual(spring_statuses["sites"][0]["status"], "upgrading")
        self.assertEqual(spring_statuses["sites"][0]["next_level"], "传说(Legend)")
        self.assertEqual(spring_statuses["sites"][1]["status"], "retired")
        self.assertEqual([item["name"] for item in spring["vip_levels"]], ["荣誉会员(Honor)"])
        snapshot = {"join_at": "2026-08-01", "updated_day": "2026-10-04", "ratio": 1.3, "download": 501 * 1024**3, "seeding_points": 150_000, "torrent_uploads": 0}
        self.assertEqual(core._requirement_missing(spring_elite, snapshot), [])
        snapshot["download"] = 500 * 1024**3
        self.assertTrue(core._requirement_missing(spring_elite, snapshot))
        snapshot["download"] = 501 * 1024**3
        snapshot["seeding_points"] = 100_000
        snapshot["torrent_uploads"] = 1
        self.assertTrue(core._requirement_missing(spring_elite, snapshot))
        snapshot["torrent_uploads"] = 2
        self.assertEqual(core._requirement_missing(spring_elite, snapshot), [])
        snapshot["join_at"] = "2026-08-31"
        self.assertTrue(core._requirement_missing(spring_elite, snapshot))
        snapshot["join_at"] = "2026-08-30"
        self.assertEqual(core._requirement_missing(spring_elite, snapshot), [])
        for source_id, download, real_download, points, uploads, points_only, ratio in (
            (3, 1024**4, "> 4 TB", 500_000, 100, 1_000_000, 1.2),
            (4, 3 * 1024**4, "> 12 TB", 1_200_000, 300, 2_400_000, 2),
        ):
            level = next(item for item in spring["levels"] if item["source_id"] == source_id)
            self.assertEqual(level["min_join_days"], 35)
            self.assertEqual(level["min_ratio"], ratio)
            self.assertTrue(level["min_ratio_strict"])
            self.assertEqual(len(level["alternatives"]), 4)
            self.assertEqual(level["alternatives"][0]["min_download"], download)
            self.assertEqual(level["alternatives"][0]["min_seeding_points"], points)
            self.assertEqual(level["alternatives"][0]["min_torrent_uploads"], uploads)
            self.assertTrue(level["alternatives"][0]["min_torrent_uploads_strict"])
            self.assertEqual(level["alternatives"][1]["min_seeding_points"], points_only)
            self.assertEqual(level["alternatives"][2]["unsupported_requirements"][0]["target"], real_download)

        lolita = rules["ilolicon"]
        self.assertIn("萝莉", lolita["aliases"])
        lolita_power = next(level for level in lolita["levels"] if level["source_id"] == 3)
        self.assertIn("Power User", lolita_power["aliases"])
        self.assertTrue(lolita_power["min_ratio_strict"])
        self.assertFalse(lolita_power["min_seeding_points_strict"])

        self.assertEqual(rules["天空"]["retirement_level"], "Veteran User")
        self.assertEqual(rules["音乐乌托邦"]["retirement_level"], "Veteran User")
        music_power = next(level for level in rules["音乐乌托邦"]["levels"] if level["source_id"] == 3)
        self.assertTrue(music_power["min_ratio_strict"])
        self.assertTrue(music_power["min_seeding_points_strict"])

        depth_levels = [
            level for level in rules["Depth Studio"]["levels"]
            if level["source_id"] in range(3, 11)
        ]
        self.assertEqual(
            [level["min_ratio"] for level in depth_levels],
            [1.2, 2.55, 2.55, 3.2, 4.05, 5, 6, 7],
        )
        self.assertTrue(all(level["min_ratio_strict"] for level in depth_levels))
        self.assertTrue(all(level["min_seeding_points_strict"] for level in depth_levels))
        self.assertEqual(rules["Depth Studio"]["retirement_level"], "Nexus Master")
        self.assertEqual([level["min_join_days"] for level in depth_levels], [35, 56, 105, 175, 280, 420, 560, 700])
        self.assertEqual([level["min_seeding_points"] for level in depth_levels], [25000, 60000, 120000, 200000, 350000, 500000, 700000, 1000000])
        self.assertEqual([level["min_download"] for level in depth_levels], [50 * 1024**3, 120 * 1024**3, 300 * 1024**3, 500 * 1024**3, 750 * 1024**3, 1024**4, 1.5 * 1024**4, 3 * 1024**4])
        self.assertNotIn("封存", depth_levels[1]["description"])
        self.assertNotIn("永远", depth_levels[4]["description"])
        self.assertIn("封存账号后不会被删除", depth_levels[5]["description"])
        self.assertIn("永远保留账号", depth_levels[7]["description"])
        depth_progress = core.build_retirement_progress([
            {"site_id": 1, "site_name": "Depth Studio", "user_level": "Veteran User", "updated_day": "2026-10-04"},
            {"site_id": 2, "site_name": "Depth Studio", "user_level": "Nexus Master", "updated_day": "2026-10-04"},
        ])
        self.assertEqual(depth_progress["sites"][0]["status"], "upgrading")
        self.assertEqual(depth_progress["sites"][0]["retirement_level"], "Nexus Master")
        self.assertEqual(depth_progress["sites"][1]["status"], "retired")

        ggpt_power = next(level for level in rules["GGPT"]["levels"] if level["source_id"] == 1)
        self.assertFalse(ggpt_power["min_ratio_strict"])
        self.assertTrue(ggpt_power["min_seeding_points_strict"])

        zimiao = rules["梓喵"]
        self.assertEqual(zimiao["retirement_level"], "Nexus Master")
        self.assertEqual(len(zimiao["levels"]), 9)
        self.assertEqual(
            [level["min_seeding_points"] for level in zimiao["levels"][1:]],
            [40_000, 100_000, 300_000, 500_000, 1_000_000, 1_500_000, 2_000_000, 5_000_000],
        )
        self.assertEqual(
            [level["min_torrent_uploads"] for level in zimiao["levels"][1:]],
            [1, 5, 10, 20, 40, 80, 150, 200],
        )
        self.assertTrue(all(level["min_ratio_strict"] for level in zimiao["levels"][1:]))
        self.assertTrue(all(level["min_seeding_points_strict"] for level in zimiao["levels"][1:]))

    def test_alternative_requirement_accepts_either_available_branch(self):
        level = {
            "alternatives": [
                {"min_download": 600_000_000_000},
                {"min_torrent_uploads": 200},
            ]
        }
        self.assertEqual(
            core._requirement_missing(level, {"download": 600_000_000_000}),
            [],
        )
        missing = core._requirement_missing(level, {"download": 1})
        self.assertTrue(any("任选条件未达成" in item for item in missing))
        self.assertTrue(any("发布数数据未提供" in item for item in missing))

    def test_audiences_retirement_rules_match_published_level_route(self):
        progress = core.build_retirement_progress(
            [{
                "site_id": 1,
                "site_name": "观众",
                "user_level": "User",
                "join_at": "2026-07-03 18:19:19",
                "updated_day": "2026-09-06",
                "download": 50 * core.GIB,
                "ratio": 1.5,
                "bonus": 50_000,
            }],
        )
        site = progress["sites"][0]
        levels = {level["name"]: level for level in site["route"]}

        self.assertEqual(site["status"], "upgrading")
        self.assertEqual(site["retirement_level"], "Extreme User")
        self.assertEqual(levels["Power User"]["eligible_date"], "2026-08-07")
        self.assertEqual(levels["Power User"]["min_download"], 120 * core.GIB)
        self.assertEqual(levels["Power User"]["min_upload"], 240 * core.GIB)
        self.assertFalse(levels["Power User"]["min_upload_strict"])
        self.assertEqual(levels["Power User"]["min_ratio"], 2.0)
        self.assertFalse(levels["Power User"]["min_ratio_strict"])
        self.assertEqual(levels["Power User"]["min_seeding_points"], 100_000.0)
        self.assertIn("年轻气盛", levels["Power User"]["aliases"])
        self.assertIsNone(levels["Power User"]["min_bonus"])
        self.assertIn("做种积分数据未提供", levels["Power User"]["missing"])
        self.assertFalse(
            any("门槛" in item for item in levels["Power User"]["missing"])
        )
        self.assertIn("NFO", levels["Power User"]["description"])
        self.assertEqual(levels["Crazy User"]["eligible_date"], "2026-12-18")
        self.assertIn("可以查看排行榜", levels["Crazy User"]["description"])
        self.assertEqual(levels["Insane User"]["min_ratio"], 3.5)
        self.assertEqual(levels["Extreme User"]["min_ratio"], 4.5)
        self.assertEqual(levels["Extreme User"]["eligible_date"], "2028-01-14")
        self.assertTrue(levels["Extreme User"]["is_retirement"])
        self.assertIn("永远保留账号", levels["Extreme User"]["description"])
        self.assertEqual(levels["Rainbow"]["eligible_date"], "2028-12-15")
        self.assertIn("彩虹ID", levels["Rainbow"]["description"])

    def test_audiences_ratio_threshold_uses_bundled_rule_value(self):
        progress = core.build_retirement_progress(
            [{
                "site_id": 1,
                "site_name": "观众",
                "user_level": "User",
                "join_at": "2026-01-01",
                "updated_day": "2026-12-31",
                "download": 120 * core.GIB,
                "ratio": 2.0,
                "seeding_points": 100_000,
            }],
        )
        power = next(
            level
            for level in progress["sites"][0]["route"]
            if level["name"] == "Power User"
        )
        self.assertFalse(any("分享率" in item for item in power["missing"]))

    def test_audiences_points_eta_matches_ptd_remaining_hours(self):
        progress = core.build_retirement_progress(
            [{
                "site_id": 1,
                "site_name": "观众",
                "user_level": "User",
                "join_at": "2026-01-01",
                "updated_day": "2026-09-11",
                "download": 200 * core.GIB,
                "upload": 500 * core.GIB,
                "ratio": 3,
                "seeding_points": 70_260,
                "seeding_points_hourly": 42.85,
            }],
        )

        power = next(
            level for level in progress["sites"][0]["route"]
            if level["name"] == "Power User"
        )
        self.assertEqual(power["seeding_points_eta_hours"], 694)
        self.assertEqual(power["seeding_points_eta_days"], 29)
        self.assertEqual(power["seeding_points_eta_date"], "2026-10-10")

    def test_cat_alternative_tasks_have_separate_points_eta(self):
        progress = core.build_retirement_progress([{
            "site_id": 1,
            "site_name": "猫站",
            "user_level": "加菲猫 POWER USER",
            "join_at": "2026-01-01",
            "updated_day": "2026-09-24",
            "seeding_points": 200_000,
            "seeding_points_hourly": 1_000,
        }])
        ultimate = next(
            level for level in progress["sites"][0]["route"]
            if level["name"] == "山东狮子猫 ULTIMATE USER"
        )
        first, second = ultimate["alternatives"]
        self.assertEqual(first["seeding_points_eta_days"], 42)
        self.assertEqual(first["seeding_points_eta_date"], "2026-11-05")
        self.assertEqual(second["seeding_points_eta_days"], 142)
        self.assertEqual(second["seeding_points_eta_date"], "2027-02-13")

    def test_audiences_seeding_points_gap_uses_readable_integer_format(self):
        missing = core._requirement_missing(
            {"min_seeding_points": 1_500_000},
            {"seeding_points": 70_260},
        )

        self.assertIn("做种积分剩余 1,429,740", missing)
        self.assertFalse(any("e+" in item.casefold() for item in missing))

    def test_strict_seeding_points_at_threshold_does_not_report_zero_gap(self):
        missing = core._requirement_missing(
            {
                "min_seeding_points": 80_000,
                "min_seeding_points_strict": True,
            },
            {"seeding_points": 80_000},
        )

        self.assertIn("做种积分需大于 80,000", missing)
        self.assertNotIn("做种积分剩余 0", missing)

    def test_mteam_retirement_rules_match_published_level_route(self):
        progress = core.build_retirement_progress(
            [{
                "site_id": 1,
                "site_name": "馒头",
                "user_level": "小卒 / User",
                "join_at": "2026-01-01",
                "updated_day": "2026-01-29",
                "download": 200 * core.GIB,
                "ratio": 2,
            }],
        )
        site = progress["sites"][0]
        levels = {level["name"]: level for level in site["route"]}

        self.assertEqual(site["status"], "upgrading")
        self.assertEqual(site["retirement_level"], "Extreme User")
        self.assertEqual(site["next_level"], "Power User")
        self.assertEqual(levels["Power User"]["eligible_date"], "2026-01-29")
        self.assertEqual(levels["Power User"]["min_download"], 200 * core.GIB)
        self.assertEqual(levels["Power User"]["min_upload"], 400 * core.GIB)
        self.assertFalse(levels["Power User"]["min_join_days_strict"])
        self.assertFalse(levels["Power User"]["min_upload_strict"])
        self.assertFalse(levels["Power User"]["min_download_strict"])
        self.assertFalse(levels["Power User"]["min_ratio_strict"])
        self.assertFalse(any("账号时间" in item for item in levels["Power User"]["missing"]))
        self.assertFalse(any("下载" in item for item in levels["Power User"]["missing"]))
        self.assertTrue(any(item.startswith("上传剩余 ") for item in levels["Power User"]["missing"]))
        self.assertFalse(any("分享率" in item for item in levels["Power User"]["missing"]))
        self.assertTrue(levels["Extreme User"]["is_retirement"])
        self.assertIn("+6%", levels["Extreme User"]["description"])
        self.assertEqual(levels["mTorrent Master"]["min_join_days"], 224)
        self.assertEqual(levels["mTorrent Master"]["min_download"], 3000 * core.GIB)

    def test_bundled_mteam_rule_matches_legacy_site_and_level_aliases(self):
        progress = core.build_retirement_progress(
            [{
                "site_id": 1,
                "site_name": "M-Team 馒头",
                "user_level": "府尹",
                "join_at": "2025-01-01",
                "updated_day": "2026-09-08",
            }],
        )

        site = progress["sites"][0]
        self.assertEqual(site["status"], "retired")
        self.assertEqual(site["current_level"], "府尹")
        self.assertTrue(next(level for level in site["route"] if level["name"] == "Extreme User")["is_current"])

    def test_vip_level_is_shown_as_wealthy_retirement(self):
        progress = core.build_retirement_progress(
            [{
                "site_id": 1,
                "site_name": "馒头",
                "user_level": "VIP",
                "updated_day": "2026-09-12",
            }],
        )

        site = progress["sites"][0]
        self.assertEqual(progress["retired"], 0)
        self.assertEqual(progress["wealthy_retired"], 1)
        self.assertEqual(progress["rule_missing"], 0)
        self.assertEqual(site["status"], "wealthy_retired")
        self.assertTrue(site["is_vip"])
        self.assertEqual(site["current_level"], "VIP")

    def test_level_above_retirement_keeps_next_level_progress(self):
        progress = core.build_retirement_progress(
            [{
                "site_id": 1,
                "site_name": "馒头",
                "user_level": "Ultimate User",
                "join_at": "2025-01-01",
                "updated_day": "2026-09-12",
            }],
        )

        site = progress["sites"][0]
        self.assertEqual(site["status"], "retired")
        self.assertEqual(site["next_level"], "mTorrent Master")
        self.assertTrue(any(level["name"] == "mTorrent Master" for level in site["route"]))

    def test_hhan_retirement_rules_keep_seeding_points_distinct_from_bonus(self):
        progress = core.build_retirement_progress(
            [{
                "site_id": 1,
                "site_name": "憨憨",
                "user_level": "憨头憨脑 User",
                "join_at": "2026-01-01",
                "updated_day": "2026-09-11",
                "upload": 100 * core.GIB,
                "download": 60 * core.GIB,
                "ratio": 1.1,
                "bonus": 9_999_999,
                "seeding_points": 79_999,
                "seeding_points_hourly": 10,
            }],
        )
        site = progress["sites"][0]
        levels = {level["name"]: level for level in site["route"]}
        named = lambda suffix: next(level for name, level in levels.items() if name.endswith(suffix))

        self.assertTrue(site["next_level"].endswith("Power User"))
        self.assertTrue(site["retirement_level"].endswith("Nexus Master"))
        self.assertEqual(named("Power User")["min_seeding_points"], 80_000)
        self.assertFalse(named("Power User")["min_seeding_points_strict"])
        self.assertIsNone(named("Power User")["min_bonus"])
        self.assertIn("做种积分剩余 1", named("Power User")["missing"])
        self.assertFalse(any("魔力" in item for item in named("Power User")["missing"]))
        self.assertEqual(named("Power User")["min_upload"], int(52.5 * core.GIB))
        self.assertEqual(
            [named(name)["min_seeding_points"] for name in (
                "Power User", "Elite User", "Crazy User", "Insane User",
                "Veteran User", "Extreme User", "Ultimate User", "Nexus Master",
            )],
            [80_000, 150_000, 300_000, 500_000, 900_000, 1_100_000, 1_300_000, 1_500_000],
        )
        self.assertTrue(all(
            named(name)["min_bonus"] is None
            for name in (
                "Power User", "Elite User", "Crazy User", "Insane User",
                "Veteran User", "Extreme User", "Ultimate User", "Nexus Master",
            )
        ))
        self.assertFalse(named("Ultimate User")["is_retirement"])
        self.assertTrue(named("Nexus Master")["is_retirement"])
        self.assertEqual(named("Power User")["seeding_points_eta_days"], 1)
        self.assertEqual(named("Power User")["seeding_points_eta_date"], "2026-09-12")
        self.assertEqual(named("Power User")["seeding_points_eta_hours"], 0)

    def test_hhan_retirement_requires_nexus_master(self):
        rule = core.DEFAULT_RETIREMENT_RULES["憨憨"]
        self.assertEqual(rule["retirement_level"], "满面娇憨 Nexus Master")
        ultimate = next(level for level in rule["levels"] if level["source_id"] == 7)
        self.assertNotIn("永远保留", ultimate["description"])
        progress = core.build_retirement_progress([
            {"site_id": 1, "site_name": "憨憨", "user_level": "Ultimate User", "updated_day": "2026-10-04"},
            {"site_id": 2, "site_name": "HHanClub", "user_level": "Nexus Master", "updated_day": "2026-10-04"},
        ])
        self.assertEqual(progress["sites"][0]["status"], "upgrading")
        self.assertEqual(progress["sites"][0]["next_level"], "满面娇憨 Nexus Master")
        self.assertEqual(progress["sites"][1]["status"], "retired")

    def test_hhan_points_eta_never_uses_magic_rate(self):
        progress = core.build_retirement_progress(
            [{
                "site_id": 1,
                "site_name": "憨憨",
                "user_level": "憨头憨脑 User",
                "join_at": "2026-01-01",
                "updated_day": "2026-09-11",
                "upload": 100 * core.GIB,
                "download": 60 * core.GIB,
                "ratio": 1.1,
                "bonus": 999_999,
                "estimated_bonus_hourly": 10_000,
                "seeding_points": 56_000,
                "seeding_points_hourly": 100,
            }],
        )

        power = next(
            level for level in progress["sites"][0]["route"]
            if level["name"].endswith("Power User")
        )
        self.assertEqual(power["seeding_points_eta_days"], 10)
        self.assertEqual(power["seeding_points_eta_date"], "2026-09-21")

    def test_home_retirement_rules_match_published_requirements(self):
        progress = core.build_retirement_progress(
            [{
                "site_id": 1,
                "site_name": "家园",
                "user_level": "(士兵)User",
                "join_at": "2026-01-01",
                "updated_day": "2026-09-11",
                "upload": 0,
                "download": 0,
                "ratio": 0,
                "bonus": 99_999_999,
                "seeding_points": 0,
            }],
        )
        site = progress["sites"][0]
        levels = {level["name"]: level for level in site["route"]}
        ordered = (
            "Power User", "Elite User", "Crazy User", "Insane User",
            "Veteran User", "Extreme User", "Ultimate User", "Nexus Master",
        )

        self.assertEqual(site["next_level"], "Power User")
        self.assertEqual(site["retirement_level"], "Nexus Master")
        self.assertEqual(site["current_level"], "(士兵)User")
        self.assertEqual(
            [levels[name]["min_join_days"] for name in ordered],
            [35, 56, 84, 112, 140, 168, 210, 252],
        )
        self.assertEqual(
            [levels[name]["min_download"] for name in ordered],
            [256 * core.GIB, 386 * core.GIB, 512 * core.GIB, 768 * core.GIB,
             1024 * core.GIB, 2048 * core.GIB, 8192 * core.GIB, 10240 * core.GIB],
        )
        self.assertEqual(
            [levels[name]["min_seeding_points"] for name in ordered],
            [40_000, 100_000, 180_000, 280_000,
             400_000, 540_000, 700_000, 1_000_000],
        )
        self.assertTrue(all(levels[name]["min_bonus"] is None for name in ordered))
        self.assertEqual(levels["Power User"]["min_upload"], 512 * core.GIB)
        self.assertEqual(levels["Nexus Master"]["min_upload"], 100 * 1024**4)
        self.assertTrue(levels["Nexus Master"]["is_retirement"])

    def test_hdfans_retirement_rules_use_seeding_points_not_bonus(self):
        progress = core.build_retirement_progress(
            [{
                "site_id": 1,
                "site_name": "红豆饭 HDFans",
                "user_level": "User",
                "join_at": "2026-01-01",
                "updated_day": "2026-09-11",
                "upload": 0,
                "download": 0,
                "ratio": 0,
                "bonus": 9_999_999,
                "seeding_points": 0,
            }],
        )
        site = progress["sites"][0]
        levels = {level["name"]: level for level in site["route"]}
        ordered = (
            "Power User", "Elite User", "Crazy User", "Insane User",
            "Veteran User", "Extreme User", "Ultimate User", "Nexus Master",
        )

        self.assertEqual(site["next_level"], "Power User")
        self.assertEqual(site["retirement_level"], "Extreme User")
        self.assertEqual(
            [levels[name]["min_join_days"] for name in ordered],
            [28, 56, 105, 210, 280, 350, 420, 700],
        )
        self.assertEqual(
            [levels[name]["min_download"] for name in ordered],
            [50 * core.GIB, 120 * core.GIB, 256 * core.GIB, 512 * core.GIB,
             1024 * core.GIB, 2048 * core.GIB, 4096 * core.GIB, 10240 * core.GIB],
        )
        self.assertEqual(
            [levels[name]["min_seeding_points"] for name in ordered],
            [50_000, 100_000, 250_000, 400_000,
             600_000, 800_000, 1_000_000, 1_688_888],
        )
        self.assertTrue(all(levels[name]["min_bonus"] is None for name in ordered))
        self.assertEqual(levels["Power User"]["min_upload"], 50 * core.GIB)
        self.assertEqual(levels["Extreme User"]["min_upload"], 7 * 1024**4)
        self.assertTrue(levels["Extreme User"]["is_retirement"])

    def test_kylin_retirement_rules_match_published_requirements(self):
        progress = core.build_retirement_progress(
            [{
                "site_id": 1,
                "site_name": "麒麟",
                "user_level": "草塘结庐/User",
                "join_at": "2026-01-01",
                "updated_day": "2026-09-11",
                "upload": 0,
                "download": 0,
                "ratio": 0,
                "bonus": 9_999_999,
                "seeding_points": 0,
            }],
        )
        site = progress["sites"][0]
        levels = {level["name"]: level for level in site["route"]}
        ordered = (
            "Power User", "Elite User", "Crazy User", "Insane User",
            "Veteran User", "Extreme User", "Ultimate User", "Nexus Master",
        )

        self.assertEqual(site["next_level"], "Power User")
        self.assertEqual(site["retirement_level"], "Veteran User")
        self.assertEqual(
            [levels[name]["min_join_days"] for name in ordered],
            [28, 56, 105, 175, 280, 420, 560, 700],
        )
        self.assertEqual(
            [levels[name]["min_download"] for name in ordered],
            [50 * core.GIB, 120 * core.GIB, 300 * core.GIB, 500 * core.GIB,
             750 * core.GIB, 1024 * core.GIB, 4096 * core.GIB, 10240 * core.GIB],
        )
        self.assertEqual(
            [levels[name]["min_ratio"] for name in ordered],
            [2, 3, 4, 5, 6, 7, 8, 10],
        )
        self.assertEqual(
            [levels[name]["min_seeding_points"] for name in ordered],
            [40_000, 80_000, 150_000, 250_000,
             400_000, 600_000, 800_000, 1_000_000],
        )
        self.assertTrue(all(levels[name]["min_bonus"] is None for name in ordered))
        self.assertEqual(levels["Power User"]["min_upload"], 100 * core.GIB)
        self.assertEqual(levels["Veteran User"]["min_upload"], 4500 * core.GIB)
        self.assertTrue(levels["Veteran User"]["is_retirement"])

    def test_audiences_rule_matches_decorated_site_and_level_names(self):
        progress = core.build_retirement_progress(
            [{
                "site_id": 1,
                "site_name": "观众 Audiences",
                "user_level": "Power User（同年轻气盛）",
                "join_at": "2026-07-03 18:19:19",
                "updated_day": "2026-09-06",
            }],
        )
        site = progress["sites"][0]

        self.assertEqual(site["status"], "upgrading")
        self.assertEqual(site["next_level"], "Elite User")
        self.assertTrue(next(level for level in site["route"] if level["name"] == "Power User")["is_current"])

    def test_known_site_keeps_route_when_mp_level_is_unknown(self):
        progress = core.build_retirement_progress(
            [{
                "site_id": 1,
                "site_name": "观众",
                "user_level": "站点暂未返回等级",
                "join_at": "2026-07-03 18:19:19",
                "updated_day": "2026-09-06",
            }],
        )
        site = progress["sites"][0]

        self.assertEqual(site["status"], "rule_missing")
        self.assertEqual(site["retirement_level"], "Extreme User")
        self.assertEqual(len(site["route"]), 10)

    def test_uploaded_rule_matches_site_domain_when_display_name_differs(self):
        rule = {
            "_custom_rule": True,
            "retirement_level": "Nexus Master",
            "levels": [
                {"name": "User"},
                {"name": "Power User"},
                {"name": "Nexus Master"},
            ],
        }
        progress = core.build_retirement_progress(
            [{
                "site_id": 1,
                "site_name": "我的猫站",
                "domain": "pterclub.com",
                "user_level": "POWER_USER",
                "updated_day": "2026-09-12",
            }],
            {"pterclub.com": rule},
        )
        site = progress["sites"][0]

        self.assertEqual(site["status"], "upgrading")
        self.assertEqual(site["next_level"], "Nexus Master")
        self.assertEqual(len(site["route"]), 3)

    def test_manual_wealthy_retirement_matches_domain_without_level_rule(self):
        progress = core.build_retirement_progress(
            [{
                "site_id": 9,
                "site_name": "自定义会员站",
                "domain": "vip.example",
                "user_level": "Donor",
                "updated_day": "2026-09-12",
            }],
            {},
            ["vip.example"],
        )

        site = progress["sites"][0]
        self.assertEqual(progress["wealthy_retired"], 1)
        self.assertEqual(progress["rule_missing"], 0)
        self.assertEqual(site["status"], "wealthy_retired")
        self.assertTrue(site["wealthy_retirement_manual"])
        self.assertFalse(site["is_vip"])

    def test_vip_only_rule_uses_domain_alias_for_wealthy_retirement(self):
        progress = core.build_retirement_progress(
            [{
                "site_name": "IPT",
                "domain": "iptorrents.com",
                "user_level": "VIP",
                "updated_day": "2026-09-12",
            }],
        )

        self.assertEqual(progress["wealthy_retired"], 1)
        self.assertEqual(progress["sites"][0]["status"], "wealthy_retired")


class PackagingTests(unittest.TestCase):
    def test_shared_manifest_matches_source(self):
        manifest = json.loads((ROOT / "package.v2.json").read_text(encoding="utf-8"))
        meta = manifest["PTDataStatistics"]
        source = (PLUGIN / "__init__.py").read_text(encoding="utf-8")
        self.assertIn(f'plugin_version = "{meta["version"]}"', source)
        self.assertIn(f'v{meta["version"]}', meta["history"])
        self.assertEqual(meta["history"][f'v{meta["version"]}'], "不值一提")
        frontend_meta = json.loads((PLUGIN / "package.json").read_text(encoding="utf-8"))
        self.assertEqual(frontend_meta["version"], meta["version"])
        icon_url = "https://raw.githubusercontent.com/changzhanghs/MoviePilot-Plugins/main/icons/ptdatastatistics.png"
        self.assertEqual(meta["icon"], icon_url)
        self.assertIn(f'plugin_icon = "{icon_url}"', source)
        icon_png = (ROOT / "icons" / "ptdatastatistics.png").read_bytes()
        self.assertTrue(icon_png.startswith(b"\x89PNG\r\n\x1a\n"))
        self.assertGreater(len(icon_png), 1024)
        icon = (ROOT / "icons" / "ptdatastatistics.svg").read_text(encoding="utf-8")
        self.assertIn('aria-label="PT数据统计"', icon)
        self.assertIn('fill="#ffc83d"', icon)
        self.assertEqual(meta["system_version"], ">=2.12.0")
        self.assertIsNot(meta.get("v3"), False)
        self.assertNotIn("release", meta)

    def test_plugin_source_does_not_read_downloaders_or_pt_sites(self):
        source = (PLUGIN / "__init__.py").read_text(encoding="utf-8")
        self.assertNotIn("Downloader", source)
        self.assertNotIn("requests.", source)
        self.assertIn("SiteOper", source)

    def test_federation_exposes_all_components(self):
        source = (PLUGIN / "vite.config.js").read_text(encoding="utf-8")
        for name in ("./Page", "./Config", "./Dashboard", "./AppPage"):
            self.assertIn(name, source)

    def test_federation_components_accept_runtime_instance_props(self):
        for filename in ("Page.vue", "Config.vue", "Dashboard.vue", "AppPage.vue"):
            source = (PLUGIN / "src" / "components" / filename).read_text(encoding="utf-8")
            self.assertIn("pluginId", source, filename)
            self.assertIn("sourcePluginId", source, filename)
            self.assertIn("nativeSubscribe", source, filename)
        config = (PLUGIN / "src" / "components" / "Config.vue").read_text(encoding="utf-8")
        self.assertIn("initialConfig", config)
        self.assertIn("'save'", config)

    def test_workbench_ui_polish_contract(self):
        source = (PLUGIN / "src" / "components" / "PTStatsWorkbench.vue").read_text(
            encoding="utf-8"
        )
        self.assertIn("item.state === 'joined' && item.site_id", source)
        self.assertIn('v-if="item.state === \'joined\'" class="twelve-node__name"', source)
        self.assertNotIn('class="twelve-node__date"', source)
        self.assertNotIn("item.state === 'joined' ? item.name : '未解锁'", source)
        self.assertNotIn('class="twelve-node__latest"', source)
        self.assertNotIn('>最近加入</span>', source)
        self.assertIn('class="twelve-remaining">剩余', source)
        self.assertNotIn(":hint=\"`服务器日期 ${overview.server_date || '—'}`\"", source)
        self.assertNotIn("查询数据</VBtn>", source)
        self.assertIn(":label=\"panel.inputLabel\"", source)
        self.assertIn(":prepend-inner-icon=\"panel.icon\"", source)
        self.assertIn(':model-value="distributionFilters[panel.dateKey]"', source)
        self.assertIn('@click="openNativePicker"', source)
        self.assertIn('@update:model-value="value => updateDistributionFilter(panel.dateKey, value)"', source)
        self.assertIn("distributionRequestSequence", source)
        self.assertIn("const historyGroups = computed", source)
        self.assertIn("const selectedHistoryPeriod = computed", source)
        self.assertIn("selectHistoryPeriod(period)", source)
        self.assertIn("const selectedPeriodSites = computed", source)
        self.assertIn("selectHistorySite(item)", source)
        self.assertIn("Chart from 'chart.js/auto'", source)
        self.assertIn("history/hourly", source)
        self.assertNotIn("站点贡献", source)
        self.assertIn('class="history-console"', source)
        self.assertIn('class="history-period-strip"', source)
        self.assertIn('class="history-workspace"', source)
        self.assertIn('class="history-site-sidebar"', source)
        self.assertIn('class="history-site-sidebar__items"', source)
        self.assertIn('class="history-workspace__main"', source)
        self.assertIn('@click="selectHistorySite(null)"', source)
        self.assertNotIn('class="history-site-expansion"', source)
        self.assertNotIn('v-model="historyMetric"', source)
        self.assertNotIn('label="站点范围"', source)
        self.assertNotIn('class="history-toolbar"', source)
        self.assertNotIn('class="history-toolbar-secondary"', source)
        self.assertNotIn('class="history-detail-summary__title"', source)
        self.assertIn('class="history-summary-scope"', source)
        self.assertNotIn('class="history-period-scope"', source)
        self.assertLess(source.index('class="history-summary-scope"'), source.index('class="history-detail-metrics"'))
        self.assertLess(source.index('class="history-detail-summary"'), source.index('class="history-site-sidebar"'))
        self.assertIn("if (value === 'history' && !(history.value.records || []).length) loadHistory()", source)
        self.assertIn("选择左侧站点可查看该站点历史数据", source)
        self.assertIn("const selectedHistoryRecords = computed", source)
        self.assertIn('class="history-record-table"', source)
        self.assertIn("<th>日期</th><th>累计上传</th><th>累计下载</th>", source)
        self.assertNotIn("<th>账号质量</th>", source)
        self.assertNotIn("<th>积分 / 魔力</th>", source)
        self.assertNotIn("<th>做种数 / 体积</th>", source)
        self.assertIn("<th>分享率</th><th>魔力</th><th>做种数</th><th>做种体积</th>", source)
        self.assertIn("小时曲线至少需要同一站点在当天产生 2 次数据刷新", source)
        self.assertIn('<span><i class="legend__upload" />上传</span>', source)
        self.assertIn('<span><i class="legend__download" />下载</span>', source)
        self.assertNotIn("history-line-chart--expanded", source)
        self.assertIn('>数据统计</VTab>', source)
        self.assertNotIn(">数据刷新</VBtn>", source)
        self.assertNotIn("syncFromMP", source)
        self.assertIn("暂无历史数据，请等待 MoviePilot 站点刷新", source)
        self.assertNotIn("重新读取 MP 数据", source)
        self.assertNotIn('<header class="hero">', source)
        self.assertLess(source.index('value="retirement"'), source.index('value="history"'))
        self.assertIn('class="site-data-list"', source)
        self.assertNotIn("服务器日期 {{ overview.server_date", source)
        self.assertIn('class="site-stat-grid"', source)
        self.assertIn(".site-stat-grid{display:grid;grid-template-columns:repeat(10,minmax(0,1fr))", source)
        self.assertIn(".site-stat-grid{grid-template-columns:repeat(5,minmax(0,1fr))}", source)
        self.assertIn(".site-stat-grid{grid-template-columns:repeat(2,minmax(0,1fr))}", source)
        self.assertIn("<span>魔力</span>", source)
        self.assertIn("<span>预估时魔</span>", source)
        self.assertNotIn("魔力（预估时魔）", source)
        self.assertIn("const siteSortOptions", source)
        self.assertIn("const siteSortKey = ref('site_priority')", source)
        self.assertEqual(source.count("{ title: '加入时间', value: 'join_at' }"), 2)
        self.assertIn("if (key === 'join_at')", source)
        for key in ("site_priority", "upload", "download", "bonus", "seeding", "seeding_size"):
            self.assertIn(f"value: '{key}'", source)
        self.assertIn("title: '站点优先级'", source)
        self.assertIn('v-for="site in sortedCurrentSites"', source)
        self.assertIn("bonusValue(item.bonus)", source)
        self.assertNotIn("<th>站点</th><th>数据日期</th>", source)
        self.assertIn("site.join_at?.slice(0, 10)", source)
        self.assertIn('@click="openNativePicker"', source)
        self.assertIn("current: complete ? '达成'", source)
        self.assertIn("currentDays} 天", source)
        self.assertNotIn("注册时间已达成", source)
        self.assertIn('class="retirement-explorer"', source)
        self.assertIn('class="retirement-site-list"', source)
        self.assertIn("const retirementSortOptions", source)
        self.assertIn("const sortedRetirementSites = computed", source)
        self.assertIn('v-model="retirementSortKey"', source)
        self.assertIn('class="retirement-site-sort"', source)
        self.assertIn('v-for="site in sortedRetirementSites"', source)
        self.assertLess(source.index('class="retirement-site-list__heading"'), source.index('class="retirement-site-sort"'))
        self.assertLess(source.index('class="retirement-site-sort"'), source.index('class="retirement-site-list__items"'))
        self.assertIn('@click="selectRetirementSite(site)"', source)
        self.assertIn('class="retirement-detail"', source)
        self.assertIn('class="retirement-route-rail"', source)
        self.assertIn('class="retirement-route-rail__track"', source)
        self.assertIn('v-if="selectedRetirementSite.retirement_level">目标等级', source)
        self.assertIn('aria-label="等级进度"', source)
        self.assertNotIn("等级升级中", source)
        self.assertIn("!site.retirement_level && !site.next_level", source)
        self.assertIn("--route-count", source)
        self.assertIn(".retirement-detail{min-width:0;min-height:0;overflow:visible", source)
        self.assertNotIn(".retirement-detail{min-width:0;min-height:0;overflow-y:auto", source)
        self.assertNotIn("还差", source)
        self.assertNotIn("MoviePilot 不提供站点等级门槛和保号等级", source)
        self.assertIn('class="requirement-panel"', source)
        self.assertIn("function springUpgradeTasks(site, level)", source)
        self.assertIn("{ title: '任务一', subtitle: '保种升级'", source)
        self.assertIn("{ title: '任务二', subtitle: '发种升级'", source)
        self.assertIn('class="spring-upgrade-tasks"', source)
        self.assertIn('@click="springUpgradeTaskIndex = index"', source)
        self.assertIn("const springUpgradeTaskIndex = ref(0)", source)
        self.assertIn('class="retirement-levels"', source)
        self.assertIn("selectedRetirementSite", source)
        self.assertIn("const selectedRetirementView = computed", source)
        self.assertIn('class="requirement-overview__score"', source)
        self.assertIn('class="requirement-table__head"', source)
        self.assertIn('<span>目标要求</span><span>当前进度</span><span>剩余</span><span>时间</span><span>完成进度</span>', source)
        self.assertIn("etaDate: level.seeding_points_eta_date", source)
        self.assertLess(source.index("pushNumeric({ key: 'seeding-points'"), source.index("if (joinRow) rows.push(joinRow)"))
        self.assertIn("eta: complete ? '—' : eligibleDate || '—'", source)
        self.assertIn("function nextLevelEta(site, requirements)", source)
        self.assertIn(".map(row => row.eta)", source)
        self.assertIn("row.detail.replace(/^剩余\\s*/, '')", source)
        self.assertIn('class="retirement-levels__columns"', source)
        self.assertIn('<details v-for="level in selectedRetirementView.levels"', source)
        self.assertIn("const route = retirementRoute(site)", source)
        self.assertIn("const levels = site.route || []", source)
        self.assertNotIn("route.slice(currentIndex)", source)
        self.assertIn("route.slice(userIndex)", source)
        self.assertNotIn("route.slice(0, retirementIndex + 1)", source)
        self.assertIn('class="rules-file-input"', source)
        self.assertIn("async function uploadRuleFile(event)", source)
        self.assertIn("settingsDraft.value.custom_retirement_rules = rules", source)
        self.assertIn("alignRulesToMoviePilotSites(normalizeUploadedRules(payload))", source)
        self.assertIn("return { ...rule, site: matchedName, aliases, domains }", source)
        self.assertIn('class="wealthy-selection-summary"', source)
        self.assertIn('<VDialog v-model="wealthyPickerOpen"', source)
        self.assertIn('v-model="wealthySiteSearch"', source)
        self.assertIn('class="wealthy-site-picker"', source)
        self.assertIn("已选站点优先显示", source)
        self.assertLess(source.index('class="wealthy-selection-summary"'), source.index('<VDialog v-model="wealthyPickerOpen"'))
        self.assertIn("settingsDraft.value.wealthy_retirement_sites", source)
        self.assertIn("await props.api.post(`${pluginBase.value}/settings`, payload)", source)
        self.assertIn("`${pluginBase.value}/rules/template`", source)
        self.assertIn("mteam-level-rules-template.json", source)
        self.assertIn("下载模板", source)
        self.assertLess(source.index('class="rules-upload__actions"'), source.index('class="rules-file-input"'))
        self.assertNotIn("使用内置等级规则", source)
        self.assertNotIn("自定义规则优先于同名内置规则", source)
        self.assertIn(':model-value="selectedRetirementView.routeProgress"', source)
        self.assertNotIn("待同步积分时速", source)
        self.assertIn("nextLevelOverallProgress(site)", source)
        self.assertIn("return averageRequirementProgress(requirementRows(site, nextLevel, taskIndex))", source)
        self.assertIn("status === 'wealthy_retired'", source)
        self.assertIn("富贵养老", source)
        self.assertIn("wealthyRetiredCount", source)
        self.assertIn('class="wealthy-retirement-state"', source)
        self.assertIn("function splitLevelName(level)", source)
        self.assertIn("const chinese = [name, ...aliases].find(hasChinese)", source)
        self.assertIn('class="retirement-route-node__name"', source)
        self.assertIn("site.status !== 'wealthy_retired'", source)
        self.assertNotIn("完成以下要求即可升级，继续享受更多权益。", source)
        self.assertNotIn(':hint="`${summary.valid_sites || 0} 个有效站点`"', source)
        self.assertNotIn(':hint="`总分享率 ${formatNumber(summary.overall_ratio, 3)}`"', source)
        self.assertNotIn(':hint="`${todaySites.length} 个有流量站点`"', source)
        self.assertLess(source.index("规则缺失 {{ retirement.rule_missing"), source.index("升级中 {{ retirement.upgrading"))
        self.assertLess(source.index("升级中 {{ retirement.upgrading"), source.index("养老中 {{ ordinaryRetiredCount"))
        self.assertLess(source.index("养老中 {{ ordinaryRetiredCount"), source.index("富贵养老 {{ wealthyRetiredCount"))
        self.assertNotIn("retirementProgressPercent(site)", source)
        self.assertIn("const overallProgress = averageRequirementProgress(requirements)", source)
        self.assertNotIn("retirement-preview-grid", source)
        self.assertNotIn("retirement-mini-progress", source)
        self.assertLess(source.index('class="retirement-site-list"'), source.index('class="retirement-detail"'))
        self.assertLess(source.index('class="retirement-detail__metrics"'), source.index('class="retirement-route-rail"'))
        self.assertLess(source.index('class="retirement-route-rail"'), source.index('class="requirement-panel"'))
        self.assertIn('v-if="level.description"', source)
        self.assertNotIn("<span>积分预计</span><span>状态</span>", source)
        self.assertNotIn("routeMissingLabel(level)", source)
        self.assertIn(".pt-workbench--compact .retirement-explorer{grid-template-columns:1fr", source)
        self.assertIn(".pt-workbench--compact .requirement-table,.pt-workbench--compact .retirement-levels{max-width:100%;overflow-x:auto", source)
        self.assertIn("<h2>养老进度</h2>", source)
        self.assertNotIn("全部站点养老进度", source)
        self.assertNotIn("同步 MP 数据间隔", source)
        self.assertNotIn("mdi-calendar-arrow-up", source)
        self.assertNotIn("mdi-calendar-arrow-down", source)
        self.assertNotIn("mdi-content-copy", source)
        self.assertNotIn("copyPtdReceiverUrl", source)
        self.assertEqual(source.count('icon="mdi-shuffle-variant"'), 2)
        self.assertNotIn('建议同时勾选“站点与服务器配置”', source)

        dashboard = (PLUGIN / "src" / "components" / "Dashboard.vue").read_text(
            encoding="utf-8"
        )
        self.assertLess(dashboard.index("统计时间"), dashboard.index("上传增量"))
        self.assertIn("今日流量", dashboard)
        self.assertIn('icon="mdi-finance"', dashboard)
        self.assertIn("今天 00:00 起", dashboard)
        self.assertIn('<VCard class="pt-dashboard dashboard-grid-fill">', dashboard)
        self.assertIn("container-type: inline-size", dashboard)
        self.assertIn("background: rgb(var(--v-theme-surface));", dashboard)
        self.assertIn("grid-template-columns: minmax(180px, .7fr) minmax(0, 2.3fr)", dashboard)
        self.assertIn("@container (max-width: 820px)", dashboard)
        self.assertIn("@container (max-width: 480px)", dashboard)
        self.assertNotIn("@container (max-width: 700px)", dashboard)
        self.assertIn('aria-label="今日站点流量列表"', dashboard)
        self.assertIn("overflow-y: auto", dashboard)
        self.assertIn("grid-auto-rows: 90px", dashboard)
        self.assertIn("align-content: start", dashboard)
        self.assertIn("'#52d000', '#29a8e8', '#f59e0b', '#8b5cf6'", dashboard)
        self.assertNotIn("backdrop-filter: blur(18px)", dashboard)
        self.assertNotIn("backdrop-filter: blur(10px)", dashboard)
        self.assertIn("background: rgba(var(--v-theme-on-surface), .04)", dashboard)
        self.assertIn("width: 126px", dashboard)
        self.assertIn("font-size: 1rem; font-weight: 700", dashboard)
        self.assertIn(".site-row__metric span { color: rgb(var(--v-theme-on-surface)); font-weight: 700; }", dashboard)
        self.assertIn(".site-row__metric--download { color: rgb(var(--v-theme-on-surface)); }", dashboard)
        self.assertNotIn('icon="mdi-arrow-up" size="20" color="success"', dashboard)
        self.assertNotIn('icon="mdi-arrow-down" size="20" color="error"', dashboard)
        self.assertIn("color: rgb(var(--v-theme-on-surface)) !important", dashboard)
        self.assertIn(".total-pill span { grid-area: label; font-size: .8rem; font-weight: 600; color: rgb(var(--v-theme-on-surface)); }", dashboard)
        self.assertIn("font-variant-numeric: tabular-nums", dashboard)

        self.assertNotIn("<h2>数据导出</h2>", source)
        self.assertNotIn("ExportDialog", source)
        self.assertNotIn("export_fields", source)
        self.assertIn("url.hostname = 'localhost'", source)
        self.assertIn("其它局域网设备请替换为 MoviePilot 主机 IP", source)

        utils = (PLUGIN / "src" / "utils.js").read_text(encoding="utf-8")
        self.assertIn("while (bytes >= 1024", utils)
        self.assertIn("bytes /= 1024", utils)
        self.assertIn("const digits = bytes < 100 ? 2 : 1", utils)
        self.assertNotIn("bytes /= 1000", utils)
        self.assertIn("event?.preventDefault?.()", utils)


if __name__ == "__main__":
    unittest.main()
