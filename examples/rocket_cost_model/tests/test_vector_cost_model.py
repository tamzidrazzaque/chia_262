"""Bounded Saturn vector-cost proposals must not admit arbitrary source edits."""

from pathlib import Path
import tempfile
import unittest
from unittest import mock

from examples.rocket_cost_model.vector_cost_model import (
    BASE_COSTS,
    COMMON_COMMENTS,
    CPU_COMMENTS,
    REGMOVE_COMMENTS,
    _ensure_generated_lexer,
    proposal,
    render_costs,
    validate_changes,
)


def initializer(comments):
    return "\n".join(f"  {BASE_COSTS[key]}, /* {comment}  */" for key, comment in comments.items())


SOURCE = f"""
static const common_vector_cost rvv_vls_vector_cost = {{
{initializer(COMMON_COMMENTS)}
}};
static const scalable_vector_cost rvv_vla_vector_cost = {{
  {{
{initializer(COMMON_COMMENTS)}
  }},
}};
static const regmove_vector_cost rvv_regmove_vector_cost = {{
{initializer(REGMOVE_COMMENTS)}
}};
static const struct cpu_vector_cost generic_vector_cost = {{
{initializer(CPU_COMMENTS)}
  &rvv_vls_vector_cost, /* vls */
  &rvv_vla_vector_cost, /* vla */
  &rvv_regmove_vector_cost, /* regmove */
}};
static const struct riscv_tune_param rocket_tune_info = {{
  3, /* branch_cost */
  NULL, /* vector cost */
}};
"""


class VectorCostModelTests(unittest.TestCase):
    def test_rejects_unknown_non_integer_and_unbounded_changes(self):
        for changes in ({"command": 1}, {"permute": True}, {"permute": 0}, {"permute": 65}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                validate_changes(changes)

    def test_proposal_requires_only_changes_and_rationale(self):
        selected = {"changes": {"permute": 4}, "rationale": "Saturn permutation hypothesis"}
        self.assertEqual(proposal(selected), selected)
        with self.assertRaises(ValueError):
            proposal({**selected, "patch": "arbitrary text"})

    def test_render_changes_only_selected_cost_and_attaches_rocket_table(self):
        changed, values = render_costs(SOURCE, {"vec_to_scalar": 7})
        self.assertEqual(values["vec_to_scalar"], 7)
        self.assertEqual(values["permute"], BASE_COSTS["permute"])
        self.assertEqual(changed.count("7, /* vec_to_scalar_cost  */"), 2)
        self.assertIn("&generic_vector_cost, /* vector cost */", changed)
        self.assertNotIn("NULL, /* vector cost */", changed)

    def test_render_requires_pinned_source_shape(self):
        with self.assertRaisesRegex(ValueError, "initializer was not found"):
            render_costs("not the pinned backend", {"permute": 4})

    def test_empty_generated_lexer_is_rebuilt_and_stale_object_removed(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            lexer = root / "build/gcc/gengtype-lex.cc"
            lexer.parent.mkdir(parents=True)
            lexer.write_text("")
            stale = root / "build/gcc/build/gengtype-lex.o"
            stale.parent.mkdir()
            stale.write_bytes(b"stale")

            def fake_flex(command, check):
                self.assertEqual(command[0], "flex")
                self.assertTrue(check)
                lexer.write_text("generated lexer\n")

            with mock.patch("subprocess.run", side_effect=fake_flex):
                _ensure_generated_lexer(root)
            self.assertTrue(lexer.read_text().startswith("#ifdef HOST_GENERATOR_FILE\n"))
            self.assertFalse(stale.exists())


if __name__ == "__main__":
    unittest.main()
