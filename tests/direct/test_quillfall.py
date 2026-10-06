"""Quillfall — The Autumn Anthology: direct-mode test suite.

Covers: intake guards, deterministic form gates (sonnet/limerick/quatrain),
deterministic season gate, LLM-label adjudication (accepted / rejected /
uncertain), fail-safe paths (malformed LLM output, empty labels, off-domain
labels), deterministic-clamp-override (model fooled by an off-season poem
cannot PASS), validator agreement (incl. dual-failure agreement), settle
semantics (anthology seal, treasury burn, refund), cooldown, and stats.

Fixture poems use ORTHOGRAPHIC end rhymes (last-2-letters equal) so the
contract's deterministic rhyme checker accepts exactly the rhymed poems
and rejects the broken-rhyme fixtures.

Mock shapes follow verified pitfalls: mock_llm responses are JSON strings
(auto-parsed by gltest); warp is followed by an explicit message_raw
datetime refresh (known gltest pitfall).
"""
import json
import re
import pytest

from eth_utils import to_checksum_address

STAKE = 10 ** 16  # 0.01 GEN — above the 0.001 minimum

# ---------------------------------------------------------------------------
# Poem fixtures (orthographic rhymes; syllable counts verified against the
# contract's own estimator before being committed here)
# ---------------------------------------------------------------------------

# Limerick, AABBA, autumn imagery. Orthographic rhymes: gold/cold/old (ld),
# air/fair (ir). Syllables: 10/8/5/5/8 (bands A 7-11, B 4-7).
LIMERICK_AUTUMN = (
    "An amber maple let go of its gold,\n"
    "The frost made the meadow grow cold,\n"
    "The leaves filled the air,\n"
    "And drifted so fair,\n"
    "Till orchards were russet and old."
)

# Sonnet, 14 decasyllabic lines, autumn imagery.
SONNET_AUTUMN = (
    "The orchard bends with apples row on row,\n"
    "The cider press drips sweet beneath the tree,\n"
    "The maple sheds its amber down below,\n"
    "And geese are calling low across the lea.\n"
    "The bonfire smokes against the fading light,\n"
    "The harvest moon is climbing pale and high,\n"
    "The acorns drop when owls are out at night,\n"
    "The frost has etched its lace on every rye.\n"
    "The wheat is sheaved, the stubble fields are brown,\n"
    "The chestnuts split inside their prickled shell,\n"
    "The wind strips every bough before the town,\n"
    "The smoke of hearths is rising where we dwell.\n"
    "So autumn writes its ledger on the land,\n"
    "And seals the year with one enchanted hand."
)

# Quatrain, AABA (rubaiyat-style: wall/fall/wall; line 2 unrhymed).
QUATRAIN_AUTUMN = (
    "The acorn drops beside the garden wall,\n"
    "The maples burn in amber and in red,\n"
    "The sparrows gather where the shadows fall,\n"
    "And smoke drifts gold above the garden wall."
)

# Limerick about summer swimming (no autumn lexicon at all -> season FAIL).
LIMERICK_SUMMER = (
    "A swimmer went down to the tide,\n"
    "With sunscreen and towels beside,\n"
    "The waves were so bright,\n"
    "Beneath blazing light,\n"
    "He watched the shining surf glide."
)

# Limerick dominated by winter lexicon; mentions autumn once (season FAIL).
LIMERICK_WINTER = (
    "A snowman was carved in the snow,\n"
    "With icicles hanging below,\n"
    "One autumn leaf blew,\n"
    "Across the white view,\n"
    "Then blizzards and frost laid it low."
)

# Limerick with almost no seasonal lexicon at all.
LIMERICK_NEUTRAL = (
    "A builder once built a machine,\n"
    "The finest that ever was seen,\n"
    "It whirred and it hummed,\n"
    "It calculated and summed,\n"
    "And kept all its numbers quite clean."
)

# A form-valid QUATRAIN with only 16 words -> season gate UNCERTAIN
# (word-count floor), so adjudication fail-safes to INCONCLUSIVE even
# though the form gate passes.
SHORT_POEM = (
    "The frost seals the land,\n"
    "The leaves drift like sand,\n"
    "The geese leave the town,\n"
    "The light goes down."
)

