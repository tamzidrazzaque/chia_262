"""The private SPEC roles 1-3 must preserve their controlled variables."""

import hashlib
import json
from pathlib import Path
import unittest

from examples.rocket_cost_model.spec_vector_baseline import (
    GENERATED,
    SCALAR_FLAGS,
    TARGET_CONFIG,
    TARGET_DLEN,
    TARGET_FIRESIM_CONFIG,
    TARGET_VLEN,
    VECTOR_FLAGS,
    candidate_name,
    render_config,
    role_settings,
    validate_candidate_manifest,
    validated,
)


TEMPLATE = """%define label riscv # comment
%if %{bits} == 64
%   define model      -march=rv64imafdc  -mabi=lp64d
%endif
ignore_errors        = 1
default:
   CC = compiler %{model} -static
"""


class VectorSpecBaselineTests(unittest.TestCase):
    def test_official_firesim_discovery_matches_selected_target(self):
        discovery_path = Path(__file__).parents[1] / "saturn-firesim-discovery.json"
        discovery = json.loads(discovery_path.read_text())
        self.assertEqual(discovery["recipe"]["TARGET_CONFIG"], TARGET_FIRESIM_CONFIG)
        self.assertEqual(discovery["catalog"]["AGFI"], "agfi-012e92467d7d2149a")
        self.assertTrue(discovery["catalog"]["AWS_metadata_verified"])
        self.assertEqual(
            discovery["source"]["Chipyard_revision"],
            "19a07f6b8d4d1db81f5561d9aeceb2cdc43407fe",
        )
        self.assertEqual(
            discovery["source"]["FireSim_revision"],
            discovery["manager_metadata_check"]["observed_FireSim_revision"],
        )
        self.assertTrue(discovery["manager_metadata_check"]["FireSim_revision_matches"])
        self.assertEqual(discovery["driver"]["status"], "accepted")
        self.assertTrue(discovery["driver"]["matching_source_verified"])
        receipt_path = discovery_path.parent / discovery["driver"]["acceptance_record"]
        self.assertEqual(hashlib.sha256(receipt_path.read_bytes()).hexdigest(),
                         discovery["driver"]["acceptance_record_sha256"])
        receipt = json.loads(receipt_path.read_text())
        self.assertEqual(receipt["build_exit_code"], 0)
        self.assertEqual(receipt["quintuplet"], discovery["recipe"]["expected_quintuplet"])
        self.assertEqual(receipt["AGFI"], discovery["catalog"]["AGFI"])
        self.assertEqual(receipt["driver_sha256"], discovery["driver"]["driver_sha256"])
        self.assertEqual(receipt["driver_bundle_sha256"], discovery["driver"]["driver_bundle_sha256"])
        self.assertEqual(receipt["missing_dependencies"], [])
        self.assertTrue(receipt["generated_header_sha256"])
        for source, details in receipt["sources"].items():
            self.assertTrue(details["clean"])
            self.assertEqual(details["revision"], discovery["source"][source + "_revision"])
        self.assertFalse(receipt["hardware_execution_verified"])
        self.assertFalse(discovery["hardware_execution_verified"])

    def test_role1_is_scalar_and_disables_both_vectorizers(self):
        label, flags, vector_qemu = role_settings("1-scalar")
        self.assertEqual(label, "saturn_role1_scalar")
        self.assertEqual(flags, SCALAR_FLAGS)
        self.assertIn("-fno-tree-loop-vectorize", flags)
        self.assertIn("-fno-tree-slp-vectorize", flags)
        self.assertFalse(vector_qemu)

    def test_role2_is_stock_dynamic_rvv_baseline(self):
        label, flags, vector_qemu = role_settings("2-generic-vector")
        self.assertEqual(label, "saturn_role2_generic_vector")
        self.assertEqual(flags, VECTOR_FLAGS)
        self.assertIn("-fvect-cost-model=dynamic", flags)
        self.assertTrue(vector_qemu)

    def test_role3_requires_safe_immutable_candidate_id(self):
        with self.assertRaisesRegex(ValueError, "requires an immutable candidate ID"):
            role_settings("3-saturn-aware")
        label, flags, vector_qemu = role_settings("3-saturn-aware", "0123456789ab")
        self.assertEqual(label, "saturn_role3_0123456789ab")
        self.assertEqual(flags, VECTOR_FLAGS)
        self.assertTrue(vector_qemu)
        with self.assertRaisesRegex(ValueError, "candidate ID"):
            candidate_name("../../unsafe")

    def test_candidate_manifest_binds_full_id_revision_and_prefix(self):
        manifest = {
            "candidate_id": "a" * 64,
            "prefix": "/private/candidate",
            "gcc_revision": "1b306039ac49f8ad91ca71d3de3150a3c9fa792a",
        }
        validate_candidate_manifest(manifest, "a" * 12, Path("/private/candidate"))
        with self.assertRaisesRegex(ValueError, "identity"):
            validate_candidate_manifest(manifest, "b" * 12, Path("/private/candidate"))
        with self.assertRaisesRegex(ValueError, "prefix"):
            validate_candidate_manifest(manifest, "a" * 12, Path("/private/other"))

    def test_renders_fixed_vector_target_and_qemu_cpu(self):
        config = render_config(
            TEMPLATE, "saturn_role2_generic_vector", VECTOR_FLAGS,
            Path("/private/qemu-riscv64"), True,
        )
        self.assertTrue(config.startswith(GENERATED))
        self.assertIn(VECTOR_FLAGS, config)
        self.assertIn("%define label saturn_role2_generic_vector", config)
        self.assertIn("ignore_errors        = 0", config)
        self.assertIn("use_submit_for_speed = yes", config)
        self.assertEqual(TARGET_CONFIG, "REFV256D128RocketConfig")
        self.assertEqual(TARGET_FIRESIM_CONFIG, "FireSimREFV256D128RocketConfig")
        self.assertEqual((TARGET_VLEN, TARGET_DLEN), (256, 128))
        self.assertIn("-cpu rv64,v=true,vlen=256,elen=64 ${command}", config)
        self.assertNotIn("rv64imafdc", config)

    def test_scalar_config_does_not_request_vector_qemu(self):
        config = render_config(
            TEMPLATE, "saturn_role1_scalar", SCALAR_FLAGS,
            Path("/private/qemu-riscv64"), False,
        )
        self.assertIn("submit = /private/qemu-riscv64 ${command}", config)
        self.assertNotIn("vlen=", config)

    def test_rejects_relative_qemu_path(self):
        with self.assertRaisesRegex(ValueError, "absolute path"):
            render_config(TEMPLATE, "saturn_role2_generic_vector", VECTOR_FLAGS,
                          Path("qemu-riscv64"), True)

    def test_requires_exact_spec_success_line(self):
        self.assertTrue(validated(" Success 648.exchange2_s base test ratio=0\n",
                                  "648.exchange2_s", "test"))
        self.assertFalse(validated(" Success 648.exchange2_s base train ratio=0\n",
                                   "648.exchange2_s", "test"))


if __name__ == "__main__":
    unittest.main()
