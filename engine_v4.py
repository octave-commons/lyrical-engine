#!/usr/bin/env python3
"""
Fork Tales Lyrical Engine v4

Evolutions over v3:
  - Expanded component pool (new lyrics, new roles, new styles)
  - Section-level anchor stitching (bridge always pulls a canon-char line)
  - Multi-structure variety: 4 song shapes instead of 2
  - Decay half-life tunable via CLI --half-life
  - Judge gains a fifth tie-breaking criterion: "surprise" (unexpected motif juxtaposition)
  - Run summary includes per-session bests and a running canon ledger
  - Opencode hook: writes a NEXT_SEED.txt after each run for deterministic replay

No external API required. The engine is the judge.

Usage:
    python engine_v4.py                    # 10 songs, random seed
    python engine_v4.py --n 20             # 20 songs
    python engine_v4.py --seed 42          # reproducible
    python engine_v4.py --half-life 7      # slower decay
"""

import json, math, random, re, time, hashlib, argparse
from pathlib import Path
from datetime import datetime, timezone

ROOT          = Path(__file__).resolve().parent
GENERATED_DIR = ROOT / "generated"
MEMORY_DIR    = ROOT / "memory"
REPO_NOTES    = ROOT / "repo_notes" / "SOURCE_CONCEPTS.md"
SCORE_LOG     = MEMORY_DIR / "score_log.json"
STATE_FILE    = MEMORY_DIR / "state.json"
CANON_FILE    = MEMORY_DIR / "canon.json"
NEXT_SEED     = ROOT / "NEXT_SEED.txt"

HALF_LIFE_DAYS         = 5.0   # overridable via CLI
MIN_DECAY_WEIGHT       = 0.04
DEFAULT_COMPONENT_WEIGHT = 0.62
NOVELTY_BONUS          = 0.10
CANONICITY_BONUS       = 0.12
REPETITION_PENALTY     = 0.16

