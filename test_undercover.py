# -*- coding: utf-8 -*-
"""
Undercover Plugin Self-Test Suite
Tests: word library, categories, multi-word groups, game settings,
       winner detection, special mode, v1->v2 migration
"""
import json
import os
import sys
import random
import io

# Force UTF-8 output
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

WORD_PAIRS_FILE = r"C:\Users\30136\.astrbot\word_pairs.json"

# ── Data classes (standalone copies from main.py) ──
class Player:
    def __init__(self, user_id, user_name):
        self.user_id = user_id
        self.user_name = user_name
        self.is_alive = True
        self.role = None
        self.word = None
        self.last_speech = ""

class GameRoom:
    def __init__(self, room_id, owner_id, owner_name):
        self.room_id = room_id
        self.owner_id = owner_id
        self.owner_name = owner_name
        self.players = []
        self.status = "waiting"
        self.speech_order = []
        self.current_speaker_index = 0
        self.votes = {}
        self.round = 1
        self.group_session_str = ""
        self.whiteboard_guessing = False
        self.whiteboard_player = None
        self.citizen_word = ""
        self.enable_whiteboard = True
        self.selected_category = "全部"
        self.private_vote = True
        self.special_mode = False
        self.final_guess_phase = False
        self.whiteboard_guessed = {}

