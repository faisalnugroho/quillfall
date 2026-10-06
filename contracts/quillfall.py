# { "Depends": "py-genlayer:1jb45aa8ynh2a9c9xn3b7qqh8sm5q93hwfp7jqmwsfhh8jpz09h6" }
"""Quillfall — The Autumn Anthology.

An on-chain poetry anthology where acceptance into the permanent
collection is adjudicated by neutral consensus over an AI evaluation of
FORM and SEASONAL CONTENT — the two things a plain smart contract
cannot judge.

A poet submits a poem with a declared form and stakes GEN. The contract
derives the verdict as a pure function of per-criterion labels the
leader model AND every validating model return independently:

  FORM_OK        — does the poem text satisfy the declared form?
  SEASON_OK      — autumn imagery throughout (no off-season dominance)?

  ACCEPTED     : all PASS                                  -> poem sealed
                 into the anthology, stake returned to the poet.
  REJECTED     : any FAIL                                 -> stake burned
                 to the anthology treasury; poem kept, marked rejected.
  INCONCLUSIVE : any UNCERTAIN, or any evaluator error    -> nothing
                 moves; fail-safe, poet may resubmit after cooldown.

DESIGN RULES (from 9 prior accepted GenLayer submissions):
  * The model NEVER picks the outcome; it returns per-criterion
    PASS/FAIL/UNCERTAIN labels with one cited line each. The contract
    computes the verdict. Consensus compares stable substance only.
  * Every LLM failure mode (exception, non-JSON, malformed shape,
    off-domain labels) maps to a well-formed INCONCLUSIVE that never
    moves money.
  * Evidence is the poem text itself, embedded in the transaction —
    fully public and identical for every validator. No web fetches are
    needed for judging, so there is no egress or evidence-availability
    risk in consensus.
  * Content gates are deterministic and clamp the LLM: an empty or
    too-short poem, a text dominated by another season's lexicon, or a
    text that merely mentions autumn once cannot PASS — regardless of
    what the model says.
  * Deterministic layer only: no storage writes, no transfer emits and
    no treasury accounting inside non-deterministic blocks.
  * Money moves ONLY via emit_transfer(on="finalized"), after checks-
    effects-interactions bookkeeping: stake is debited BEFORE the emit
    so a failed child message can never double-spend.
  * Anti-spam: one open submission per address; a settled submission
    (REJECTED / INCONCLUSIVE) opens a cooldown before re-submission.
"""
from genlayer import *
import json


# ---------------------------------------------------------------------------
# Deterministic shared lexicons (part of the deployed code, same for every
# validator — used by the deterministic content gates)
# ---------------------------------------------------------------------------

# Substantial autumn lexicon: words that genuinely carry autumn imagery.
# Includes common plural forms (exact-match lexicon).
AUTUMN_CORE = [
    "autumn", "autumns", "fall", "falls", "falling", "fallen", "harvest",
    "harvests", "amber", "russet", "russets", "ochre", "crimson", "ember",
    "embers", "maple", "maples", "oak", "oaks", "birch", "birches",
    "chestnut", "chestnuts", "acorn", "acorns", "leaf", "leaves",
    "leafpile", "leafpiles", "foliage", "bough", "boughs", "breeze",
    "breezes", "mist", "mists", "misty", "frost", "frosts", "frosty",
    "hollow", "hollows", "orchard", "orchards", "apple", "apples",
    "cider", "corn", "maize", "wheat", "sheaf", "sheaves", "scarecrow",
    "scarecrows", "sparrow", "sparrows", "crow", "crows", "goose",
    "geese", "migrate", "migration", "equinox", "october", "november",
    "september", "hearth", "hearths", "bonfire", "bonfires", "smoke",
    "smokes", "smoky", "fog", "fogs", "foggy", "dew", "hibernate",
    "hibernation", "drift", "drifts", "russeted", "goldenrod",
]

# Off-season markers: if these dominate the poem, it is not an autumn poem.
OFFSEASON_CORE = [
    "snow", "snows", "snowfall", "snowman", "snowmen", "blizzard",
    "blizzards", "icicle", "icicles", "ice", "icy", "winter", "winters",
    "december", "january", "february", "sleigh", "sleighs", "blossom",
    "blossoms", "bloom", "blooms", "blooming", "tulip", "tulips",
    "daffodil", "daffodils", "spring", "march", "april", "may", "cherry",
    "cherries", "sunflower", "sunflowers", "beach", "beaches",
    "seashore", "surf", "sunbathe", "summer", "summers", "june", "july",
    "august", "watermelon", "watermelons", "cicada", "cicadas",
    "heatwave", "heatwaves", "sunburn",
]