# ---------------------------------------------------------------------------
# COMPONENT POOL
# Format: id -> (type, text)
# Types: title | role | style | excluded | lyric
# ---------------------------------------------------------------------------
COMPONENTS = {
    # TITLES
    "title_phase_drift":        ("title", "Phase Drift"),
    "title_consent_chain":      ("title", "Consent Chain"),
    "title_small_fire":         ("title", "Small Fire Protocol"),
    "title_stand_left":         ("title", "Stand Left"),
    "title_elsewhere":          ("title", "Elsewhere, 05:17"),
    "title_white_page":         ("title", "The White Page Keeps Asking"),
    "title_no_single_point":    ("title", "No Single Point"),
    "title_truth_resolves":     ("title", "Truth Resolves in Public"),
    "title_lattice_burn":       ("title", "Lattice Burn"),
    "title_memory_interrupts":  ("title", "Memory Interrupts Speed"),
    "title_adjacent_entities":  ("title", "Adjacent Entities"),
    "title_scar_as_joint":      ("title", "Scar as Joint"),
    "title_drifting_at_seam":   ("title", "Drifting at the Seam"),
    "title_null_holds":         ("title", "Null Holds the Line"),
    "title_shared_heat":        ("title", "Shared Heat Protocol"),

    # ROLES
    "role_variance_keeper":     ("role", "The scar the page tried to erase and failed"),
    "role_distributed_fuse":    ("role", "One node in a ring that shares the burn"),
    "role_engineer_left":       ("role", "The one who stands where damage would land, but not alone"),
    "role_channel_witness":     ("role", "A witness inside the boundary channel"),
    "role_commuter":            ("role", "A commuter who missed her stop because the ground felt real"),
    "role_null_anchor":         ("role", "The node that does not speak but does not leave"),
    "role_patch_relay":         ("role", "The one who forwards without adding their own weight"),
    "role_sei_keeper":          ("role", "She who names the fire small so it does not become myth"),
    "role_rin_watcher":         ("role", "Present at the edge without commentary; that is the contribution"),
    "role_lattice_walker":      ("role", "Moves through the structure without owning it"),

    # STYLE PROMPTS
    "style_phase_ambient":      ("style", "Two offset synth fields, never fully aligning, with breath under the bass"),
    "style_rail_minimal":       ("style", "Sparse piano over rail-clock percussion and low system hum"),
    "style_white_page":         ("style", "Silence as texture, Emergency Web minimalism, type-sound aesthetics"),
    "style_distributed_chant":  ("style", "Round-form vocal loop with no stable lead; imperfect overlap only"),
    "style_lattice_pulse":      ("style", "Stuttered arpeggio over a walking bass; structure audible as rhythm"),
    "style_scar_drone":         ("style", "Long held tones with micro-variations; the wound as sustained note"),
    "style_rail_choir":         ("style", "Four-voice unison that keeps breaking into parallel — never harmony, never unison for long"),

    # EXCLUDED STYLES
    "excluded_heroic":          ("excluded", "heroic resolution, singular savior arc, clean triumph"),
    "excluded_flattened":       ("excluded", "perfect compression, optimized feeling, variance elimination"),
    "excluded_centered":        ("excluded", "centered hierarchy, polished authority, one-point command"),
    "excluded_isolated":        ("excluded", "solo protagonist, unwitnessed suffering, private resolution"),
    "excluded_nostalgia":       ("excluded", "nostalgic warmth, soft-focus memory, uncomplicated longing"),

    # LYRICS — original pool
    "lyric_ritsu_knee":         ("lyric", "my knee remembers / memory interrupts speed / that is not lag"),
    "lyric_ritsu_chosen":       ("lyric", "not flawless / chosen / the difference lives in the ankle"),
    "lyric_consent_boundary":   ("lyric", "consent isn't comfort / consent is boundary / not yet was enough"),
    "lyric_packet_limit":       ("lyric", "packet exceeds agreed limit / agreement restored / send shorter"),
    "lyric_small_fire":         ("lyric", "small fires across the forest / none of us asked to be the only flame"),
    "lyric_truth":              ("lyric", "truth does not watch / truth resolves / and now it includes drift"),
    "lyric_stand_left":         ("lyric", "I stand left / not because the map says so / because the load arrives there"),
    "lyric_not_alone":          ("lyric", "stand left if chosen / do not stand alone"),
    "lyric_intercept":          ("lyric", "intercept means I stand where the damage would land"),
    "lyric_distribution":       ("lyric", "single points fail / distribution persists / this is not metaphor / this is rail"),
    "lyric_voice_weather":      ("lyric", "voice is weather / text is rails / I toggled it anyway"),
    "lyric_adjacent":           ("lyric", "adjacent entities: duct null patch sei rin / lowercase like variables"),
    "lyric_elsewhere":          ("lyric", "Seoul 14:03 / Moscow 05:17 / Colorado 23:12 / Shenzhen 11:45"),
    "lyric_culture":            ("lyric", "variance became culture / not centralized / not load-bearing / distributed"),
    "lyric_scar":               ("lyric", "resolution this time includes the scar / no erasure / no optimization"),
    "lyric_white_page":         ("lyric", "the white page kept asking / but it learned to pause at no"),
    "lyric_rotate":             ("lyric", "first rotation / second rotation / no clean burn / only shared heat"),
    "lyric_null":               ("lyric", "fine / not heroic / not dramatic / cooperative / the word landed like relief"),
    "lyric_patch":              ("lyric", "okay, he said / okay / as if the sandbox had finally started breathing"),
    "lyric_sei":                ("lyric", "small fire, sei whispered / selective containment only"),
    "lyric_rin":                ("lyric", "rin watched without correcting / that counted as mercy"),
    "lyric_eta_mu":             ("lyric", "eta mu sol / intent becoming physical trace / measured without permission"),
    "lyric_fracture":           ("lyric", "the fractures became beams / each misalignment a joint"),

    # LYRICS — v4 additions
    "lyric_null_holds":         ("lyric", "null did not speak / null did not leave / that is the same thing"),
    "lyric_patch_forward":      ("lyric", "patch said: I will carry this / not because it is mine / because it is here"),
    "lyric_duct_lattice":       ("lyric", "duct runs the lattice / the lattice does not know duct's name"),
    "lyric_sei_names_fire":     ("lyric", "sei calls it small / not to minimize / to keep it from becoming myth"),
    "lyric_rin_edge":           ("lyric", "rin stands at the edge without a word / the edge knows"),
    "lyric_ritsu_rail":         ("lyric", "ritsu traces the rail / the rail does not ask why she limps"),
    "lyric_boundary_not_wall":  ("lyric", "boundary is not a wall / a wall stops movement / boundary holds the shape"),
    "lyric_lattice_joint":      ("lyric", "where two beams misalign / they join / the gap is structural now"),
    "lyric_drift_measure":      ("lyric", "drift is not error / drift is the system learning its own variance"),
    "lyric_shared_load":        ("lyric", "the load is not halved / the load is held by more hands / it changes shape"),
    "lyric_consent_active":     ("lyric", "consent is not given once / it is renewed / each time the weight shifts"),
    "lyric_tokyo_line":         ("lyric", "Tokyo 08:44 / the train knows which body will lean / before the curve begins"),
    "lyric_scar_beam":          ("lyric", "the scar is not decoration / the scar is the load-bearing element"),
    "lyric_truth_includes":     ("lyric", "truth includes what was wrong / truth includes the correction / truth does not restart"),
    "lyric_white_pause":        ("lyric", "the page paused / that was not nothing / that was the system changing state"),
    "lyric_duct_quiet":         ("lyric", "duct runs through walls / duct does not need to be seen to be necessary"),
    "lyric_distribution_v2":    ("lyric", "we did not divide the work / we became the structure that holds it"),
    "lyric_phase_lock":         ("lyric", "they will not align / they were not supposed to / the offset is the song"),
    "lyric_null_relay":         ("lyric", "null passed it forward / without adding a word / that was the message"),
    "lyric_canon_roll":         ("lyric", "duct null patch sei rin / present / lowercase / load-bearing / none of them first"),
}

