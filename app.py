#!/usr/bin/env python3
import json
import os
import sys
import re

# Terminal color constants for cross-platform compatibility
RESET = "\033[0m"
RED = "\033[91m"
GREEN = "\033[92m"
YELLOW = "\033[93m"
BLUE = "\033[94m"
CYAN = "\033[96m"

# State persistence path
STATE_FILE = "state.json"


class ChessOrganizer:
    """
    Command-line tournament organizer for round-robin chess events.
    Manages player rosters, dynamic pairings, result tracking, and
    tiebreak calculations with persistent JSON state.
    """

    def __init__(self):
        self.state = self._load_state()
        print("Welcome to Chess Tournament Organizer!")
        self._print_status()
        self._cli_loop()

    # --- Utility Helpers ---
    @staticmethod
    def _visible_len(text):
        """Calculates visible character count, ignoring ANSI escape sequences."""
        return len(re.sub(r'\x1b\[[0-9;]*m', '', str(text)))

    @staticmethod
    def _pad_text(text, width, alignment='left'):
        """Pads text to target visible width, safely ignoring ANSI codes."""
        visible = len(re.sub(r'\x1b\[[0-9;]*m', '', str(text)))
        pad = max(0, width - visible)
        if alignment == 'right':
            return ' ' * pad + str(text)
        elif alignment == 'center':
            left = pad // 2
            return ' ' * left + str(text) + ' ' * (pad - left)
        return str(text) + ' ' * pad

    def _ask_confirm(self, msg):
        """Prompts user for confirmation. Returns True only on 'y'."""
        resp = input(f"\n{YELLOW}{msg} (y/n): {RESET}").strip().lower()
        return resp == "y"

    @staticmethod
    def _render_table(headers, rows, alignments=None, col_pad=2):
        """Dynamically scales and prints a terminal-safe table with ANSI support."""
        if not headers: return
        n_cols = len(headers)
        if alignments is None:
            alignments = ['left'] * n_cols

        # Calculate max visible width per column
        col_widths = []
        for i in range(n_cols):
            w = ChessOrganizer._visible_len(str(headers[i]))
            for r in rows:
                if i < len(r):
                    w = max(w, ChessOrganizer._visible_len(str(r[i])))
            col_widths.append(w)

        # Row formatter
        def _fmt_row(vals):
            parts = []
            for i in range(n_cols):
                val = str(vals[i]) if i < len(vals) else ""
                target_w = col_widths[i] + col_pad
                parts.append(ChessOrganizer._pad_text(val, target_w, alignments[i]))
            return " | ".join(parts)

        # Separator matches exact printed width
        sep_len = sum(col_widths) + (col_pad * n_cols) + (3 * (n_cols - 1))
        print(_fmt_row(headers))
        print("-" * sep_len)
        for r in rows:
            print(_fmt_row(r))

    # --- State Management ---
    def _load_state(self):
        """Loads tournament data from disk or initializes a fresh state."""
        if os.path.exists(STATE_FILE):
            with open(STATE_FILE, 'r') as f:
                return json.load(f)
        return {"active_tournament": None, "tournaments": {}}

    def _save_state(self):
        """Atomically writes the current state dictionary to disk."""
        with open(STATE_FILE, 'w') as f:
            json.dump(self.state, f, indent=2)

    def _get_active(self):
        """Returns the name of the currently active tournament, or None."""
        name = self.state.get("active_tournament")
        if name and name in self.state["tournaments"]:
            return name
        self.state["active_tournament"] = None
        return None

    def _print_status(self):
        """Displays the current tournament context in the prompt header."""
        active = self.state.get("active_tournament")
        display = active if active else "NO TOURNAMENT"
        print(f"\n{CYAN}[{display}]{RESET} Ready. Type {CYAN}'help'{RESET} for commands. All changes save instantly.")

    # --- Scoring & Tiebreak Calculations ---
    def _calc_points_sb(self, tournament):
        """
        Dynamically calculates match points and Sonneborn-Berger (SB) scores.
        SB values shift live as tournament results change.
        """
        players = list(tournament["players"].keys())
        pts = {p: 0.0 for p in players if p != "0"}
        sb = {p: 0.0 for p in pts}

        for r in tournament["rounds"]:
            for g in r["games"]:
                if g["result"]:
                    w, b = g["white"], g["black"]
                    if g["result"] == "d":
                        if w in pts: pts[w] += 0.5
                        if b in pts: pts[b] += 0.5
                    else:
                        winner = w if g["result"] == "w" else b
                        if winner in pts:
                            pts[winner] += 1.0

        for r in tournament["rounds"]:
            for g in r["games"]:
                if g["result"] and g["white"] != "0" and g["black"] != "0":
                    w, b = g["white"], g["black"]
                    if g["result"] == "d":
                        if w in pts: sb[w] += 0.5 * pts.get(b, 0.0)
                        if b in pts: sb[b] += 0.5 * pts.get(w, 0.0)
                    else:
                        winner = w if g["result"] == "w" else b
                        loser = b if winner == w else w
                        if winner in pts and loser in pts:
                            sb[winner] += pts[loser]
        return pts, sb

    # --- Pairing Generation ---
    def _generate_rounds(self, mode):
        """
        Appends Round Robin or Double Round Robin schedules to the active tournament.
        Automatically assigns BYE results (1 point) when player count is odd.
        """
        active = self._get_active()
        if not active:
            print(f"{RED}No tournament active. Use 'tournaments' to create/load first.{RESET}")
            return

        t = self.state["tournaments"][active]
        players = sorted([p for p in t["players"].keys() if p != "0"], key=lambda x: int(x))
        if len(players) < 2:
            print(f"{RED}Minimum 2 players required to generate rounds.{RESET}")
            return

        ids = players[:]
        if len(ids) % 2 == 1:
            ids.append("0")  # Append BYE placeholder
        n = len(ids)
        generated = []
        fixed = ids[0]
        rotating = ids[1:]

        # Standard Circle Method pairing algorithm
        for _ in range(n - 1):
            round_pairings = []
            current = [fixed] + rotating
            for i in range(n // 2):
                round_pairings.append((current[i], current[n - 1 - i]))
            generated.append(round_pairings)
            rotating.insert(0, rotating.pop())

        if mode == "drr":
            for i in range(len(generated)):
                generated.append([(b, w) for w, b in generated[i]])

        # Append to tournament state without overwriting existing data
        start_r = len(t["rounds"]) + 1
        for i, round_pairings in enumerate(generated):
            r_data = {"round_num": start_r + i, "games": []}
            for j, (w, b) in enumerate(round_pairings):
                res = "b" if w == "0" else ("w" if b == "0" else None)
                r_data["games"].append({
                    "game_num": j + 1,
                    "white": w,
                    "black": b,
                    "result": res
                })
            t["rounds"].append(r_data)

        self._save_state()
        print(
            f"{GREEN}Generated {len(generated)} rounds ({start_r}-{start_r + len(generated) - 1}). Auto-saved.{RESET}")

    # --- Command Handlers ---
    def _cmd_tournaments(self, args):
        """Manages tournament creation, switching, listing, and deletion."""
        if not args:
            t_dict = self.state["tournaments"]
            if not t_dict:
                print(f"{YELLOW}No tournaments found.{RESET}")
                return
            self._render_table(
                ["TOURNAMENT NAME", "ROUNDS"],
                [(f"{GREEN}{k}{RESET}", v.get("rounds", []).__len__()) for k, v in t_dict.items()],
                alignments=["left", "right"]
            )
            return

        if len(args) == 1:
            name = args[0]
            if name in self.state["tournaments"]:
                self.state["active_tournament"] = name
                self._save_state()
                print(f"{GREEN}Loaded tournament '{name}'.{RESET}")
            else:
                self.state["tournaments"][name] = {
                    "players": {"0": {"name": "BYE"}},
                    "next_player_id": 1,
                    "rounds": []
                }
                self.state["active_tournament"] = name
                self._save_state()
                print(f"{GREEN}Created & loaded tournament '{name}'.{RESET}")
        elif len(args) == 2 and args[1].lower() == "del":
            name = args[0]
            if name not in self.state["tournaments"]:
                print(f"{RED}Tournament '{name}' not found.{RESET}")
                return
            if self._ask_confirm(f"Delete tournament '{name}'? All data will be lost."):
                del self.state["tournaments"][name]
                if self.state.get("active_tournament") == name:
                    self.state["active_tournament"] = None
                self._save_state()
                print(f"{GREEN}Tournament '{name}' deleted.{RESET}")
            else:
                print("Cancelled.")
        else:
            print(f"{RED}Usage: tournaments  |  tournaments <name>  |  tournaments <name> del{RESET}")

    def _cmd_add(self, name_raw):
        """Registers a new player with an auto-incremented numeric ID."""
        active = self._get_active()
        if not active:
            print(f"{RED}No tournament active.{RESET}")
            return
        if not name_raw:
            print(f"{RED}Usage: add <player_name>{RESET}")
            return
        t = self.state["tournaments"][active]
        pid = str(t["next_player_id"])
        t["players"][pid] = {"name": name_raw}
        t["next_player_id"] += 1
        self._save_state()
        print(f"{GREEN}Added '{name_raw}' as ID {pid}.{RESET}")

    def _cmd_rounds(self, args):
        """Displays round status, manages pairings, and handles generation/results."""
        active = self._get_active()
        if not active:
            print(f"{RED}No tournament active.{RESET}")
            return

        t = self.state["tournaments"][active]

        if not args:
            self._render_table(
                ["ROUND", "GAMES", "STATUS"],
                [(r["round_num"], len(r["games"]),
                  "Complete" if all(g["result"] for g in r["games"]) else
                  ("In Progress" if any(g["result"] for g in r["games"]) else "Pending"))
                 for r in t["rounds"]],
                alignments=["right", "right", "left"]
            )
            return

        if args[0].lower() == "clear":
            if self._ask_confirm("Wipe ALL rounds & results?"):
                t["rounds"] = []
                self._save_state()
                print(f"{GREEN}All rounds cleared.{RESET}")
            return

        if len(args) >= 2 and args[0].lower() == "gen":
            mode = args[1].lower()
            if mode not in ("rr", "drr"):
                print(f"{RED}Invalid type. Use 'rr' or 'drr'.{RESET}")
                return
            self._generate_rounds(mode)
            return

        try:
            r_num = int(args[0])
        except ValueError:
            print(
                f"{RED}Invalid argument. Use: rounds / rounds <num> / rounds gen <type> / rounds <r> clear / ...{RESET}")
            return

        if r_num < 1 or r_num > len(t["rounds"]):
            print(f"{RED}Invalid round. Tournament has {len(t['rounds'])} rounds.{RESET}")
            return

        r = t["rounds"][r_num - 1]

        # Add custom game
        if len(args) == 4 and args[3].lower() == "add":
            w_raw, b_raw = args[1], args[2]
            w_id = "0" if w_raw.lower() == "bye" else w_raw
            b_id = "0" if b_raw.lower() == "bye" else b_raw

            if w_id not in t["players"] or b_id not in t["players"]:
                print(f"{RED}Invalid player ID(s). Ensure they exist.{RESET}")
                return
            if w_id == b_id:
                print(f"{RED}Player cannot play themselves.{RESET}")
                return

            paired_ids = {g["white"] for g in r["games"]} | {g["black"] for g in r["games"]}
            if w_id != "0" and w_id in paired_ids:
                print(f"{RED}Player {w_id} is already paired in Round {r_num}.{RESET}")
                return
            if b_id != "0" and b_id in paired_ids:
                print(f"{RED}Player {b_id} is already paired in Round {r_num}.{RESET}")
                return

            bye_count = sum(1 for g in r["games"] if g["white"] == "0" or g["black"] == "0")
            if (w_id == "0" or b_id == "0") and bye_count >= 1:
                if not self._ask_confirm(f"Multiple BYEs detected in Round {r_num}. Proceed?"):
                    return

            new_game = {"game_num": len(r["games"]) + 1, "white": w_id, "black": b_id, "result": None}
            if w_id == "0" and b_id != "0":
                new_game["result"] = "b"
            elif b_id == "0" and w_id != "0":
                new_game["result"] = "w"

            r["games"].append(new_game)
            self._save_state()
            print(
                f"{GREEN}Added Game {new_game['game_num']} (ID {w_id} vs {b_id}) to Round {r_num}. Auto-saved.{RESET}")
            return

        # Switch board positions
        if len(args) == 4 and args[3].lower() == "switch":
            try:
                g_a, g_b = int(args[1]), int(args[2])
            except ValueError:
                print(f"{RED}Game numbers must be integers.{RESET}")
                return
            idx_a = next((i for i, g in enumerate(r["games"]) if g["game_num"] == g_a), None)
            idx_b = next((i for i, g in enumerate(r["games"]) if g["game_num"] == g_b), None)
            if idx_a is None or idx_b is None:
                print(f"{RED}Game {g_a} or {g_b} not found in Round {r_num}.{RESET}")
                return
            r["games"][idx_a], r["games"][idx_b] = r["games"][idx_b], r["games"][idx_a]
            r["games"][idx_a]["game_num"] = g_a
            r["games"][idx_b]["game_num"] = g_b
            self._save_state()
            print(f"{GREEN}Swapped board positions for Game {g_a} and {g_b} in Round {r_num}.{RESET}")
            return

        # Delete specific game
        if len(args) == 3 and args[2].lower() == "del":
            try:
                g_num = int(args[1])
            except ValueError:
                print(f"{RED}Game number must be an integer.{RESET}")
                return
            idx = next((i for i, g in enumerate(r["games"]) if g["game_num"] == g_num), None)
            if idx is None:
                print(f"{RED}Game {g_num} not found in Round {r_num}.{RESET}")
                return
            if r["games"][idx]["result"] and not self._ask_confirm(
                    f"Game {g_num} has a recorded result. Delete anyway?"):
                return
            r["games"].pop(idx)
            for i, g in enumerate(r["games"]):
                g["game_num"] = i + 1
            self._save_state()
            print(f"{GREEN}Deleted Game {g_num} from Round {r_num}. Games auto-renumbered.{RESET}")
            return

        # Record result
        if len(args) == 4 and args[2].lower() == "res":
            outcome = args[3].lower()
            if outcome not in ("w", "d", "b"):
                print(f"{RED}Outcome must be 'w', 'b', or 'd'.{RESET}")
                return
            try:
                g_num = int(args[1])
            except ValueError:
                print(f"{RED}Game number must be an integer.{RESET}")
                return
            if g_num < 1 or g_num > len(r["games"]):
                print(f"{RED}Invalid game in Round {r_num}.{RESET}")
                return

            game = r["games"][g_num - 1]
            if game["result"] and not self._ask_confirm(
                    f"Round {r_num} Game {g_num} already recorded ('{game['result']}'). Overwrite?"):
                return

            game["result"] = outcome
            self._save_state()
            print(f"{GREEN}Round {r_num} Game {g_num} set to '{outcome}'. Auto-saved.{RESET}")
            return

        # Default: Show round pairings & unmatched
        if len(args) == 1:
            pair_rows = []
            paired_ids = set()
            for g in r["games"]:
                w_name = t["players"].get(g["white"], {}).get("name", "?")
                b_name = t["players"].get(g["black"], {}).get("name", "?")
                w_disp = f"{w_name} ({g['white']})" if g["white"] != "0" else "BYE (0)"
                b_disp = f"{b_name} ({g['black']})" if g["black"] != "0" else "BYE (0)"
                res = g["result"] if g["result"] else "--"
                pair_rows.append([g["game_num"], w_disp, b_disp, res])
                paired_ids.add(g["white"])
                paired_ids.add(g["black"])

            print(f"\n{CYAN}=== ROUND {r_num} PAIRINGS ==={RESET}")
            self._render_table(["GAME", "WHITE (ID)", "BLACK (ID)", "RESULT"], pair_rows,
                               ["right", "left", "left", "left"])

            unmatched = [(pid, t["players"][pid]["name"]) for pid in t["players"] if
                         pid != "0" and pid not in paired_ids]
            unmatched.sort(key=lambda x: int(x[0]))

            if unmatched:
                print(f"\n{CYAN}--- UNMATCHED PLAYERS ---{RESET}")
                self._render_table(["ID", "NAME"], unmatched, ["right", "left"])
            else:
                print(f"\n{GREEN}All active players are paired.{RESET}")
            return

        print(f"{RED}Invalid arguments for rounds command.{RESET}")

    def _cmd_info(self, args):
        """Displays standings or individual player match history."""
        active = self._get_active()
        if not active:
            print(f"{RED}No tournament active.{RESET}")
            return
        t = self.state["tournaments"][active]
        pts, sb = self._calc_points_sb(t)

        if not args:
            players = [(pid, t["players"][pid]["name"], pts.get(pid, 0), sb.get(pid, 0))
                       for pid in t["players"] if pid != "0"]
            players.sort(key=lambda x: (-x[2], -x[3], int(x[0])))
            print(f"\n{CYAN}=== LIVE STANDINGS ==={RESET}")
            self._render_table(["ID", "NAME", "PTS", "SB"], players, ["right", "left", "right", "right"])
        else:
            pid = args[0]
            if pid == "0" or pid not in t["players"]:
                print(f"{RED}Player ID '{pid}' not found.{RESET}")
                return

            name = t["players"][pid]["name"]
            p_total = pts.get(pid, 0)
            s_total = sb.get(pid, 0)
            print(f"\n{CYAN}Player: {name} (ID: {pid}) | Total: {p_total:.1f} | SB: {s_total:.2f}{RESET}")

            history = []
            for r in t["rounds"]:
                for g in r["games"]:
                    if g["white"] == pid or g["black"] == pid:
                        opp = g["black"] if g["white"] == pid else g["white"]
                        color = "W" if g["white"] == pid else "B"
                        opp_name = t["players"].get(opp, {}).get("name", "?")
                        res = g["result"] if g["result"] else "--"
                        sb_gain = 0.0
                        if g["result"] and opp != "0":
                            opp_pts = pts.get(opp, 0)
                            if g["result"] == "d":
                                sb_gain = 0.5 * opp_pts
                            elif (g["white"] == pid and g["result"] == "w") or (
                                    g["black"] == pid and g["result"] == "b"):
                                sb_gain = opp_pts
                        history.append(
                            [r["round_num"], g["game_num"], f"{opp_name} ({opp})", color, res, f"{sb_gain:.2f}"])

            print(f"{'-' * 70}")
            self._render_table(["ROUND", "GAME", "OPPONENT (ID)", "COLOR", "RES", "SB+"], history,
                               ["right", "right", "left", "center", "left", "right"])

    def _show_help(self):
        """Renders the command manual using the dynamic table formatter."""
        entries = [
            ("tournaments", "", "List all tournaments & round counts"),
            ("", "[name]", "Create new or load existing tournament"),
            ("", "[name] del", "Delete tournament & associated data"),
            ("add", "<player_name>", "Register a player (auto-assigned numeric ID)"),
            ("rounds", "", "Show round overview & completion status"),
            ("", "gen [rr|drr]", "Generate and append round-robin schedule"),
            ("", "<number>", "Show detailed pairings & unmatched players"),
            ("", "<r> <w_id> <b_id> add", "Add custom game to specific round"),
            ("", "<r> <g_a> <g_b> switch", "Swap board positions of two games"),
            ("", "<r> <game> del", "Remove specific game (auto-renumbers)"),
            ("", "clear", "Wipe all rounds & results"),
            ("", "<r> <game> res [w|d|b]", "Record game outcome for round/game"),
            ("info", "", "Display live standings table"),
            ("", "<player_id>", "Show match history & SB contribution"),
            ("help", "", "Display this command manual"),
            ("exit", "", "Save tournament state & close application"),
        ]
        rows = [(f"{GREEN}{cmd}{RESET}", usage, desc) for cmd, usage, desc in entries]
        print()
        self._render_table(["COMMAND", "USAGE", "DESCRIPTION"], rows, alignments=["left", "left", "left"])

    # --- Interactive Command Loop ---
    def _cli_loop(self):
        """Continuous REPL loop with safe signal handling and auto-save."""
        while True:
            try:
                raw = input(f"\n{BLUE}[{self.state.get('active_tournament', 'GLOBAL')}]{RESET} > ").strip()
                if not raw: continue
                parts = raw.split(maxsplit=1)
                cmd = parts[0].lower()
                arg = parts[1] if len(parts) > 1 else ""

                if cmd == "help":
                    self._show_help()
                elif cmd == "tournaments":
                    self._cmd_tournaments(arg.split() if arg else [])
                elif cmd == "add":
                    self._cmd_add(arg.strip())
                elif cmd == "rounds":
                    self._cmd_rounds(arg.split() if arg else [])
                elif cmd == "info":
                    self._cmd_info(arg.split())
                elif cmd == "exit":
                    print(f"\n{GREEN}Saving & exiting...{RESET}")
                    self._save_state()
                    sys.exit(0)
                else:
                    print(f"{RED}Unknown command. Type 'help'.{RESET}")
            except KeyboardInterrupt:
                print(f"\n{YELLOW}Interrupted. Saving state...{RESET}")
                self._save_state()
                sys.exit(0)
            except Exception as e:
                print(f"{RED}Runtime error: {e}{RESET}")


if __name__ == "__main__":
    ChessOrganizer()