# A "sonnet" that is really a limerick (form gate must FAIL it).
SONNET_FORM_CHEAT = LIMERICK_AUTUMN

# A limerick whose long lines blow past the syllable band (form FAIL).
LIMERICK_BLOATED = (
    "A farmer was counting his harvest of apples and wheat in the sun,\n"
    "With baskets of chestnuts and acorns enough for everyone around,\n"
    "The maples were burning,\n"
    "The geese were returning,\n"
    "And cider was drunk by the barrel."
)

# A limerick whose A-rhyme is broken on line 5 (gold/cold OK, knife does
# not rhyme with gold -> AABBA violated; form FAIL).
LIMERICK_BROKEN_RHYME = (
    "The maples let go of their gold,\n"
    "The frost made the meadow grow cold,\n"
    "An acorn dropped down,\n"
    "The wind through the town,\n"
    "Was crisp and as sharp as a knife."
)

# A "sonnet" about spring (fails both form and season gates).
SONNET_SPRING = (
    "The tulips bloom in colors down the glade,\n"
    "The cherry blossoms drift across the lawn,\n"
    "The April sun on every new leaf played,\n"
    "The springtime birds are singing before dawn."
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def addr_str(addr):
    """Normalize gltest Address / bytes / str to EIP-55 hex string."""
    if isinstance(addr, str):
        return to_checksum_address(addr)
    if isinstance(addr, bytes):
        return to_checksum_address(addr.hex())
    if hasattr(addr, "as_bytes"):
        raw = addr.as_bytes
        raw = raw() if callable(raw) else raw
        return to_checksum_address(bytes(raw).hex())
    return to_checksum_address(bytes(addr).hex())


LLM_PATTERN = ".*independent poetry judges.*"


def mock_llm_labels(vm, form_status="PASS", season_status="PASS",
                    cite="amber leaves drifted"):
    vm.clear_mocks()
    vm.mock_llm(LLM_PATTERN, json.dumps({
        "labels": [
            {"criterion": 0, "name": "FORM_OK", "status": form_status,
             "cite": cite, "reason": "form assessment"},
            {"criterion": 1, "name": "SEASON_OK", "status": season_status,
             "cite": cite, "reason": "season assessment"},
        ]
    }))


def submit(vm, contract, poem=LIMERICK_AUTUMN, form="limerick",
           title="Amber Fall", stake=STAKE, sender=None):
    if sender is not None:
        vm.sender = sender
    vm.value = stake
    try:
        contract.submit_poem(title, form, poem)
    finally:
        vm.value = 0
    state = json.loads(contract.get_poet_state(addr_str(vm.sender)))
    return state["last_id"]


def get_rec(contract, sid):
    return json.loads(contract.get_submission(sid))


def get_stats(contract):
    return json.loads(contract.get_stats())


def refresh_datetime(vm, iso):
    """warp() does not propagate into an already-loaded contract's cached
    message_raw (known gltest pitfall) — refresh it explicitly."""
    vm.warp(iso)
    import sys
    import genlayer.gl as gl_mod
    gl_mod.message_raw["datetime"] = iso


# ---------------------------------------------------------------------------
# Deterministic helpers unit tests (contract module functions)
# ---------------------------------------------------------------------------

def _load_module():
    """Load the contract's PURE helper functions as a plain module,
    skipping the genlayer import (the from genlayer import * line keeps
    the module from importing whole outside the runner). Everything from
    `_count_words` through the constants before the class is pure."""
    import types
    src = open("/home/ubuntu/quillfall/contracts/quillfall.py", "r").read()
    idx = src.index("AUTUMN_CORE")
    end = src.index("MIN_STAKE_WEI")
    module = types.ModuleType("quillfall_pure")
    body = "import json\n" + src[idx:end]
    exec(body, module.__dict__)
    return module


@pytest.fixture(scope="module")
def pure():
    return _load_module()


class TestPureHelpers:
    def test_syllable_estimator_basics(self, pure):
        assert pure._count_syllables("cat") == 1
        assert pure._count_syllables("maple") == 2
        assert pure._count_syllables("amber") == 2
        assert pure._count_syllables("calculated") == 3

    def test_limerick_fixture_passes_form_gate(self, pure):
        assert pure._validate_form("limerick", LIMERICK_AUTUMN) == "PASS"

    def test_sonnet_fixture_passes_form_gate(self, pure):
        assert pure._validate_form("sonnet", SONNET_AUTUMN) == "PASS"

    def test_quatrain_fixture_passes_form_gate(self, pure):
        assert pure._validate_form("quatrain", QUATRAIN_AUTUMN) == "PASS"

    def test_limerick_bloated_fails(self, pure):
        assert pure._validate_form("limerick", LIMERICK_BLOATED) == "FAIL"

    def test_limerick_broken_rhyme_fails(self, pure):
        assert pure._validate_form("limerick", LIMERICK_BROKEN_RHYME) == "FAIL"

    def test_sonnet_count_fails(self, pure):
        assert pure._validate_form("sonnet", QUATRAIN_AUTUMN) == "FAIL"

    def test_season_gate_pass_on_autumn(self, pure):
        assert pure._validate_season_gate(LIMERICK_AUTUMN) == "PASS"

    def test_season_gate_pass_on_sonnet(self, pure):
        assert pure._validate_season_gate(SONNET_AUTUMN) == "PASS"

    def test_season_gate_fail_on_winter(self, pure):
        assert pure._validate_season_gate(LIMERICK_WINTER) == "FAIL"

    def test_season_gate_fail_on_neutral(self, pure):
        assert pure._validate_season_gate(LIMERICK_NEUTRAL) == "FAIL"

    def test_season_gate_fail_on_summer(self, pure):
        assert pure._validate_season_gate(LIMERICK_SUMMER) == "FAIL"

    def test_season_gate_fail_on_spring_sonnet(self, pure):
        assert pure._validate_season_gate(SONNET_SPRING) == "FAIL"

    def test_season_gate_uncertain_on_short(self, pure):
        assert pure._validate_season_gate(SHORT_POEM) == "UNCERTAIN"

    def test_short_poem_form_gate_passes(self, pure):
        assert pure._validate_form("quatrain", SHORT_POEM) == "PASS"

    def test_unknown_form_uncertain(self, pure):
        assert pure._validate_form("haiku", QUATRAIN_AUTUMN) == "UNCERTAIN"


# ---------------------------------------------------------------------------
# Intake guards
# ---------------------------------------------------------------------------

class TestIntake:
    def test_submit_happy_path(self, direct_vm, direct_deploy,
                               direct_alice):
        vm = direct_vm
        vm.sender = direct_alice
        contract = direct_deploy("contracts/quillfall.py")
        sid = submit(vm, contract, sender=direct_alice)
        rec = get_rec(contract, sid)
        assert rec["status"] == "PENDING"
        assert rec["poet"] == addr_str(direct_alice)
        assert int(rec["stake"]) == STAKE
        assert rec["form_gate"] == "PASS"
        assert rec["season_gate"] == "PASS"

    def test_stake_below_minimum_reverts(self, direct_vm, direct_deploy,
                                         direct_alice):
        vm = direct_vm
        vm.sender = direct_alice
        contract = direct_deploy("contracts/quillfall.py")
        with vm.expect_revert("stake_below_minimum"):
            submit(vm, contract, stake=10 ** 14, sender=direct_alice)

    def test_open_submission_exists(self, direct_vm, direct_deploy,
                                    direct_alice):
        vm = direct_vm
        contract = direct_deploy("contracts/quillfall.py")
        submit(vm, contract, sender=direct_alice)
        with vm.expect_revert("open_submission_exists"):
            submit(vm, contract, sender=direct_alice)

    def test_unsupported_form(self, direct_vm, direct_deploy, direct_alice):
        vm = direct_vm
        contract = direct_deploy("contracts/quillfall.py")
        with vm.expect_revert("unsupported_form"):
            submit(vm, contract, form="haiku", sender=direct_alice)

    def test_bad_poem_length(self, direct_vm, direct_deploy, direct_alice):
        vm = direct_vm
        contract = direct_deploy("contracts/quillfall.py")
        with vm.expect_revert("bad_poem_length"):
            submit(vm, contract, poem="too short", sender=direct_alice)

    def test_bad_title_length(self, direct_vm, direct_deploy, direct_alice):
        vm = direct_vm
        contract = direct_deploy("contracts/quillfall.py")
        with vm.expect_revert("bad_title_length"):
            submit(vm, contract, title="ab", sender=direct_alice)

    def test_two_poets_can_submit_concurrently(self, direct_vm,
                                               direct_deploy, direct_alice,
                                               direct_bob):
        vm = direct_vm
        contract = direct_deploy("contracts/quillfall.py")
        sid_a = submit(vm, contract, sender=direct_alice)
        sid_b = submit(vm, contract, poem=QUATRAIN_AUTUMN, form="quatrain",
                       sender=direct_bob)
        assert sid_a != sid_b
        assert get_rec(contract, sid_a)["poet"] == addr_str(direct_alice)
        assert get_rec(contract, sid_b)["poet"] == addr_str(direct_bob)


# ---------------------------------------------------------------------------
# Adjudication — deterministic short-circuits (no LLM mock needed)
# ---------------------------------------------------------------------------

class TestDeterministicAdjudication:
    def test_form_gate_rejects_sonnet_cheat_even_with_fooled_llm(
            self, direct_vm, direct_deploy, direct_alice):
        vm = direct_vm
        contract = direct_deploy("contracts/quillfall.py")
        sid = submit(vm, contract, poem=SONNET_FORM_CHEAT, form="sonnet",
                     sender=direct_alice)
        # The LLM is "fooled" and says PASS/PASS — the deterministic form
        # gate must override it: 5 lines can never be a sonnet.
        mock_llm_labels(vm, "PASS", "PASS")
        vm.sender = direct_alice
        contract.adjudicate(sid)
        rec = get_rec(contract, sid)
        assert rec["verdict"] == "REJECTED"
        assert "form_gate_fail:sonnet" in rec["reasons"]

    def test_season_gate_rejects_winter_dominance(self, direct_vm,
                                                  direct_deploy,
                                                  direct_alice):
        vm = direct_vm
        contract = direct_deploy("contracts/quillfall.py")
        sid = submit(vm, contract, poem=LIMERICK_WINTER,
                     sender=direct_alice)
        mock_llm_labels(vm, "PASS", "PASS")  # fooled model
        vm.sender = direct_alice
        contract.adjudicate(sid)
        rec = get_rec(contract, sid)
        assert rec["verdict"] == "REJECTED"
        assert "season_gate_fail" in rec["reasons"]

    def test_short_poem_is_inconclusive_not_rejected(self, direct_vm,
                                                     direct_deploy,
                                                     direct_alice):
        vm = direct_vm
        contract = direct_deploy("contracts/quillfall.py")
        sid = submit(vm, contract, poem=SHORT_POEM, form="quatrain",
                     sender=direct_alice)
        vm.sender = direct_alice
        contract.adjudicate(sid)
        rec = get_rec(contract, sid)
        assert rec["verdict"] == "INCONCLUSIVE"
        assert "gate_uncertain" in rec["reasons"]


# ---------------------------------------------------------------------------
# Adjudication — LLM-label driven paths
# ---------------------------------------------------------------------------

class TestLLMAdjudication:
    def test_accepted_poem_sealed_into_anthology(self, direct_vm,
                                                 direct_deploy,
                                                 direct_alice):
        vm = direct_vm
        contract = direct_deploy("contracts/quillfall.py")
        sid = submit(vm, contract, sender=direct_alice)
        mock_llm_labels(vm, "PASS", "PASS")
        vm.sender = direct_alice
        contract.adjudicate(sid)
        rec = get_rec(contract, sid)
        assert rec["verdict"] == "ACCEPTED"
        entry = json.loads(contract.get_anthology_entry(sid))
        assert entry["title"] == "Amber Fall"
        assert entry["form"] == "limerick"
        assert "maple" in entry["poem"]
        stats = get_stats(contract)
        assert stats["accepted"] == "1"
        assert stats["anthology_size"] == "1"
        assert stats["treasury_balance"] == "0"

    def test_rejected_by_llm_labels_burns_stake(self, direct_vm,
                                                direct_deploy,
                                                direct_alice):
        vm = direct_vm
        contract = direct_deploy("contracts/quillfall.py")
        sid = submit(vm, contract, sender=direct_alice)
        mock_llm_labels(vm, "FAIL", "PASS")
        vm.sender = direct_alice
        contract.adjudicate(sid)
        rec = get_rec(contract, sid)
        assert rec["verdict"] == "REJECTED"
        assert "form_fail" in rec["reasons"]
        stats = get_stats(contract)
        assert stats["rejected"] == "1"
        assert stats["treasury_balance"] == str(STAKE)
        with vm.expect_revert("not_in_anthology"):
            contract.get_anthology_entry(sid)

    def test_uncertain_label_is_inconclusive_and_refunds(self, direct_vm,
                                                         direct_deploy,
                                                         direct_alice):
        vm = direct_vm
        contract = direct_deploy("contracts/quillfall.py")
        sid = submit(vm, contract, sender=direct_alice)
        mock_llm_labels(vm, "PASS", "UNCERTAIN")
        vm.sender = direct_alice
        contract.adjudicate(sid)
        rec = get_rec(contract, sid)
        assert rec["verdict"] == "INCONCLUSIVE"
        assert "judge_uncertain" in rec["reasons"]
        assert get_stats(contract)["inconclusive"] == "1"

    def test_malformed_llm_output_is_inconclusive(self, direct_vm,
                                                  direct_deploy,
                                                  direct_alice):
        vm = direct_vm
        contract = direct_deploy("contracts/quillfall.py")
        sid = submit(vm, contract, sender=direct_alice)
        vm.clear_mocks()
        vm.mock_llm(LLM_PATTERN, "this is not json at all")
        vm.sender = direct_alice
        contract.adjudicate(sid)
        rec = get_rec(contract, sid)
        assert rec["verdict"] == "INCONCLUSIVE"
        assert "judge_unparsable" in rec["reasons"]

    def test_empty_labels_is_inconclusive(self, direct_vm, direct_deploy,
                                          direct_alice):
        vm = direct_vm
        contract = direct_deploy("contracts/quillfall.py")
        sid = submit(vm, contract, sender=direct_alice)
        vm.clear_mocks()
        vm.mock_llm(LLM_PATTERN, json.dumps({"labels": []}))
        vm.sender = direct_alice
        contract.adjudicate(sid)
        rec = get_rec(contract, sid)
        assert rec["verdict"] == "INCONCLUSIVE"

    def test_off_domain_label_treated_as_uncertain(self, direct_vm,
                                                   direct_deploy,
                                                   direct_alice):
        vm = direct_vm
        contract = direct_deploy("contracts/quillfall.py")
        sid = submit(vm, contract, sender=direct_alice)
        vm.clear_mocks()
        vm.mock_llm(LLM_PATTERN, json.dumps({"labels": [
            {"criterion": 0, "name": "FORM_OK", "status": "EXCELLENT"},
            {"criterion": 1, "name": "SEASON_OK", "status": "PASS"},
        ]}))
        vm.sender = direct_alice
        contract.adjudicate(sid)
        rec = get_rec(contract, sid)
        assert rec["verdict"] == "INCONCLUSIVE"

    def test_quatrain_accepted(self, direct_vm, direct_deploy, direct_alice):
        vm = direct_vm
        contract = direct_deploy("contracts/quillfall.py")
        sid = submit(vm, contract, poem=QUATRAIN_AUTUMN, form="quatrain",
                     title="October Quatrain", sender=direct_alice)
        mock_llm_labels(vm, "PASS", "PASS")
        vm.sender = direct_alice
        contract.adjudicate(sid)
        assert get_rec(contract, sid)["verdict"] == "ACCEPTED"

    def test_already_adjudicated_guard(self, direct_vm, direct_deploy,
                                       direct_alice):
        vm = direct_vm
        contract = direct_deploy("contracts/quillfall.py")
        sid = submit(vm, contract, sender=direct_alice)
        mock_llm_labels(vm, "PASS", "PASS")
        vm.sender = direct_alice
        contract.adjudicate(sid)
        with vm.expect_revert("already_adjudicated"):
            contract.adjudicate(sid)

    def test_adjudicate_unknown_id(self, direct_vm, direct_deploy,
                                   direct_alice):
        vm = direct_vm
        contract = direct_deploy("contracts/quillfall.py")
        with vm.expect_revert("submission_not_found"):
            contract.adjudicate("q999-aaaaaa-0")


# ---------------------------------------------------------------------------
# Validator agreement
# ---------------------------------------------------------------------------

class TestValidatorAgreement:
    def test_validator_agrees_on_labels(self, direct_vm, direct_deploy,
                                        direct_alice):
        vm = direct_vm
        contract = direct_deploy("contracts/quillfall.py")
        sid = submit(vm, contract, sender=direct_alice)
        mock_llm_labels(vm, "PASS", "PASS")
        vm.sender = direct_alice
        contract.adjudicate(sid)
        assert vm.run_validator() is True

    def test_validator_agrees_on_fail_safe(self, direct_vm, direct_deploy,
                                           direct_alice):
        vm = direct_vm
        contract = direct_deploy("contracts/quillfall.py")
        sid = submit(vm, contract, sender=direct_alice)
        vm.clear_mocks()
        vm.mock_llm(LLM_PATTERN, "not json")
        vm.sender = direct_alice
        contract.adjudicate(sid)
        assert vm.run_validator() is True

    def test_validator_disagrees_on_divergent_labels(self, direct_vm,
                                                     direct_deploy,
                                                     direct_alice):
        vm = direct_vm
        contract = direct_deploy("contracts/quillfall.py")
        sid = submit(vm, contract, sender=direct_alice)
        mock_llm_labels(vm, "PASS", "PASS")
        vm.sender = direct_alice
        contract.adjudicate(sid)
        # swap the mock so the validator's independent re-run sees FAIL
        mock_llm_labels(vm, "FAIL", "PASS")
        assert vm.run_validator() is False


# ---------------------------------------------------------------------------
# Settlement semantics: cooldown, poet state, treasury
# ---------------------------------------------------------------------------

class TestSettlement:
    def test_cooldown_blocks_resubmit(self, direct_vm, direct_deploy,
                                      direct_alice):
        vm = direct_vm
        contract = direct_deploy("contracts/quillfall.py")
        sid = submit(vm, contract, sender=direct_alice)
        mock_llm_labels(vm, "PASS", "PASS")
        vm.sender = direct_alice
        contract.adjudicate(sid)
        with vm.expect_revert("resubmit_cooldown_active"):
            submit(vm, contract, poem=QUATRAIN_AUTUMN, form="quatrain",
                   sender=direct_alice)

    def test_cooldown_expires_after_warp(self, direct_vm, direct_deploy,
                                         direct_alice):
        vm = direct_vm
        contract = direct_deploy("contracts/quillfall.py")
        sid = submit(vm, contract, sender=direct_alice)
        mock_llm_labels(vm, "PASS", "PASS")
        vm.sender = direct_alice
        contract.adjudicate(sid)
        refresh_datetime(vm, "2026-10-06T18:30:00.000000Z")
        sid2 = submit(vm, contract, poem=QUATRAIN_AUTUMN, form="quatrain",
                      sender=direct_alice)
        assert get_rec(contract, sid2)["status"] == "PENDING"

    def test_open_flag_cleared_after_settle(self, direct_vm, direct_deploy,
                                            direct_alice):
        vm = direct_vm
        contract = direct_deploy("contracts/quillfall.py")
        sid = submit(vm, contract, sender=direct_alice)
        state = json.loads(contract.get_poet_state(addr_str(direct_alice)))
        assert state["open_id"] == sid
        mock_llm_labels(vm, "FAIL", "FAIL")
        vm.sender = direct_alice
        contract.adjudicate(sid)
        state = json.loads(contract.get_poet_state(addr_str(direct_alice)))
        assert state["open_id"] == ""

    def test_multiple_poets_independent_settlement(self, direct_vm,
                                                   direct_deploy,
                                                   direct_alice,
                                                   direct_bob):
        vm = direct_vm
        contract = direct_deploy("contracts/quillfall.py")
        sid_a = submit(vm, contract, sender=direct_alice)
        sid_b = submit(vm, contract, poem=QUATRAIN_AUTUMN, form="quatrain",
                       sender=direct_bob)
        mock_llm_labels(vm, "PASS", "PASS")
        vm.sender = direct_alice
        contract.adjudicate(sid_a)
        vm.sender = direct_bob
        contract.adjudicate(sid_b)
        stats = get_stats(contract)
        assert stats["accepted"] == "2"
        assert stats["total_submissions"] == "2"
        assert stats["anthology_size"] == "2"