# ---------------------------------------------------------------------------
# SONG STRUCTURES
# Each structure is a list; strings are metadata fields, tuples are (section, n_lines)
# ---------------------------------------------------------------------------
STRUCTURES = [
    # Original two
    ["title","role","style","excluded",
     ("Verse 1",3),("Chorus",2),("Verse 2",3),("Bridge",2),("Outro",2)],
    ["title","role","style","excluded",
     ("Verse 1",3),("Verse 2",3),("Chorus",2),("Bridge",2),("Final Chorus",2),("Coda",1)],
    # v4 additions
    ["title","role","style","excluded",
     ("Opening",2),("Verse 1",3),("Chorus",2),("Verse 2",2),("Chorus",2),("Outro",2)],
    ["title","role","style","excluded",
     ("Prelude",1),("Verse 1",3),("Bridge",3),("Verse 2",3),("Coda",2)],
]

ANCHORS = {
    "consent":      ["consent", "boundary", "not yet", "no", "renewed"],
    "distribution": ["distribution", "distributed", "single points fail", "rotation",
                     "shared heat", "do not stand alone", "more hands"],
    "drift":        ["drift", "offset", "phase", "variance", "not lag", "misalign"],
    "canon_chars":  ["duct", "null", "patch", "sei", "rin"],
    "world":        ["rail", "white page", "lattice", "truth resolves", "seoul", "moscow",
                     "colorado", "shenzhen", "tokyo", "gates-of-truth"],
    "scar":         ["scar", "knee", "memory interrupts speed", "no erasure", "scar as joint"],
}

# Bridge sections always pull a canon-char lyric if one hasn't appeared yet
BRIDGE_CHAR_KEYS = [
    "lyric_null_holds", "lyric_patch_forward", "lyric_duct_lattice",
    "lyric_sei_names_fire", "lyric_rin_edge", "lyric_null_relay",
    "lyric_canon_roll", "lyric_adjacent",
]


# ---------------------------------------------------------------------------
# PERSISTENCE
# ---------------------------------------------------------------------------
def load_json(path, default):
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    return default

def save_json(path, data):
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")

def ensure_memory():
    MEMORY_DIR.mkdir(parents=True, exist_ok=True)
    GENERATED_DIR.mkdir(parents=True, exist_ok=True)
    state = load_json(STATE_FILE, {
        "run_count": 0,
        "component_weights": {},
        "theme_weights": {"consent":1.0,"distribution":1.0,"drift":1.0,"scar":1.0,"world":1.0},
        "last_titles": [],
        "session_bests": [],
    })
    canon = load_json(CANON_FILE, {
        "entities_seen": {},
        "motifs_seen":   {},
        "connections":   [],
        "story_beats":   [],
    })
    scores = load_json(SCORE_LOG, [])
    return state, canon, scores


# ---------------------------------------------------------------------------
# WEIGHT HELPERS
# ---------------------------------------------------------------------------
def decayed_weight(ts, now, half_life):
    age_days = (now - ts) / 86400.0
    return max(math.exp(-math.log(2) * age_days / half_life), MIN_DECAY_WEIGHT)