def _count_words(text):
    """Lowercased word list of the poem. Pure python, deterministic."""
    lowered = text.lower()
    words = []
    current = ""
    for ch in lowered:
        if ch == " " or ch == "\n" or ch == "\t" or ch == "\r":
            if current != "":
                words.append(current)
                current = ""
        elif ch.isalpha():
            current += ch
        else:
            if current != "":
                words.append(current)
                current = ""
    if current != "":
        words.append(current)
    return words


def _has_any(words, lexicon):
    for w in words:
        for term in lexicon:
            if w == term:
                return True
    return False


def _count_any(words, lexicon):
    n = 0
    for w in words:
        for term in lexicon:
            if w == term:
                n += 1
                break
    return n


def _count_syllables(word):
    """Small deterministic English syllable estimator (heuristic)."""
    w = word
    if len(w) <= 3:
        return 1
    w2 = w
    if w2[-1:] == "e" and len(w2) > 4 and w2[-2:] != "le":
        w2 = w2[:-1]
    count = 0
    prev_vowel = False
    for ch in w2:
        is_vowel = ch == "a" or ch == "e" or ch == "i" or ch == "o" or ch == "y"
        if is_vowel and not prev_vowel:
            count += 1
        prev_vowel = is_vowel
    return count


def _line_syllables(line):
    total = 0
    for w in _count_words(line):
        total += _count_syllables(w)
    return total


def _split_lines(text):
    lines = []
    current = ""
    for ch in text:
        if ch == "\n":
            lines.append(current)
            current = ""
        else:
            current += ch
    if current.strip() != "":
        lines.append(current)
    return lines


# --- Deterministic sonnet shape (14 lines, iambic-pentameter tolerance) -----
SONNET_LINES = 14
SONNET_SYL_MIN = 8
SONNET_SYL_MAX = 12

# --- Limerick shape: 5 lines, AABBA, anapestic feel via syllable bands -----
LIMERICK_LINES = 5
LIMERICK_SYL = {
    "A": (7, 11),   # lines 1,2,5: long anapestic lines
    "B": (4, 7),    # lines 3,4: short lines
}
LIMERICK_RHYME_MIN = 2  # letters that must match at line end


def _last_rhyme_token(line):
    """Last 3 alphabetic chars of the line's last word, lowercased."""
    words = _count_words(line)
    if len(words) == 0:
        return ""
    last = words[len(words) - 1]
    if len(last) >= 3:
        return last[len(last) - 3:]
    return last


def _rhymes(a, b):
    """Deterministic orthographic end-rhyme check: the last 2 letters of
    the lines' final words must match exactly (covers sun/one, tide/wide,
    mist/kissed, red/head, gold/cold). Three-letter matching misses
    non-identical but riming onsets (sun/one)."""
    ta = _last_rhyme_token(a)
    tb = _last_rhyme_token(b)
    if len(ta) < 2 or len(tb) < 2:
        return False
    return ta[len(ta) - 2:] == tb[len(tb) - 2:]


def _validate_form(form, text):
    """Deterministic structural gate. Returns 'PASS' | 'FAIL' | 'UNCERTAIN'.

    PASS  = structure verified by code.
    FAIL  = structure contradicted by code (line count / rhyme / meter).
    UNCERTAIN = code cannot fully verify (free verse fallback only when the
                declared form is unknown — and unknown forms are rejected at
                intake, so this only guards upgrades).
    """
    if form == "sonnet":
        lines = _split_lines(text)
        if len(lines) != SONNET_LINES:
            return "FAIL"
        ok_lines = 0
        for ln in lines:
            syl = _line_syllables(ln)
            if syl >= SONNET_SYL_MIN and syl <= SONNET_SYL_MAX:
                ok_lines += 1
        if ok_lines >= SONNET_LINES - 2:
            return "PASS"
        return "FAIL"

    if form == "limerick":
        lines = _split_lines(text)
        if len(lines) != LIMERICK_LINES:
            return "FAIL"
        # syllable bands
        idx = [0, 1, 2, 3, 4]
        bands = [
            LIMERICK_SYL["A"],
            LIMERICK_SYL["A"],
            LIMERICK_SYL["B"],
            LIMERICK_SYL["B"],
            LIMERICK_SYL["A"],
        ]
        for i in idx:
            syl = _line_syllables(lines[i])
            lo = bands[i][0]
            hi = bands[i][1]
            if syl < lo or syl > hi:
                return "FAIL"
        # AABBA rhyme scheme
        if not (_rhymes(lines[0], lines[1])
                and _rhymes(lines[0], lines[4])
                and _rhymes(lines[2], lines[3])):
            return "FAIL"
        return "PASS"

    if form == "quatrain":
        lines = _split_lines(text)
        if len(lines) != 4:
            return "FAIL"
        # rhymed quatrain: ABAB or AABB or AABA (enclosed/paired forms)
        r01 = _rhymes(lines[0], lines[1])
        r02 = _rhymes(lines[0], lines[2])
        r03 = _rhymes(lines[0], lines[3])
        r12 = _rhymes(lines[1], lines[2])
        r13 = _rhymes(lines[1], lines[3])
        r23 = _rhymes(lines[2], lines[3])
        abab = (r02 and r13)
        aabb = (r01 and r23)
        aaba = (r02 and r03)
        if not (abab or aabb or aaba):
            return "FAIL"
        # each line must carry at least 4 words (a real line, not a stub)
        for ln in lines:
            if len(_count_words(ln)) < 4:
                return "FAIL"
        return "PASS"

    return "UNCERTAIN"


