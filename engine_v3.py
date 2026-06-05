#!/usr/bin/env python3
"""
Fork Tales Lyrical Engine v3

Self-contained: generates songs, judges them internally, saves every score,
and adapts component weights over time with exponential decay.

No external API required. The engine is the judge.

Usage:
    python engine_v3.py             # runs 10 songs (default seed)
    python engine_v3.py --n 20      # custom batch size
    python engine_v3.py --seed 42   # reproducible run
"""

import json, math, random, re, time, hashlib, argparse
from pathlib import Path
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parent
GENERATED_DIR = ROOT / "generated"
MEMORY_DIR = ROOT / "memory"
REPO_NOTES = ROOT / "repo_notes" / "SOURCE_CONCEPTS.md"
SCORE_LOG = MEMORY_DIR / "score_log.json"
STATE_FILE = MEMORY_DIR / "state.json"
CANON_FILE = MEMORY_DIR / "canon.json"

HALF_LIFE_DAYS = 5.0
MIN_DECAY_WEIGHT = 0.04
DEFAULT_COMPONENT_WEIGHT = 0.62
NOVELTY_BONUS = 0.10
CANONICITY_BONUS = 0.12
REPETITION_PENALTY = 0.16

COMPONENTS = {
    "title_phase_drift": ("title", "Phase Drift"),
    "title_consent_chain": ("title", "Consent Chain"),
    "title_small_fire": ("title", "Small Fire Protocol"),
    "title_stand_left": ("title", "Stand Left"),
    "title_elsewhere": ("title", "Elsewhere, 05:17"),
    "title_white_page": ("title", "The White Page Keeps Asking"),
    "title_no_single_point": ("title", "No Single Point"),
    "title_truth_resolves": ("title", "Truth Resolves in Public"),

    "role_variance_keeper": ("role", "The scar the page tried to erase and failed"),
    "role_distributed_fuse": ("role", "One node in a ring that shares the burn"),
    "role_engineer_left": ("role", "The one who stands where damage would land, but not alone"),
    "role_channel_witness": ("role", "A witness inside the boundary channel"),
    "role_commuter": ("role", "A commuter who missed her stop because the ground felt real"),

    "style_phase_ambient": ("style", "Two offset synth fields, never fully aligning, with breath under the bass"),
    "style_rail_minimal": ("style", "Sparse piano over rail-clock percussion and low system hum"),
    "style_white_page": ("style", "Silence as texture, Emergency Web minimalism, type-sound aesthetics"),
    "style_distributed_chant": ("style", "Round-form vocal loop with no stable lead; imperfect overlap only"),

    "excluded_heroic": ("excluded", "heroic resolution, singular savior arc, clean triumph"),
    "excluded_flattened": ("excluded", "perfect compression, optimized feeling, variance elimination"),
    "excluded_centered": ("excluded", "centered hierarchy, polished authority, one-point command"),

    "lyric_ritsu_knee": ("lyric", "my knee remembers / memory interrupts speed / that is not lag"),
    "lyric_ritsu_chosen": ("lyric", "not flawless / chosen / the difference lives in the ankle"),
    "lyric_consent_boundary": ("lyric", "consent isn't comfort / consent is boundary / not yet was enough"),
    "lyric_packet_limit": ("lyric", "packet exceeds agreed limit / agreement restored / send shorter"),
    "lyric_small_fire": ("lyric", "small fires across the forest / none of us asked to be the only flame"),
    "lyric_truth": ("lyric", "truth does not watch / truth resolves / and now it includes drift"),
    "lyric_stand_left": ("lyric", "I stand left / not because the map says so / because the load arrives there"),
    "lyric_not_alone": ("lyric", "stand left if chosen / do not stand alone"),
    "lyric_intercept": ("lyric", "intercept means I stand where the damage would land"),
    "lyric_distribution": ("lyric", "single points fail / distribution persists / this is not metaphor / this is rail"),
    "lyric_voice_weather": ("lyric", "voice is weather / text is rails / I toggled it anyway"),
    "lyric_adjacent": ("lyric", "adjacent entities: duct null patch sei rin / lowercase like variables"),
    "lyric_elsewhere": ("lyric", "Seoul 14:03 / Moscow 05:17 / Colorado 23:12 / Shenzhen 11:45"),
    "lyric_culture": ("lyric", "variance became culture / not centralized / not load-bearing / distributed"),
    "lyric_scar": ("lyric", "resolution this time includes the scar / no erasure / no optimization"),
    "lyric_white_page": ("lyric", "the white page kept asking / but it learned to pause at no"),
    "lyric_rotate": ("lyric", "first rotation / second rotation / no clean burn / only shared heat"),
    "lyric_null": ("lyric", "fine / not heroic / not dramatic / cooperative / the word landed like relief"),
    "lyric_patch": ("lyric", "okay, he said / okay / as if the sandbox had finally started breathing"),
    "lyric_sei": ("lyric", "small fire, sei whispered / selective containment only"),
    "lyric_rin": ("lyric", "rin watched without correcting / that counted as mercy"),
    "lyric_eta_mu": ("lyric", "eta mu sol / intent becoming physical trace / measured without permission"),
    "lyric_fracture": ("lyric", "the fractures became beams / each misalignment a joint"),
}