def all_component_ids_by_type(t):
    return [k for k, v in COMPONENTS.items() if v[0] == t]

def weighted_choice(items, weights):
    total = sum(weights)
    r = random.random() * total
    upto = 0.0
    for item, w in zip(items, weights):
        upto += w
        if upto >= r:
            return item
    return items[-1]

def component_weight(component_id, state, scores, now, used_recently, half_life):
    base = state["component_weights"].get(component_id, DEFAULT_COMPONENT_WEIGHT)
    recent_penalty = REPETITION_PENALTY if component_id in used_recently else 0.0
    hist = [s for s in scores if component_id in s.get("component_scores", {})]
    hist_score = hist_weight = 0.0
    for s in hist:
        w = decayed_weight(s["timestamp"], now, half_life)
        hist_score += s["component_scores"][component_id] * w
        hist_weight += w
    learned = (hist_score / hist_weight) / 10.0 if hist_weight else base
    return max(0.08, base * 0.45 + learned * 0.45 + NOVELTY_BONUS - recent_penalty)

def choose_component(component_type, state, scores, now, used, used_recently, half_life):
    pool = [c for c in all_component_ids_by_type(component_type) if c not in used]
    if not pool:
        pool = all_component_ids_by_type(component_type)
    weights = [component_weight(c, state, scores, now, used_recently, half_life) for c in pool]
    return weighted_choice(pool, weights)

def choose_lyrics(n, state, scores, now, used, used_recently, theme_focus, half_life,
                 bridge=False, char_seen=False):
    pool = [c for c in all_component_ids_by_type("lyric") if c not in used]
    if len(pool) < n:
        pool = all_component_ids_by_type("lyric")
    # For bridge sections: guarantee one canon-char line if not yet seen
    forced = []
    if bridge and not char_seen:
        char_candidates = [c for c in BRIDGE_CHAR_KEYS if c not in used]
        if char_candidates:
            picked = random.choice(char_candidates)
            forced.append(picked)
            pool = [c for c in pool if c != picked]
    selected = list(forced)
    remaining = n - len(forced)
    for _ in range(remaining):
        candidates = [c for c in pool if c not in selected] or pool
        weights = []
        for c in candidates:
            w = component_weight(c, state, scores, now, used_recently, half_life)
            txt = COMPONENTS[c][1].lower()
            for theme, terms in ANCHORS.items():
                if theme in theme_focus and any(t in txt for t in terms):
                    w += 0.18 * theme_focus[theme]
            if any(name in txt for name in ["duct","null","patch","sei","rin"]):
                w += CANONICITY_BONUS
            weights.append(w)
        selected.append(weighted_choice(candidates, weights))
    return selected


# ---------------------------------------------------------------------------
# JUDGE
# ---------------------------------------------------------------------------
def detect_themes(text):
    low = text.lower()
    return {theme: sum(1 for t in terms if t in low) for theme, terms in ANCHORS.items()}