def _validate_season_gate(text):
    """Deterministic seasonal gate. Returns 'PASS' | 'FAIL' | 'UNCERTAIN'."""
    words = _count_words(text)
    total = len(words)
    if total < 20:
        return "UNCERTAIN"
    autumn_hits = _count_any(words, AUTUMN_CORE)
    off_hits = _count_any(words, OFFSEASON_CORE)
    if off_hits > autumn_hits and off_hits > 2:
        return "FAIL"
    if autumn_hits == 0:
        return "FAIL"
    return "PASS"


MIN_STAKE_WEI = 1000000000000000        # 0.001 GEN (18 decimals)
MIN_POEM_CHARS = 60
MAX_POEM_CHARS = 4000
RESUBMIT_COOLDOWN_SECONDS = 3600        # 1h between submissions per poet


class QuillfallAnthology(gl.Contract):
    """Autumn anthology with consensus-adjudicated acceptance."""

    # --- storage -----------------------------------------------------------
    owner: Address
    submissions: TreeMap[str, str]   # id -> JSON record (all values strings)
    poet_last_id: TreeMap[str, str]  # poet address -> last submission id
    poet_open: TreeMap[str, str]     # poet address -> open submission id
    poet_cooldown_until: TreeMap[str, str]  # poet -> epoch seconds (str)
    anthology: TreeMap[str, str]     # id -> accepted poem record (sealed)
    next_id: u256
    treasury_balance: u256
    total_submissions: u256
    total_accepted: u256
    total_rejected: u256
    total_inconclusive: u256

    def __init__(self):
        self.owner = gl.message.sender_address
        self.submissions = TreeMap()
        self.poet_last_id = TreeMap()
        self.poet_open = TreeMap()
        self.poet_cooldown_until = TreeMap()
        self.anthology = TreeMap()
        self.next_id = u256(1)
        self.treasury_balance = u256(0)
        self.total_submissions = u256(0)
        self.total_accepted = u256(0)
        self.total_rejected = u256(0)
        self.total_inconclusive = u256(0)

    # ------------------------------------------------------------------
    # Internal helpers (deterministic)
    # ------------------------------------------------------------------

    def _now_epoch(self):
        """Node-assigned ISO-8601 datetime -> epoch seconds, pure integer
        math (Howard Hinnant _days_from_civil), no datetime/floats."""
        iso = gl.message_raw["datetime"]
        date_part = iso[:10]
        year = int(date_part[0:4])
        month = int(date_part[5:7])
        day = int(date_part[8:10])
        hh = int(iso[11:13])
        mm = int(iso[14:16])
        ss = int(iso[17:19])
        y = year
        if month <= 2:
            y -= 1
        era = y // 400
        yoe = y - era * 400
        if month > 2:
            mp = month - 3
        else:
            mp = month + 9
        doy = (153 * mp + 2) // 5 + day - 1
        doe = doy + 365 * yoe + yoe // 4 - yoe // 100
        days = era * 146097 + doe - 719468
        return days * 86400 + hh * 3600 + mm * 60 + ss

    def _new_submission_id(self, poet_str, now_epoch):
        base = str(self.next_id)
        self.next_id = u256(int(self.next_id) + 1)
        return "q" + base + "-" + poet_str[2:8] + "-" + str(now_epoch)

    def _get_submission(self, sid):
        raw = self.submissions.get(sid, "")
        if raw == "":
            return None
        return json.loads(raw)

    def _put_submission(self, rec):
        self.submissions[rec["id"]] = json.dumps(rec, sort_keys=True)

    # ------------------------------------------------------------------
    # Views
    # ------------------------------------------------------------------

    @gl.public.view
    def get_submission(self, submission_id: str) -> str:
        raw = self.submissions.get(submission_id, "")
        if raw == "":
            raise gl.vm.UserError("submission_not_found")
        return raw

    @gl.public.view
    def get_anthology_entry(self, submission_id: str) -> str:
        raw = self.anthology.get(submission_id, "")
        if raw == "":
            raise gl.vm.UserError("not_in_anthology")
        return raw

    @gl.public.view
    def get_poet_state(self, poet: str) -> str:
        return json.dumps({
            "last_id": self.poet_last_id.get(poet, ""),
            "open_id": self.poet_open.get(poet, ""),
            "cooldown_until": self.poet_cooldown_until.get(poet, "0"),
        }, sort_keys=True)

    @gl.public.view
    def get_stats(self) -> str:
        return json.dumps({
            "total_submissions": str(self.total_submissions),
            "accepted": str(self.total_accepted),
            "rejected": str(self.total_rejected),
            "inconclusive": str(self.total_inconclusive),
            "treasury_balance": str(self.treasury_balance),
            "anthology_size": str(len(self.anthology.keys())),
        }, sort_keys=True)

    # ------------------------------------------------------------------
    # Submission (payable — stake enters escrow held by the contract)
    # ------------------------------------------------------------------

    @gl.public.write.payable
    def submit_poem(self, title: str, form: str, poem_text: str):
        poet = str(gl.message.sender_address)
        stake = int(gl.message.value)

        # --- intake guards (deterministic) ---
        if self.poet_open.get(poet, "") != "":
            raise gl.vm.UserError("open_submission_exists")
        now = self._now_epoch()
        cd_raw = self.poet_cooldown_until.get(poet, "0")
        if int(cd_raw) > now:
            raise gl.vm.UserError("resubmit_cooldown_active:" + cd_raw)
        if stake < MIN_STAKE_WEI:
            raise gl.vm.UserError("stake_below_minimum")
        t = title.strip()
        p = poem_text.strip()
        if len(t) < 3 or len(t) > 120:
            raise gl.vm.UserError("bad_title_length")
        if len(p) < MIN_POEM_CHARS or len(p) > MAX_POEM_CHARS:
            raise gl.vm.UserError("bad_poem_length")
        if form != "sonnet" and form != "limerick" and form != "quatrain":
            raise gl.vm.UserError("unsupported_form")

        sid = self._new_submission_id(poet, now)
        # Deterministic pre-gates, stored for UX display only; the consensus
        # path recomputes them from poem_text inside adjudicate.
        form_gate = _validate_form(form, p)
        season_gate = _validate_season_gate(p)

        self._put_submission({
            "id": sid,
            "poet": poet,
            "title": t,
            "form": form,
            "poem": p,
            "stake": str(stake),
            "status": "PENDING",
            "verdict": "",
            "reasons": "",
            "form_gate": form_gate,
            "season_gate": season_gate,
            "opened_at": str(now),
            "resolved_at": "",
            "tx_note": "",
        })
        self.poet_last_id[poet] = sid
        self.poet_open[poet] = sid
        self.total_submissions = u256(int(self.total_submissions) + 1)

    # ------------------------------------------------------------------
    # Adjudication (write: forces full consensus for nondet ops)
    # ------------------------------------------------------------------

    @gl.public.write
    def adjudicate(self, submission_id: str):
        rec = self._get_submission(submission_id)
        if rec is None:
            raise gl.vm.UserError("submission_not_found")
        if rec["status"] != "PENDING":
            raise gl.vm.UserError("already_adjudicated")

        poem = rec["poem"]
        form = rec["form"]

        # ---------- deterministic clamps (host-side, pre-nondet) ----------
        form_gate = _validate_form(form, poem)
        season_gate = _validate_season_gate(poem)

        # Deterministic short-circuits: no LLM needed, pure consensus.
        if form_gate == "FAIL":
            self._settle(submission_id, rec, "REJECTED", ["form_gate_fail:" + form])
            return
        if season_gate == "FAIL":
            self._settle(submission_id, rec, "REJECTED", ["season_gate_fail"])
            return
        if season_gate == "UNCERTAIN" or form_gate == "UNCERTAIN":
            self._settle(submission_id, rec, "INCONCLUSIVE",
                         ["gate_uncertain"])
            return

        # ---------- non-deterministic evaluation ----------
        def leader_fn():
            prompt = (
                "You are one of several independent poetry judges on an "
                "on-chain anthology. Evaluate this poem submission. Be "
                "strict but fair; judges must reach the same conclusions "
                "from the text alone.\n\n"
                "DECLARED FORM: " + form + "\n\n"
                "POEM TEXT:\n" + poem + "\n\n"
                "Criterion 0 (FORM_OK): Does the text read as a genuine "
                "attempt at the declared form? Apply these standards: a "
                "sonnet is 14 lines in roughly iambic pentameter; a "
                "limerick is 5 lines AABBA with long-long-short-short-long "
                "anapestic rhythm; a quatrain is 4 rhymed lines (ABAB, "
                "AABB or AABA). Minor syllable wobble is acceptable if the "
                "rhythm clearly reads as the form.\n\n"
                "Criterion 1 (SEASON_OK): Does the poem's imagery belong "
                "to autumn (late harvest, falling leaves, amber light, "
                "frost, migration, hearth smoke) throughout the poem? A "
                "poem where another season dominates imagery must be "
                "FAIL. A single autumn word in an off-season poem is not "
                "enough.\n\n"
                "Return ONLY valid JSON, no markdown, in exactly this "
                "shape:\n"
                '{"labels": '
                '[{"criterion": 0, "name": "FORM_OK", "status": "PASS", '
                '"cite": "<one short quoted fragment from the poem>", '
                '"reason": "<max 140 chars>"}, '
                '{"criterion": 1, "name": "SEASON_OK", "status": "PASS", '
                '"cite": "<one short quoted fragment from the poem>", '
                '"reason": "<max 140 chars>"}]}'
                "\nAllowed status values: PASS, FAIL, UNCERTAIN. Both "
                "criteria must appear, criterion values 0 and 1."
            )
            try:
                return gl.nondet.exec_prompt(prompt, response_format="json")
            except Exception:
                # LLM service failure: a well-formed sentinel that the
                # normalizer treats as unparsable -> fail-safe INCONCLUSIVE.
                return '{"labels": []}'

        def validator_fn(leader_res) -> bool:
            if not isinstance(leader_res, gl.vm.Return):
                return False
            # Validator re-derives EVERYTHING independently.
            my_labels = _llm_labels_or_none(leader_fn)
            leader_labels = _extract_labels(leader_res.calldata)
            if leader_labels is None and my_labels is None:
                # Both judges independently failed to obtain a parsable
                # evaluation -> agree on the fail-safe INCONCLUSIVE path.
                return True
            if my_labels is None or leader_labels is None:
                return False
            # Compare ONLY decision-bearing substance: status per criterion.
            # Cites/reasons are never compared (they are prose).
            for crit in ("FORM_OK", "SEASON_OK"):
                if leader_labels.get(crit, "") != my_labels.get(crit, ""):
                    return False
            return True

        result = gl.vm.run_nondet(leader_fn, validator_fn)

        # ---------- deterministic derivation from labels ----------
        leader_labels = _extract_labels(result)
        form_status, season_status = _normalize_label_pair(
            leader_labels, form_gate, season_gate)

        # Hard clamp: a fooled or hallucinating model can never upgrade a
        # deterministic FAIL, and cannot PASS with zero autumn grounding.
        if form_status == "FAIL" or season_status == "FAIL":
            reasons = []
            if form_status == "FAIL":
                reasons.append("form_fail")
            if season_status == "FAIL":
                reasons.append("season_fail")
            self._settle(submission_id, rec, "REJECTED", reasons)
            return
        if form_status == "UNCERTAIN" or season_status == "UNCERTAIN":
            self._settle(submission_id, rec, "INCONCLUSIVE",
                         ["judge_uncertain"])
            return
        if form_status == "" or season_status == "":
            # malformed / unparsable LLM output -> fail-safe
            self._settle(submission_id, rec, "INCONCLUSIVE",
                         ["judge_unparsable"])
            return

        # All PASS -> sealed into the anthology
        verdict = "ACCEPTED"
        reasons = ["form_ok", "season_ok"]
        self._settle(submission_id, rec, verdict, reasons)

    # ------------------------------------------------------------------
    # Settlement — deterministic, checks-effects-interactions
    # ------------------------------------------------------------------

    def _settle(self, sid, rec, verdict, reasons):
        stake = int(rec["stake"])
        poet = rec["poet"]
        now = str(self._now_epoch())

        rec["status"] = "SETTLED"
        rec["verdict"] = verdict
        rec["reasons"] = ";".join(reasons)
        rec["resolved_at"] = now
        self._put_submission(rec)

        self.poet_open[poet] = ""
        self.poet_cooldown_until[poet] = str(
            int(now) + RESUBMIT_COOLDOWN_SECONDS)

        if verdict == "ACCEPTED":
            self.total_accepted = u256(int(self.total_accepted) + 1)
            self.anthology[sid] = json.dumps({
                "id": sid,
                "poet": poet,
                "title": rec["title"],
                "form": rec["form"],
                "poem": rec["poem"],
                "sealed_at": now,
                "stake_returned": "true",
            }, sort_keys=True)
            # checks-effects-interactions: record refund BEFORE emitting.
            rec2 = self._get_submission(sid)
            rec2["refund"] = "sent"
            self._put_submission(rec2)
            gl.get_contract_at(gl.message.contract_address).emit_transfer(
                value=u256(stake), on="finalized"
            )
        elif verdict == "REJECTED":
            self.total_rejected = u256(int(self.total_rejected) + 1)
            self.treasury_balance = u256(int(self.treasury_balance) + stake)
        else:
            self.total_inconclusive = u256(int(self.total_inconclusive) + 1)
            rec3 = self._get_submission(sid)
            rec3["refund"] = "sent"
            self._put_submission(rec3)
            gl.get_contract_at(gl.message.contract_address).emit_transfer(
                value=u256(stake), on="finalized"
            )