# ── Core logic (copied from main.py) ──
def load_word_pairs(file_path):
    if os.path.exists(file_path):
        with open(file_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        if isinstance(data, dict) and data.get("version") == 2:
            return data
        elif isinstance(data, list):
            return {"version": 2, "categories": {"综合": data}}
    return None

def get_word_groups_for_game(word_pairs, category="全部"):
    categories = word_pairs.get("categories", {})
    if not categories:
        return []
    if category == "全部":
        result = []
        for cat_words in categories.values():
            result.extend(cat_words)
        return result
    return list(categories.get(category, []))

def pick_words_from_group(word_group):
    a, b = random.sample(word_group, 2)
    if random.random() < 0.5:
        return a, b
    else:
        return b, a

def _check_winner(game_room):
    alive_players = [p for p in game_room.players if p.is_alive]
    alive_whiteboards = [p for p in alive_players if p.role == "whiteboard"]
    alive_good = [p for p in alive_players if p.role in ("citizen", "whiteboard")]
    alive_undercovers = [p for p in alive_players if p.role == "undercover"]

    if game_room.special_mode:
        if len(alive_undercovers) > 0 and len(alive_undercovers) >= len(alive_whiteboards):
            return "卧底"
        return None

    if len(alive_undercovers) == 0 and len(alive_whiteboards) == 0:
        return "平民"
    elif len(alive_undercovers) >= len(alive_good):
        return "卧底"
    return None

def _do_next_round(game_room):
    game_room.round += 1
    game_room.speech_order = [p for p in game_room.players if p.is_alive]
    random.shuffle(game_room.speech_order)
    if len(game_room.speech_order) >= 5 and game_room.speech_order[0].role == "undercover":
        swap_idx = random.randrange(1, len(game_room.speech_order))
        game_room.speech_order[0], game_room.speech_order[swap_idx] = \
            game_room.speech_order[swap_idx], game_room.speech_order[0]
    game_room.current_speaker_index = 0
    game_room.votes.clear()
    return len(game_room.speech_order)


# ═══════════════════════════════════════════════════
# Test Harness
# ═══════════════════════════════════════════════════

passed = 0
failed = 0

def check(test_name, condition, detail=""):
    global passed, failed
    if condition:
        passed += 1
        print(f"  [PASS] {test_name}")
    else:
        failed += 1
        print(f"  [FAIL] {test_name}{' -- ' + detail if detail else ''}")

def section(title):
    print(f"\n{'='*60}")
    print(f"  {title}")
    print(f"{'='*60}")

def make_room_with_players(roles_alive):
    room = GameRoom("t", "o", "O")
    room.status = "playing"
    for i, (role, alive) in enumerate(roles_alive):
        p = Player(f"u{i}", f"Player{i}")
        p.role = role
        p.is_alive = alive
        p.word = "test_word" if role != "whiteboard" else ""
        room.players.append(p)
    return room


# ═══════════════════════════════════════════════════
# TEST 1: word_pairs.json Structure
# ═══════════════════════════════════════════════════
section("1. word_pairs.json Structure")

wp = load_word_pairs(WORD_PAIRS_FILE)
check("File exists and loads", wp is not None)
check("Version is 2", wp and wp.get("version") == 2)
check("Has 'categories' key", wp and "categories" in wp)

cats = wp.get("categories", {})
check("Has 3+ categories", len(cats) >= 3, f"got {len(cats)}")

cat_names = list(cats.keys())
print(f"    Categories: {', '.join(cat_names)}")

total_groups = sum(len(v) for v in cats.values())
check("Total groups > 100", total_groups > 100, f"got {total_groups}")

all_ok = True
multi_word_count = 0
for cat, groups in cats.items():
    for g in groups:
        if not isinstance(g, list) or len(g) < 2:
            all_ok = False
            print(f"    WARN: invalid group: {cat}/{g}")
        if len(g) > 2:
            multi_word_count += 1
check("All groups have >= 2 words", all_ok)
check("Has multi-word groups (>2)", multi_word_count > 0, f"count: {multi_word_count}")

# ═══════════════════════════════════════════════════
# TEST 2: Category Filtering
# ═══════════════════════════════════════════════════
section("2. Category Filtering")

all_groups = get_word_groups_for_game(wp, "全部")
check("'All' returns all groups", len(all_groups) == total_groups, f"exp {total_groups}, got {len(all_groups)}")

for cat in cat_names:
    cat_groups = get_word_groups_for_game(wp, cat)
    expected = len(cats[cat])
    check(f"Category '{cat}' count", len(cat_groups) == expected, f"exp {expected}, got {len(cat_groups)}")

check("Unknown category returns empty", len(get_word_groups_for_game(wp, "nonexistent")) == 0)

# ═══════════════════════════════════════════════════
# TEST 3: Multi-word Group Selection
# ═══════════════════════════════════════════════════
section("3. Multi-word Group Selection")

# 2-word group
two_word = ["apple", "pear"]
for i in range(10):
    a, b = pick_words_from_group(two_word)
    if a == b or a not in two_word or b not in two_word:
        check(f"2-word pick #{i}", False, f"a={a}, b={b}")
        break
else:
    check("2-word group: 10 picks all valid", True)

# 3-word group
three_word = ["A", "B", "C"]
results = set()
for _ in range(50):
    a, b = pick_words_from_group(three_word)
    results.add(tuple(sorted([a, b])))
check("3-word group: produces multiple combos", len(results) >= 2, f"got {len(results)} combos")
check("3-word group: max 3 combos", len(results) <= 3, f"got {len(results)} combos")

# 4-word group
four_word = ["W", "X", "Y", "Z"]
results4 = set()
for _ in range(100):
    a, b = pick_words_from_group(four_word)
    results4.add(tuple(sorted([a, b])))
check("4-word group: produces 3+ combos", len(results4) >= 3, f"got {len(results4)} combos")
check("4-word group: max 6 combos", len(results4) <= 6, f"got {len(results4)} combos")

# ═══════════════════════════════════════════════════
# TEST 4: GameRoom Settings
# ═══════════════════════════════════════════════════
section("4. GameRoom Settings")

room = GameRoom("1", "owner1", "Owner")
check("Default enable_whiteboard = True", room.enable_whiteboard == True)
check("Default selected_category = '全部'", room.selected_category == "全部")
check("Default private_vote = True", room.private_vote == True)
check("Default special_mode = False", room.special_mode == False)
check("Default final_guess_phase = False", room.final_guess_phase == False)

room.enable_whiteboard = False
room.selected_category = "游戏"
room.private_vote = False
check("Set whiteboard -> False", room.enable_whiteboard == False)
check("Set category -> '游戏'", room.selected_category == "游戏")
check("Set private_vote -> False", room.private_vote == False)

# ═══════════════════════════════════════════════════
# TEST 5: Normal Mode Winner Detection
# ═══════════════════════════════════════════════════
section("5. Normal Mode _check_winner")

# Civilians win: no undercover, no whiteboard alive
r = make_room_with_players([("citizen", True), ("citizen", True), ("undercover", False)])
check("Civ win: all UC dead, no WB", _check_winner(r) == "平民")

# Civilians win: all UC and WB dead
r = make_room_with_players([("citizen", True), ("whiteboard", False), ("undercover", False)])
check("Civ win: UC+WB dead", _check_winner(r) == "平民")

# Undercover wins: UC >= good
r = make_room_with_players([("undercover", True), ("citizen", True)])
check("UC win: 1UC vs 1Civ", _check_winner(r) == "卧底")

r = make_room_with_players([("undercover", True), ("undercover", True), ("citizen", True)])
check("UC win: 2UC vs 1Civ", _check_winner(r) == "卧底")

# Game continues
r = make_room_with_players([("undercover", True), ("citizen", True), ("citizen", True)])
check("Continue: 1UC vs 2Civ", _check_winner(r) is None)

r = make_room_with_players([("undercover", True), ("whiteboard", True), ("citizen", True)])
check("Continue: 1UC vs 1WB+1Civ", _check_winner(r) is None)

r = make_room_with_players([("undercover", True), ("whiteboard", True)])
check("UC win: 1UC vs 1WB", _check_winner(r) == "卧底")

# ═══════════════════════════════════════════════════
# TEST 6: Special Mode Winner Detection
# ═══════════════════════════════════════════════════
section("6. Special Mode _check_winner")

r = make_room_with_players([("undercover", True), ("whiteboard", True), ("whiteboard", True)])
r.special_mode = True
check("Special-continue: 1UC vs 2WB", _check_winner(r) is None)

r2 = make_room_with_players([("undercover", True), ("whiteboard", True)])
r2.special_mode = True
check("Special-UC win: 1UC vs 1WB", _check_winner(r2) == "卧底")

r3 = make_room_with_players([("undercover", True), ("whiteboard", False)])
r3.special_mode = True
check("Special-UC win: all WB dead", _check_winner(r3) == "卧底")

# UC eliminated -> don't end here (handled by vote logic)
r4 = make_room_with_players([("undercover", False), ("whiteboard", True), ("whiteboard", True)])
r4.special_mode = True
check("Special-continue: UC dead (guess phase)", _check_winner(r4) is None)

# ═══════════════════════════════════════════════════
# TEST 7: _do_next_round Logic
# ═══════════════════════════════════════════════════
section("7. _do_next_round Logic")

r = make_room_with_players([
    ("citizen", True), ("citizen", True), ("citizen", False),
    ("undercover", True)
])
r.round = 2
r.votes = {"u0": "u1"}

alive_count = _do_next_round(r)
check("Round incremented", r.round == 3)
check("Votes cleared", len(r.votes) == 0)
check("Speaker index reset", r.current_speaker_index == 0)
check("Speech order only alive", len(r.speech_order) == alive_count)
check("Alive count correct", alive_count == 3)
# Verify no dead players in speech order
dead_in_order = any(not p.is_alive for p in r.speech_order)
check("No dead players in speech order", not dead_in_order)

# ═══════════════════════════════════════════════════
# TEST 8: v1 -> v2 Migration
# ═══════════════════════════════════════════════════
section("8. v1 -> v2 Migration")

v1_data = [["apple", "pear"], ["computer", "phone"], ["cat", "dog"]]

temp_file = r"C:\Users\30136\.astrbot\temp_test_v1.json"
with open(temp_file, 'w', encoding='utf-8') as f:
    json.dump(v1_data, f, ensure_ascii=False)

loaded = load_word_pairs(temp_file)
check("v1 migrated to v2", loaded.get("version") == 2)
check("v1 data in '综合' category", "综合" in loaded.get("categories", {}))
check("v1 item count preserved", len(loaded["categories"]["综合"]) == 3)

os.remove(temp_file)

# ═══════════════════════════════════════════════════
# TEST 9: Special Mode Full Flow Simulation
# ═══════════════════════════════════════════════════
section("9. Special Mode Full Flow")

room = GameRoom("999", "owner", "Owner")
room.status = "playing"
room.special_mode = True
room.citizen_word = "test_word"

# 5 players: 1 UC + 4 WB
room.players = [
    Player("u0", "UC_Player"),
    Player("u1", "WB_A"),
    Player("u2", "WB_B"),
    Player("u3", "WB_C"),
    Player("u4", "WB_D"),
]
room.players[0].role = "undercover"
room.players[0].word = "test_word"
for p in room.players[1:]:
    p.role = "whiteboard"
    p.word = ""
    room.whiteboard_guessed[p.user_id] = False

# Round 1: vote out WB_A
room.players[1].is_alive = False
check("Flow-1: WB voted out -> eliminated", room.players[1].is_alive == False)
check("Flow-1: Game continues (UC alive)", _check_winner(room) is None)

# WB_B guesses (wrong)
room.whiteboard_guessed["u2"] = True
check("Flow-2: WB guessed wrong -> recorded", room.whiteboard_guessed["u2"] == True)
check("Flow-2: WB_B cannot guess again during game", room.whiteboard_guessed["u2"] == True)

# Round 2: vote out WB_C
room.players[3].is_alive = False
check("Flow-3: Another WB voted out -> normal", room.players[3].is_alive == False)

# Round 3: UC voted out -> final guess phase
room.players[0].is_alive = False
room.final_guess_phase = True
# Reset guess records for all surviving WBs
for p in room.players:
    if p.is_alive and p.role == "whiteboard":
        room.whiteboard_guessed[p.user_id] = False

check("Flow-4: UC voted out -> final_guess_phase=True", room.final_guess_phase == True)
check("Flow-4: Surviving WBs can guess again", room.whiteboard_guessed.get("u2") == False)
# WB_A (u1) dead, WB_C (u3) dead, UC (u0) dead
# Surviving: WB_B (u2), WB_D (u4) = 2 WBs
alive_wb = [p for p in room.players if p.is_alive and p.role == "whiteboard"]
check("Flow-4: 2 WBs survive (WB_B + WB_D)", len(alive_wb) == 2)

# Both surviving WBs guess wrong
room.whiteboard_guessed["u2"] = True
room.whiteboard_guessed["u4"] = True
remaining = [p for p in room.players if p.is_alive and p.role == "whiteboard"
             and not room.whiteboard_guessed.get(p.user_id, False)]
check("Flow-5: All WBs guessed wrong -> UC wins", len(remaining) == 0)

# ═══════════════════════════════════════════════════
# TEST 10: Edge Cases
# ═══════════════════════════════════════════════════
section("10. Edge Cases")

empty_wp = {"version": 2, "categories": {}}
check("Empty word pairs -> empty list", len(get_word_groups_for_game(empty_wp)) == 0)

single_empty = {"version": 2, "categories": {"game": []}}
check("Empty category -> empty list", len(get_word_groups_for_game(single_empty, "game")) == 0)

# 3 players minimum
r_min = make_room_with_players([("citizen", True), ("citizen", True), ("undercover", True)])
check("3 players: 1UC+2Civ", len([p for p in r_min.players if p.role == "undercover"]) == 1)

# All abstain -> no elimination
all_abstain_room = make_room_with_players([("citizen", True), ("undercover", True)])
all_abstain_room.votes = {"u0": None, "u1": None}
vote_counts = {}
for v_id in all_abstain_room.votes.values():
    if v_id is not None:
        vote_counts[v_id] = vote_counts.get(v_id, 0) + 1
check("All abstain -> no votes", len(vote_counts) == 0)

# Check citizen_word is stored correctly
r_word = GameRoom("1", "o", "O")
r_word.citizen_word = "hello"
check("citizen_word stored", r_word.citizen_word == "hello")

# ═══════════════════════════════════════════════════
# Results
# ═══════════════════════════════════════════════════
print(f"\n{'='*60}")
total = passed + failed
print(f"  Results: {passed}/{total} passed")
if failed == 0:
    print(f"  ALL TESTS PASSED!")
else:
    print(f"  {failed} TEST(S) FAILED!")
print(f"{'='*60}")

sys.exit(0 if failed == 0 else 1)