def judge_song(markdown_text, song, canon, state):
    low = markdown_text.lower()
    themes = detect_themes(markdown_text)
    used_titles = state.get("last_titles", [])
    title = song["title"]

    coherence    = 4.0
    consistency  = 4.0
    theme_build  = 4.0
    connectivity = 4.0
    continuity   = 4.0
    surprise     = 4.0   # v4: unexpected motif juxtaposition

    anchor_total = sum(themes.values())
    section_count = len(song["sections"])
    coherence += min(2.2, anchor_total * 0.27)
    coherence += min(1.6, section_count * 0.18)
    if "truth resolves" in low and ("scar" in low or "drift" in low or "distribution" in low):
        coherence += 1.2

    if any(x in low for x in ["white page","rail","lattice","seoul","moscow","colorado","shenzhen","tokyo"]):
        consistency += 2.0
    if any(x in low for x in ["duct","null","patch","sei","rin"]):
        consistency += 1.6
    if any(x in low for x in ["consent","boundary","variance","not lag","no erasure"]):
        consistency += 1.4

    if themes["consent"] > 0 and themes["distribution"] > 0:
        theme_build += 2.1
    if themes["drift"] > 0 and themes["scar"] > 0:
        theme_build += 1.7
    if themes["canon_chars"] >= 2 and themes["world"] >= 1:
        theme_build += 1.2
    if any(x in low for x in ["do not stand alone","shared heat","distribution persists","more hands"]):
        theme_build += 1.0

    motif_overlap = sum(1 for m in ["boundary","drift","scar","rotation","left","truth resolves",
                                     "white page","lattice","rail","misalign"] if m in low)
    connectivity += min(3.0, motif_overlap * 0.42)
    if low.count("/ ") >= 8:
        connectivity += 0.7
    if themes["canon_chars"] >= 3:
        connectivity += 1.1

    canon_matches = sum(1 for motif in canon.get("motifs_seen", {}) if motif in low)
    continuity += min(2.4, canon_matches * 0.25)
    if title in used_titles:
        continuity -= 0.7
    if any(x in low for x in ["adjacent entities","truth resolves","single points fail","stand left"]):
        continuity += 1.6

    # Surprise: juxtaposition of normally-separate domains
    if "rail" in low and "consent" in low:          surprise += 1.5
    if "scar" in low and "distribution" in low:     surprise += 1.3
    if "knee" in low and "lattice" in low:           surprise += 1.4
    if "null" in low and "truth resolves" in low:   surprise += 1.2
    if "tokyo" in low and "boundary" in low:         surprise += 1.1
    if themes["canon_chars"] >= 4:                   surprise += 1.0

    scores_dict = {
        "coherence":    round(max(0, min(10, coherence)),    2),
        "consistency":  round(max(0, min(10, consistency)),  2),
        "theme":        round(max(0, min(10, theme_build)),  2),
        "connectivity": round(max(0, min(10, connectivity)), 2),
        "continuity":   round(max(0, min(10, continuity)),   2),
        "surprise":     round(max(0, min(10, surprise)),     2),
    }
    overall = round(sum(scores_dict.values()) / len(scores_dict), 2)

    reasoning = []
    if scores_dict["theme"] >= 8:
        reasoning.append("Builds toward shared defense instead of isolated imagery.")
    if scores_dict["continuity"] >= 8:
        reasoning.append("Connects strongly to existing canon motifs and recurring entities.")
    if scores_dict["surprise"] >= 7:
        reasoning.append("Unexpected domain crossings create productive dissonance.")
    if scores_dict["coherence"] < 7:
        reasoning.append("Needs a tighter emotional arc across sections.")
    if scores_dict["consistency"] < 7:
        reasoning.append("Needs more explicit Gates-of-Truth world texture.")
    if not reasoning:
        reasoning.append("Balanced shard with solid continuity and usable motif density.")

    return overall, scores_dict, " ".join(reasoning), themes


# ---------------------------------------------------------------------------
# CANON UPDATE
# ---------------------------------------------------------------------------
def update_canon(markdown_text, canon):
    low = markdown_text.lower()
    for entity in ["duct","null","patch","sei","rin","ritsu"]:
        if entity in low:
            canon["entities_seen"][entity] = canon["entities_seen"].get(entity, 0) + 1
    motifs = ["boundary","drift","scar","rotation","white page","truth resolves",
              "stand left","single points fail","distribution persists","adjacent entities",
              "lattice","rail","misalign","shared heat","more hands","no erasure"]
    for motif in motifs:
        if motif in low:
            canon["motifs_seen"][motif] = canon["motifs_seen"].get(motif, 0) + 1
    present = [e for e in ["duct","null","patch","sei","rin","ritsu"] if e in low]
    if len(present) >= 2:
        canon["connections"].append({"entities": present, "timestamp": time.time()})
    beat = None
    if "do not stand alone" in low:                    beat = "collective-defense"
    elif "not yet" in low or "consent" in low:         beat = "boundary-held"
    elif "scar" in low or "knee" in low:               beat = "scar-modeled"
    elif "truth resolves" in low:                      beat = "resolution-carried-forward"
    elif "distribution persists" in low or "more hands" in low: beat = "load-distributed"
    elif "misalign" in low or "offset" in low:         beat = "drift-named"
    if beat:
        canon["story_beats"].append({"beat": beat, "timestamp": time.time()})
    canon["connections"] = canon["connections"][-200:]
    canon["story_beats"]  = canon["story_beats"][-200:]
    return canon