STRUCTURES = [
    ["title","role","style","excluded",("Verse 1",3),("Chorus",2),("Verse 2",3),("Bridge",2),("Outro",2)],
    ["title","role","style","excluded",("Verse 1",3),("Verse 2",3),("Chorus",2),("Bridge",2),("Final Chorus",2),("Coda",1)],
]

ANCHORS = {
    "consent": ["consent", "boundary", "not yet", "no"],
    "distribution": ["distribution", "distributed", "single points fail", "rotation", "shared heat", "do not stand alone"],
    "drift": ["drift", "offset", "phase", "variance", "not lag"],
    "canon_chars": ["duct", "null", "patch", "sei", "rin"],
    "world": ["rail", "white page", "lattice", "truth resolves", "seoul", "moscow", "colorado", "shenzhen"],
    "scar": ["scar", "knee", "memory interrupts speed", "no erasure"],
}


def load_json(path, default):
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    return default


def save_json(path, data):
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


def decayed_weight(ts, now):
    age_days = (now - ts) / 86400.0
    return max(math.exp(-math.log(2) * age_days / HALF_LIFE_DAYS), MIN_DECAY_WEIGHT)


def ensure_memory():
    MEMORY_DIR.mkdir(parents=True, exist_ok=True)
    GENERATED_DIR.mkdir(parents=True, exist_ok=True)
    state = load_json(STATE_FILE, {
        "run_count": 0,
        "component_weights": {},
        "theme_weights": {"consent":1.0,"distribution":1.0,"drift":1.0,"scar":1.0,"world":1.0},
        "last_titles": [],
    })
    canon = load_json(CANON_FILE, {
        "entities_seen": {},
        "motifs_seen": {},
        "connections": [],
        "story_beats": [],
    })
    scores = load_json(SCORE_LOG, [])
    return state, canon, scores


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


def component_weight(component_id, state, scores, now, used_recently):
    base = state["component_weights"].get(component_id, DEFAULT_COMPONENT_WEIGHT)
    recent_penalty = REPETITION_PENALTY if component_id in used_recently else 0.0
    hist = [s for s in scores if component_id in s.get("component_scores", {})]
    hist_score = 0.0
    hist_weight = 0.0
    for s in hist:
        w = decayed_weight(s["timestamp"], now)
        hist_score += s["component_scores"][component_id] * w
        hist_weight += w
    learned = (hist_score / hist_weight) / 10.0 if hist_weight else base
    return max(0.08, base * 0.45 + learned * 0.45 + NOVELTY_BONUS - recent_penalty)