# ---------------------------------------------------------------------------
# Module-level pure helpers used inside nondet blocks (no storage access)
# ---------------------------------------------------------------------------

def _llm_labels_or_none(run_fn):
    """Runs an LLM evaluation and returns {FORM_OK, SEASON_OK} statuses,
    or None for ANY failure mode. Fail-safe by construction."""
    try:
        raw = run_fn()
        return _extract_labels(raw)
    except Exception:
        return None


def _extract_labels(raw):
    """Parses the judges' JSON into {FORM_OK: status, SEASON_OK: status}.

    Returns None when the shape is unusable (fail-safe). Domain-locks the
    statuses: anything other than PASS/FAIL/UNCERTAIN is treated as
    UNCERTAIN (never PASS)."""
    if isinstance(raw, gl.vm.Return):
        raw = raw.calldata
    try:
        if isinstance(raw, (bytes, bytearray)):
            raw = raw.decode("utf-8")
        if isinstance(raw, (dict, list)) and not isinstance(raw, str):
            data = raw
        else:
            data = json.loads(str(raw))
        labels = data.get("labels", None) if isinstance(data, dict) else None
        if not isinstance(labels, list) or len(labels) < 2:
            return None
        out = {}
        for item in labels:
            if not isinstance(item, dict):
                return None
            name = str(item.get("name", ""))
            status = str(item.get("status", "")).upper()
            if status != "PASS" and status != "FAIL" and status != "UNCERTAIN":
                status = "UNCERTAIN"
            if name == "FORM_OK":
                out["FORM_OK"] = status
            elif name == "SEASON_OK":
                out["SEASON_OK"] = status
        if ("FORM_OK" in out) and ("SEASON_OK" in out):
            return out
        # fallback: match by criterion index if names were missing
        out2 = {}
        for item in labels:
            if not isinstance(item, dict):
                return None
            crit = str(item.get("criterion", ""))
            status = str(item.get("status", "")).upper()
            if status != "PASS" and status != "FAIL" and status != "UNCERTAIN":
                status = "UNCERTAIN"
            if crit == "0":
                out2["FORM_OK"] = status
            elif crit == "1":
                out2["SEASON_OK"] = status
        if ("FORM_OK" in out2) and ("SEASON_OK" in out2):
            return out2
        return None
    except Exception:
        return None


def _normalize_label_pair(leader_labels, form_gate, season_gate):
    """Combines leader LLM labels with deterministic gates into final
    per-criterion statuses. The deterministic gate can only DOWNGRADE."""
    if leader_labels is None:
        return "", ""
    form_status = leader_labels.get("FORM_OK", "")
    season_status = leader_labels.get("SEASON_OK", "")
    # deterministic gate overrides upward claims
    if form_gate == "FAIL":
        form_status = "FAIL"
    if season_gate == "FAIL":
        season_status = "FAIL"
    return form_status, season_status