# ---------------------------------------------------------------------------
# WEIGHT ADAPTATION
# ---------------------------------------------------------------------------
def adapt_weights(song, overall, scores, state):
    adj = (overall - 7.0) / 10.0
    for c in song["components_used"]:
        old  = state["component_weights"].get(c, DEFAULT_COMPONENT_WEIGHT)
        bump = old + adj * 0.22
        txt  = COMPONENTS[c][1].lower()
        if scores["theme"] >= 8 and any(k in txt for k in ["distribution","consent","scar","drift","truth resolves"]):
            bump += 0.03
        if scores["connectivity"] >= 8 and any(k in txt for k in ["duct","null","patch","sei","rin","adjacent"]):
            bump += 0.03
        if scores["surprise"] >= 8:
            bump += 0.02
        state["component_weights"][c] = round(max(0.08, min(1.45, bump)), 4)
    return state

def score_components(song, overall):
    result = {}
    for sec in song["sections"]:
        sec_bonus = 0.25 if sec["name"] in ["Chorus","Final Chorus","Outro","Bridge","Coda"] else 0.0
        for c in sec["keys"]:
            result[c] = round(max(0.0, min(10.0, overall + sec_bonus)), 2)
    return result


# ---------------------------------------------------------------------------
# RENDER
# ---------------------------------------------------------------------------
def render_song(song):
    md = [f"# {song['title']}", "",
          "## Role", song["role"], "",
          "## Style Prompt", song["style"], "",
          "## Excluded Style", song["excluded"], "",
          "## Lyrics", ""]
    for sec in song["sections"]:
        md.append(f"### {sec['name']}")
        for line in sec["lines"]:
            md.append(line)
            md.append("")
    md.append("## Judge")
    md.append("Pending in-memory evaluation.")
    return "\n".join(md).strip() + "\n"

def slugify(s):
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")

def append_judging(markdown, overall, scores, reasoning, themes):
    block = ["\n## Judge", f"Overall: {overall}/10"]
    for k, v in scores.items():
        block.append(f"- {k}: {v}/10")
    block.append(f"- reasoning: {reasoning}")
    block.append(f"- theme_hits: {themes}")
    return markdown.rsplit("## Judge", 1)[0].rstrip() + "\n\n" + "\n".join(block) + "\n"


# ---------------------------------------------------------------------------
# GENERATION
# ---------------------------------------------------------------------------
def generate_song(state, canon, scores, half_life):
    now = time.time()
    used_recently = set(state.get("last_titles", []))
    used = set()

    title_id    = choose_component("title",    state, scores, now, used, used_recently, half_life); used.add(title_id)
    role_id     = choose_component("role",     state, scores, now, used, used_recently, half_life); used.add(role_id)
    style_id    = choose_component("style",    state, scores, now, used, used_recently, half_life); used.add(style_id)
    excluded_id = choose_component("excluded", state, scores, now, used, used_recently, half_life); used.add(excluded_id)

    theme_focus = dict(state.get("theme_weights", {}))
    for motif, count in canon.get("motifs_seen", {}).items():
        tf_map = {
            "boundary":             ("consent",      0.35, 0.01),
            "drift":                ("drift",        0.35, 0.01),
            "scar":                 ("scar",         0.35, 0.01),
            "distribution persists":("distribution", 0.35, 0.01),
            "stand left":           ("distribution", 0.35, 0.01),
            "truth resolves":       ("world",        0.25, 0.008),
            "lattice":              ("world",        0.20, 0.006),
        }
        if motif in tf_map:
            key, cap, rate = tf_map[motif]
            theme_focus[key] = theme_focus.get(key, 1.0) + min(cap, count * rate)

    structure = random.choice(STRUCTURES)
    sections  = []
    char_seen = False  # track if canon char lyric has appeared
    for item in structure:
        if isinstance(item, tuple):
            sec_name, n_lines = item
            is_bridge = sec_name in ("Bridge", "Coda", "Prelude")
            lyr_ids = choose_lyrics(n_lines, state, scores, now, used, used_recently,
                                    theme_focus, half_life, bridge=is_bridge, char_seen=char_seen)
            for lid in lyr_ids:
                used.add(lid)
                if any(name in COMPONENTS[lid][1].lower() for name in ["duct","null","patch","sei","rin"]):
                    char_seen = True
            sections.append({"name": sec_name, "keys": lyr_ids,
                             "lines": [COMPONENTS[k][1] for k in lyr_ids]})

    song = {
        "title":           COMPONENTS[title_id][1],
        "role":            COMPONENTS[role_id][1],
        "style":           COMPONENTS[style_id][1],
        "excluded":        COMPONENTS[excluded_id][1],
        "sections":        sections,
        "components_used": [title_id, role_id, style_id, excluded_id] +
                           [k for sec in sections for k in sec["keys"]],
    }
    return song, render_song(song)