def choose_component(component_type, state, scores, now, used, used_recently):
    pool = [c for c in all_component_ids_by_type(component_type) if c not in used]
    if not pool:
        pool = all_component_ids_by_type(component_type)
    weights = [component_weight(c, state, scores, now, used_recently) for c in pool]
    return weighted_choice(pool, weights)


def choose_lyrics(n, state, scores, now, used, used_recently, theme_focus):
    pool = [c for c in all_component_ids_by_type("lyric") if c not in used]
    if len(pool) < n:
        pool = all_component_ids_by_type("lyric")
    selected = []
    for _ in range(n):
        candidates = [c for c in pool if c not in selected] or pool
        weights = []
        for c in candidates:
            w = component_weight(c, state, scores, now, used_recently)
            txt = COMPONENTS[c][1].lower()
            for theme, terms in ANCHORS.items():
                if theme in theme_focus and any(term in txt for term in terms):
                    w += 0.18 * theme_focus[theme]
            if any(name in txt for name in ["duct","null","patch","sei","rin"]):
                w += CANONICITY_BONUS
            weights.append(w)
        picked = weighted_choice(candidates, weights)
        selected.append(picked)
    return selected


def detect_themes(text):
    low = text.lower()
    found = {}
    for theme, terms in ANCHORS.items():
        found[theme] = sum(1 for t in terms if t in low)
    return found


def judge_song(markdown_text, song, canon, state):
    """Internal judge. No external API. Scores on five criteria."""
    low = markdown_text.lower()
    themes = detect_themes(markdown_text)
    used_titles = state.get("last_titles", [])
    title = song["title"]

    coherence = 4.0
    consistency = 4.0
    theme_build = 4.0
    connectivity = 4.0
    continuity = 4.0

    anchor_total = sum(themes.values())
    section_count = len(song["sections"])
    if anchor_total >= 8:
        coherence += 2.2
    elif anchor_total >= 5:
        coherence += 1.4
    coherence += min(1.6, section_count * 0.18)
    if "truth resolves" in low and ("scar" in low or "drift" in low or "distribution" in low):
        coherence += 1.2

    if any(x in low for x in ["white page","rail","lattice","seoul","moscow","colorado","shenzhen"]):
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
    if any(x in low for x in ["do not stand alone","shared heat","distribution persists"]):
        theme_build += 1.0

    motif_overlap = 0
    for motif in ["boundary","drift","scar","rotation","left","truth resolves","white page"]:
        if motif in low:
            motif_overlap += 1
    connectivity += min(3.0, motif_overlap * 0.42)
    if low.count("/ ") >= 8:
        connectivity += 0.7
    if themes["canon_chars"] >= 3:
        connectivity += 1.1

    canon_matches = 0
    for motif in canon.get("motifs_seen", {}).keys():
        if motif in low:
            canon_matches += 1
    continuity += min(2.4, canon_matches * 0.25)
    if title in used_titles:
        continuity -= 0.7
    if any(x in low for x in ["adjacent entities","truth resolves","single points fail","stand left"]):
        continuity += 1.6

    scores = {
        "coherence":    round(max(0, min(10, coherence)), 2),
        "consistency":  round(max(0, min(10, consistency)), 2),
        "theme":        round(max(0, min(10, theme_build)), 2),
        "connectivity": round(max(0, min(10, connectivity)), 2),
        "continuity":   round(max(0, min(10, continuity)), 2),
    }
    overall = round(sum(scores.values()) / len(scores), 2)

    reasoning = []
    if scores["theme"] >= 8:
        reasoning.append("Builds toward shared defense instead of isolated imagery.")
    if scores["continuity"] >= 8:
        reasoning.append("Connects strongly to existing canon motifs and recurring entities.")
    if scores["coherence"] < 7:
        reasoning.append("Needs a tighter emotional arc across sections.")
    if scores["consistency"] < 7:
        reasoning.append("Needs more explicit Gates-of-Truth world texture.")
    if not reasoning:
        reasoning.append("Balanced shard with solid continuity and usable motif density.")

    return overall, scores, " ".join(reasoning), themes