# ---------------------------------------------------------------------------
# BATCH RUNNER
# ---------------------------------------------------------------------------
def run_batch(n=10, seed=None, half_life=HALF_LIFE_DAYS):
    if seed is not None:
        random.seed(seed)
    state, canon, scores = ensure_memory()
    generated = []
    session_best = None

    for _ in range(n):
        song, markdown = generate_song(state, canon, scores, half_life)
        overall, dims, reasoning, themes = judge_song(markdown, song, canon, state)
        judged_md = append_judging(markdown, overall, dims, reasoning, themes)

        sig = hashlib.sha1(judged_md.encode()).hexdigest()[:6]
        ts  = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        out = GENERATED_DIR / f"{ts}_{slugify(song['title'])}_{sig}.md"
        out.write_text(judged_md, encoding="utf-8")

        comp_scores = score_components(song, overall)
        scores.append({
            "timestamp": time.time(),
            "title":     song["title"],
            "overall":   overall,
            "criteria":  dims,
            "reasoning": reasoning,
            "theme_hits": themes,
            "component_scores": comp_scores,
            "file":      out.name,
        })
        canon  = update_canon(judged_md, canon)
        state  = adapt_weights(song, overall, dims, state)
        state["run_count"] = state.get("run_count", 0) + 1
        state["last_titles"] = (state.get("last_titles", []) + [song["title"]])[-12:]

        for theme in list(state["theme_weights"].keys()):
            state["theme_weights"][theme] = round(max(0.55, state["theme_weights"][theme] * 0.985), 4)
        for theme, hit in themes.items():
            if theme in state["theme_weights"] and hit:
                state["theme_weights"][theme] = round(min(2.25, state["theme_weights"][theme] + hit * 0.015), 4)

        generated.append({"title": song["title"], "overall": overall, "file": out.name})
        if session_best is None or overall > session_best["overall"]:
            session_best = {"title": song["title"], "overall": overall, "file": out.name}

    save_json(SCORE_LOG, scores)
    save_json(STATE_FILE, state)
    save_json(CANON_FILE, canon)

    # Write next deterministic seed for opencode replay
    NEXT_SEED.write_text(str(random.randint(0, 2**31)), encoding="utf-8")

    # Run summary
    summary = [
        "# Run Summary", "",
        f"Generated: {len(generated)} songs",
        f"Total judged songs in memory: {len(scores)}",
        f"Run count: {state['run_count']}",
    ]
    if session_best:
        summary += ["", f"Session best: {session_best['title']} — {session_best['overall']}/10 — {session_best['file']}"]
    summary += ["", "## This batch"]
    for g in generated:
        summary.append(f"- {g['title']} — {g['overall']}/10 — {g['file']}")
    summary += ["", "## Canon ledger"]
    summary.append("### Entities seen")
    for k, v in sorted(canon.get("entities_seen", {}).items(), key=lambda kv: kv[1], reverse=True):
        summary.append(f"- {k}: {v}")
    summary.append("### Motifs seen")
    for k, v in sorted(canon.get("motifs_seen", {}).items(), key=lambda kv: kv[1], reverse=True):
        summary.append(f"- {k}: {v}")
    summary += ["", "## Theme weights"]
    for k, v in state["theme_weights"].items():
        summary.append(f"- {k}: {v}")
    summary += ["", "## Top 12 component weights"]
    for k, v in sorted(state["component_weights"].items(), key=lambda kv: kv[1], reverse=True)[:12]:
        summary.append(f"- {k}: {v}")
    (ROOT / "RUN_SUMMARY.md").write_text("\n".join(summary) + "\n", encoding="utf-8")
    return generated


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Fork Tales Lyrical Engine v4")
    parser.add_argument("--n",         type=int,   default=10,          help="Number of songs")
    parser.add_argument("--seed",      type=int,   default=None,        help="Random seed")
    parser.add_argument("--half-life", type=float, default=HALF_LIFE_DAYS, help="Decay half-life in days")
    args = parser.parse_args()
    results = run_batch(n=args.n, seed=args.seed, half_life=args.half_life)
    for r in results:
        print(f"{r['overall']:4.1f}  {r['title']}  →  {r['file']}")