def update_canon(markdown_text, canon):
    low = markdown_text.lower()
    for entity in ["duct","null","patch","sei","rin","ritsu"]:
        if entity in low:
            canon["entities_seen"][entity] = canon["entities_seen"].get(entity, 0) + 1
    motifs = ["boundary","drift","scar","rotation","white page","truth resolves",
              "stand left","single points fail","distribution persists","adjacent entities"]
    for motif in motifs:
        if motif in low:
            canon["motifs_seen"][motif] = canon["motifs_seen"].get(motif, 0) + 1
    present = [e for e in ["duct","null","patch","sei","rin","ritsu"] if e in low]
    if len(present) >= 2:
        canon["connections"].append({"entities": present, "timestamp": time.time()})
    beat = None
    if "do not stand alone" in low:     beat = "collective-defense"
    elif "not yet" in low or "consent" in low: beat = "boundary-held"
    elif "scar" in low or "knee" in low:       beat = "scar-modeled"
    elif "truth resolves" in low:              beat = "resolution-carried-forward"
    if beat:
        canon["story_beats"].append({"beat": beat, "timestamp": time.time()})
    canon["connections"] = canon["connections"][-200:]
    canon["story_beats"] = canon["story_beats"][-200:]
    return canon


def adapt_weights(song, overall, scores, state):
    adj = (overall - 7.0) / 10.0
    for c in song["components_used"]:
        old = state["component_weights"].get(c, DEFAULT_COMPONENT_WEIGHT)
        bump = old + adj * 0.22
        txt = COMPONENTS[c][1].lower()
        if scores["theme"] >= 8 and any(k in txt for k in ["distribution","consent","scar","drift","truth resolves"]):
            bump += 0.03
        if scores["connectivity"] >= 8 and any(k in txt for k in ["duct","null","patch","sei","rin","adjacent"]):
            bump += 0.03
        state["component_weights"][c] = round(max(0.08, min(1.45, bump)), 4)
    return state


def score_components(song, overall):
    result = {}
    for sec in song["sections"]:
        sec_bonus = 0.25 if sec["name"] in ["Chorus","Final Chorus","Outro","Bridge"] else 0.0
        for c in sec["keys"]:
            result[c] = round(max(0.0, min(10.0, overall + sec_bonus)), 2)
    return result


def render_song(song):
    md = []
    md.append(f"# {song['title']}")
    md.append("")
    md.append("## Role")
    md.append(song["role"])
    md.append("")
    md.append("## Style Prompt")
    md.append(song["style"])
    md.append("")
    md.append("## Excluded Style")
    md.append(song["excluded"])
    md.append("")
    md.append("## Lyrics")
    md.append("")
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


def generate_song(state, canon, scores):
    now = time.time()
    used_recently = set(state.get("last_titles", []))
    used = set()

    title_id    = choose_component("title",    state, scores, now, used, used_recently); used.add(title_id)
    role_id     = choose_component("role",     state, scores, now, used, used_recently); used.add(role_id)
    style_id    = choose_component("style",    state, scores, now, used, used_recently); used.add(style_id)
    excluded_id = choose_component("excluded", state, scores, now, used, used_recently); used.add(excluded_id)

    theme_focus = dict(state.get("theme_weights", {}))
    for motif, count in canon.get("motifs_seen", {}).items():
        if motif in ["boundary"]:             theme_focus["consent"]      = theme_focus.get("consent", 1.0)      + min(0.35, count * 0.01)
        if motif in ["drift"]:                theme_focus["drift"]        = theme_focus.get("drift", 1.0)        + min(0.35, count * 0.01)
        if motif in ["scar"]:                 theme_focus["scar"]         = theme_focus.get("scar", 1.0)         + min(0.35, count * 0.01)
        if motif in ["distribution persists","stand left"]: theme_focus["distribution"] = theme_focus.get("distribution", 1.0) + min(0.35, count * 0.01)
        if motif in ["truth resolves"]:       theme_focus["world"]        = theme_focus.get("world", 1.0)        + min(0.25, count * 0.008)

    structure = random.choice(STRUCTURES)
    sections = []
    for item in structure:
        if isinstance(item, tuple):
            sec_name, n_lines = item
            lyr_ids = choose_lyrics(n_lines, state, scores, now, used, used_recently, theme_focus)
            for lid in lyr_ids:
                used.add(lid)
            sections.append({"name": sec_name, "keys": lyr_ids, "lines": [COMPONENTS[k][1] for k in lyr_ids]})

    title = COMPONENTS[title_id][1]
    song = {
        "title": title,
        "role":     COMPONENTS[role_id][1],
        "style":    COMPONENTS[style_id][1],
        "excluded": COMPONENTS[excluded_id][1],
        "sections": sections,
        "components_used": [title_id, role_id, style_id, excluded_id] + [k for sec in sections for k in sec["keys"]],
    }
    return song, render_song(song)


def run_batch(n=10, seed=None):
    if seed is not None:
        random.seed(seed)
    state, canon, scores = ensure_memory()
    generated = []

    for _ in range(n):
        song, markdown = generate_song(state, canon, scores)
        overall, dims, reasoning, themes = judge_song(markdown, song, canon, state)
        judged_md = append_judging(markdown, overall, dims, reasoning, themes)

        sig = hashlib.sha1(judged_md.encode()).hexdigest()[:6]
        ts  = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        out = GENERATED_DIR / f"{ts}_{slugify(song['title'])}_{sig}.md"
        out.write_text(judged_md, encoding="utf-8")

        comp_scores = score_components(song, overall)
        scores.append({
            "timestamp": time.time(),
            "title": song["title"],
            "overall": overall,
            "criteria": dims,
            "reasoning": reasoning,
            "theme_hits": themes,
            "component_scores": comp_scores,
            "file": out.name,
        })
        canon  = update_canon(judged_md, canon)
        state  = adapt_weights(song, overall, dims, state)
        state["run_count"] += 1
        state["last_titles"] = (state.get("last_titles", []) + [song["title"]])[-12:]
        for theme in list(state["theme_weights"].keys()):
            state["theme_weights"][theme] = round(max(0.55, state["theme_weights"][theme] * 0.985), 4)
        for theme, hit in themes.items():
            if theme in state["theme_weights"] and hit:
                state["theme_weights"][theme] = round(min(2.25, state["theme_weights"][theme] + hit * 0.015), 4)
        generated.append({"title": song["title"], "overall": overall, "file": out.name})

    save_json(SCORE_LOG, scores)
    save_json(STATE_FILE, state)
    save_json(CANON_FILE, canon)

    summary = ["# Run Summary", "",
               f"Generated: {len(generated)} songs",
               f"Total judged songs in memory: {len(scores)}",
               f"Run count: {state['run_count']}", "", "## This batch"]
    for g in generated:
        summary.append(f"- {g['title']} — {g['overall']}/10 — {g['file']}")
    summary += ["", "## Theme weights"]
    for k, v in state["theme_weights"].items():
        summary.append(f"- {k}: {v}")
    summary += ["", "## Strongest component weights"]
    for k, v in sorted(state["component_weights"].items(), key=lambda kv: kv[1], reverse=True)[:12]:
        summary.append(f"- {k}: {v}")
    (ROOT / "RUN_SUMMARY.md").write_text("\n".join(summary) + "\n", encoding="utf-8")
    return generated


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Fork Tales Lyrical Engine v3")
    parser.add_argument("--n",    type=int, default=10, help="Number of songs to generate")
    parser.add_argument("--seed", type=int, default=None, help="Random seed for reproducibility")
    args = parser.parse_args()
    results = run_batch(n=args.n, seed=args.seed)
    for r in results:
        print(f"{r['overall']:4.1f}  {r['title']}  →  {r['file']}")
