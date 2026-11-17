import json
import math
import random
import struct
import tempfile
import tkinter as tk
import wave
from pathlib import Path

try:
    import winsound
except ImportError:
    winsound = None


SAVE_FILE = Path(__file__).with_name("snake_save.json")
COLS = 30
ROWS = 20

BG = "#0a120f"
BOARD = "#0e1b15"
GRID = "#192b22"
PANEL = "#12221a"
PANEL_EDGE = "#2a4234"
TEXT = "#f0f4ec"
MUTED = "#94a599"
GREEN = "#b4f078"
MINT = "#61d6ad"
GOLD = "#f3c86b"
CORAL = "#ff7881"
BLUE = "#85c9ff"

DIRECTIONS = {
    "Up": (0, -1),
    "Down": (0, 1),
    "Left": (-1, 0),
    "Right": (1, 0),
}
OPPOSITE = {"Up": "Down", "Down": "Up", "Left": "Right", "Right": "Left"}
POINTS = {"normal": 10, "gold": 25, "bonus": 50}
DIFFICULTIES = {
    "Easy": {"delay": 155, "step": 4, "obstacles": 0, "level_every": 7,
             "gold_chance": 0.05, "bonus_chance": 0.015, "bonus_ttl": 100, "powerup_chance": 0.55},
    "Normal": {"delay": 125, "step": 5, "obstacles": 8, "level_every": 6,
               "gold_chance": 0.07, "bonus_chance": 0.02, "bonus_ttl": 85, "powerup_chance": 0.45},
    "Hard": {"delay": 105, "step": 6, "obstacles": 18, "level_every": 5,
             "gold_chance": 0.08, "bonus_chance": 0.025, "bonus_ttl": 65, "powerup_chance": 0.35},
    "Expert": {"delay": 92, "step": 6, "obstacles": 28, "level_every": 5,
               "gold_chance": 0.09, "bonus_chance": 0.03, "bonus_ttl": 50, "powerup_chance": 0.25},
}
DEFAULT_SETTINGS = {
    "sound": True,
    "music": False,
    "grid": True,
    "particles": True,
    "screen_shake": True,
    "difficulty": "Normal",
}


def load_game_data():
    settings = DEFAULT_SETTINGS.copy()
    high_score = 0
    try:
        data = json.loads(SAVE_FILE.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            high_score = max(0, int(data.get("high_score", 0)))
            stored_settings = data.get("settings", {})
            if isinstance(stored_settings, dict):
                for name in ("sound", "music", "grid", "particles", "screen_shake"):
                    if isinstance(stored_settings.get(name), bool):
                        settings[name] = stored_settings[name]
                difficulty = stored_settings.get("difficulty")
                if difficulty in DIFFICULTIES:
                    settings["difficulty"] = difficulty
    except (OSError, ValueError, TypeError):
        pass
    return high_score, settings


def save_game_data(high_score, settings):
    payload = {"high_score": high_score, "settings": settings}
    try:
        SAVE_FILE.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    except OSError:
        pass


class SnakeEngine:
    """Grid-based game rules, kept separate from Tkinter rendering."""

    def __init__(self):
        self.difficulty = "Normal"
        self.reset()

    @property
    def rules(self):
        return DIFFICULTIES[self.difficulty]

    @property
    def speed_ms(self):
        base = max(55, self.rules["delay"] - (self.level - 1) * self.rules["step"])
        return max(38, base - 28) if self.boost_ticks else base

    def set_difficulty(self, difficulty):
        if difficulty in DIFFICULTIES:
            self.difficulty = difficulty

    def reset(self):
        center = (COLS // 2, ROWS // 2)
        self.snake = [center, (center[0] - 1, center[1]), (center[0] - 2, center[1])]
        self.direction = "Right"
        self.next_direction = "Right"
        self.score = 0
        self.food_count = 0
        self.level = 1
        self.obstacles = set()
        self.powerup = None
        self.shield = False
        self.boost_ticks = 0
        self.particles = []
        self._add_obstacles(self.rules["obstacles"])
        self.food = self._spawn_food()

    def set_direction(self, direction):
        if direction in DIRECTIONS and direction != OPPOSITE[self.next_direction]:
            self.next_direction = direction

    def _empty_cell(self, extra=(), protected_start=False):
        excluded = set(self.snake) | self.obstacles | set(extra)
        candidates = []
        center = self.snake[0]
        for y in range(ROWS):
            for x in range(COLS):
                position = (x, y)
                if position in excluded:
                    continue
                if protected_start and abs(x - center[0]) + abs(y - center[1]) < 5:
                    continue
                candidates.append(position)
        return random.choice(candidates) if candidates else None

    def _add_obstacles(self, count):
        for _ in range(count):
            position = self._empty_cell(protected_start=True)
            if position is None:
                break
            self.obstacles.add(position)

    def _spawn_food(self):
        position = self._empty_cell(extra=({self.powerup["pos"]} if self.powerup else ()))
        if position is None:
            return None
        roll = random.random()
        gold_chance = self.rules["gold_chance"]
        bonus_chance = self.rules["bonus_chance"]
        kind = "gold" if roll < gold_chance else (
            "bonus" if roll < gold_chance + bonus_chance else "normal"
        )
        return {"pos": position, "kind": kind,
            "ttl": self.rules["bonus_ttl"] if kind == "bonus" else 0}

    def _safe_escape(self):
        head = self.snake[0]
        body = set(self.snake[:-1])
        choices = []
        for direction, (dx, dy) in DIRECTIONS.items():
            if direction == OPPOSITE[self.direction]:
                continue
            position = (head[0] + dx, head[1] + dy)
            if not (0 <= position[0] < COLS and 0 <= position[1] < ROWS):
                continue
            if position not in body and position not in self.obstacles:
                choices.append(direction)
        return random.choice(choices) if choices else None

    def _make_particles(self, position):
        for _ in range(12):
            angle = random.random() * math.tau
            speed = random.uniform(0.04, 0.12)
            self.particles.append({
                "x": position[0] + 0.5,
                "y": position[1] + 0.5,
                "dx": math.cos(angle) * speed,
                "dy": math.sin(angle) * speed,
                "life": random.randint(7, 13),
            })

    def step(self, particles_enabled=True):
        events = []
        self.boost_ticks = max(0, self.boost_ticks - 1)
        if self.powerup:
            self.powerup["ttl"] -= 1
            if self.powerup["ttl"] <= 0:
                self.powerup = None
        if self.food and self.food["kind"] == "bonus":
            self.food["ttl"] -= 1
            if self.food["ttl"] <= 0:
                self.food = self._spawn_food()
        for particle in self.particles:
            particle["x"] += particle["dx"]
            particle["y"] += particle["dy"]
            particle["life"] -= 1
        self.particles = [particle for particle in self.particles if particle["life"] > 0]

        self.direction = self.next_direction
        head = self.snake[0]
        dx, dy = DIRECTIONS[self.direction]
        next_head = (head[0] + dx, head[1] + dy)
        eating = self.food is not None and next_head == self.food["pos"]
        body = set(self.snake if eating else self.snake[:-1])
        collision = (
            not (0 <= next_head[0] < COLS and 0 <= next_head[1] < ROWS)
            or next_head in body
            or next_head in self.obstacles
        )
        if collision:
            if self.shield:
                escape = self._safe_escape()
                if escape:
                    self.shield = False
                    self.direction = self.next_direction = escape
                    return ["shield"]
            return ["collision"]

        self.snake.insert(0, next_head)
        if not eating:
            self.snake.pop()
        else:
            kind = self.food["kind"]
            self.score += POINTS[kind]
            self.food_count += 1
            events.append(f"food:{kind}")
            if particles_enabled:
                self._make_particles(next_head)
            previous_level = self.level
            self.level = 1 + self.food_count // self.rules["level_every"]
            if self.level > previous_level:
                events.append("level_up")
                if self.difficulty == "Expert" and self.level % 2 == 0:
                    self._add_obstacles(2)
            self.food = self._spawn_food()
            if self.food is None:
                events.append("victory")
                return events
            if (self.food_count % 6 == 0 and self.powerup is None
                    and random.random() < self.rules["powerup_chance"]):
                position = self._empty_cell(extra={self.food["pos"]})
                if position:
                    kind = random.choice(("shield", "boost"))
                    self.powerup = {"pos": position, "kind": kind, "ttl": 90}

        if self.powerup and next_head == self.powerup["pos"]:
            kind = self.powerup["kind"]
            if kind == "shield":
                self.shield = True
            else:
                self.boost_ticks = 70
            self.powerup = None
            events.append(f"powerup:{kind}")
        return events


class SnakeGame:
    def __init__(self, root):
        self.root = root
        self.root.title("Snake Pro")
        self.root.geometry("1120x800")
        self.root.minsize(860, 680)
        self.root.configure(bg=BG)
        self.root.protocol("WM_DELETE_WINDOW", self.close)

        self.high_score, self.settings = load_game_data()
        self.engine = SnakeEngine()
        self.engine.set_difficulty(self.settings["difficulty"])
        self.state = "MENU"
        self.after_id = None
        self.shake_id = None
        self._shake_offsets = iter(())
        self._shake_previous = 0
        self.music_file = None
        self.hover_action = None
        self.buttons = []
        self.popups = []
        self.tick_count = 0
        self.toast = ""
        self.toast_ticks = 0

        self._build_ui()
        save_game_data(self.high_score, self.settings)
        self._update_header()
        self.draw_scene()
        if self.settings["music"]:
            self._start_music()

    def _build_ui(self):
        shell = tk.Frame(self.root, bg=BG)
        shell.pack(fill="both", expand=True, padx=30, pady=(18, 16))

        header = tk.Frame(shell, bg=BG)
        header.pack(fill="x", pady=(0, 14))
        brand = tk.Frame(header, bg=BG)
        brand.pack(side="left", anchor="w")
        tk.Label(brand, text="SNAKE", font=("Segoe UI", 23, "bold"),
                 bg=BG, fg=TEXT).pack(anchor="w")
        tk.Label(brand, text="ARCADE EDITION", font=("Segoe UI", 8, "bold"),
                 bg=BG, fg=GREEN).pack(anchor="w", pady=(0, 2))

        self.pause_button = tk.Button(
            header, text="PAUSE", command=self.toggle_pause,
            font=("Segoe UI", 9, "bold"), bg=PANEL, fg=TEXT,
            activebackground="#294233", activeforeground=TEXT,
            relief="flat", bd=0, padx=18, pady=11, cursor="hand2",
            disabledforeground="#53645a", takefocus=0
        )
        self.pause_button.pack(side="right", padx=(14, 0))

        metrics = tk.Frame(header, bg=BG)
        metrics.pack(side="right", fill="y")
        self.metric_values = {}
        for name in ("SCORE", "BEST", "LEVEL", "FOOD"):
            block = tk.Frame(metrics, bg=BG)
            block.pack(side="left", padx=(0, 22))
            tk.Label(block, text=name, font=("Segoe UI", 8, "bold"),
                     bg=BG, fg=MUTED).pack(anchor="w")
            value = tk.Label(block, text="0", font=("Segoe UI", 15, "bold"),
                             bg=BG, fg=TEXT)
            value.pack(anchor="w", pady=(2, 0))
            self.metric_values[name] = value

        self.canvas = tk.Canvas(shell, bg=BOARD, highlightthickness=1,
                                highlightbackground=PANEL_EDGE, bd=0)
        self.canvas.pack(fill="both", expand=True)
        self.canvas.bind("<Configure>", self._on_canvas_resize)
        self.canvas.bind("<Motion>", self._on_canvas_motion)
        self.canvas.bind("<Leave>", self._on_canvas_leave)
        self.canvas.bind("<Button-1>", self._on_canvas_click)
        self.root.bind_all("<KeyPress>", self._on_key)

        footer = tk.Frame(shell, bg=BG)
        footer.pack(fill="x", pady=(12, 0))
        self.status_label = tk.Label(footer, text="", font=("Segoe UI", 9),
                                     bg=BG, fg=MUTED)
        self.status_label.pack(side="left")
        tk.Label(footer, text="ARROWS / WASD  MOVE     SPACE  PAUSE     R  RESTART     ESC  MENU",
                 font=("Segoe UI", 8, "bold"), bg=BG, fg="#6e8175").pack(side="right")

    def _update_header(self):
        values = {
            "SCORE": self.engine.score,
            "BEST": self.high_score,
            "LEVEL": self.engine.level,
            "FOOD": self.engine.food_count,
        }
        for key, value in values.items():
            self.metric_values[key].config(text=str(value))
        power_text = "SHIELD" if self.engine.shield else (
            f"BOOST {self.engine.boost_ticks // 10 + 1}" if self.engine.boost_ticks else ""
        )
        self.pause_button.config(
            text="RESUME" if self.state == "PAUSED" else "PAUSE",
            state="normal" if self.state in ("PLAYING", "PAUSED") else "disabled"
        )
        mode = self.settings["difficulty"].upper()
        if self.state == "PLAYING":
            status = f"{mode}  /  LEVEL {self.engine.level}"
            if power_text:
                status += f"  /  {power_text}"
            self.status_label.config(text=status, fg=GREEN)
        elif self.state == "PAUSED":
            self.status_label.config(text="PAUSED  /  timers stopped", fg=GOLD)
        elif self.state == "GAME_OVER":
            self.status_label.config(text="RUN COMPLETE  /  R TO PLAY AGAIN", fg=CORAL)
        else:
            self.status_label.config(text=f"{mode} MODE  /  CLASSIC ARCADE", fg=MUTED)

    def _cancel_loop(self):
        if self.after_id is not None:
            try:
                self.root.after_cancel(self.after_id)
            except tk.TclError:
                pass
            self.after_id = None

    def _schedule_tick(self):
        if self.state == "PLAYING" and self.after_id is None:
            self.after_id = self.root.after(self.engine.speed_ms, self._tick)

    def start_game(self):
        self._cancel_loop()
        self._cancel_shake()
        self.engine.set_difficulty(self.settings["difficulty"])
        self.engine.reset()
        self.popups.clear()
        self.tick_count = 0
        self.state = "PLAYING"
        self._play_sound("start")
        self._update_header()
        self.draw_scene()
        self._schedule_tick()

    def toggle_pause(self):
        if self.state == "PLAYING":
            self._cancel_loop()
            self.state = "PAUSED"
        elif self.state == "PAUSED":
            self.state = "PLAYING"
            self._schedule_tick()
        else:
            return
        self._update_header()
        self.draw_scene()
        self._play_sound("pause")

    def show_menu(self):
        self._cancel_loop()
        self._cancel_shake()
        self.state = "MENU"
        self._update_header()
        self.draw_scene()

    def show_settings(self):
        self._cancel_loop()
        self.state = "SETTINGS"
        self._update_header()
        self.draw_scene()

    def show_how_to_play(self):
        self._cancel_loop()
        self.state = "HOW_TO_PLAY"
        self._update_header()
        self.draw_scene()

    def _tick(self):
        self.after_id = None
        if self.state != "PLAYING":
            return
        self.tick_count += 1
        events = self.engine.step(self.settings["particles"])
        self.popups = [popup for popup in self.popups if popup["life"] > 1]
        for popup in self.popups:
            popup["life"] -= 1

        for event in events:
            if event.startswith("food:"):
                kind = event.split(":", 1)[1]
                points = POINTS[kind]
                head_x, head_y = self.engine.snake[0]
                self.popups.append({"x": head_x + 0.5, "y": head_y, "text": f"+{points}",
                                    "life": 12, "color": GOLD if kind != "normal" else GREEN})
                self._play_sound("special" if kind != "normal" else "food")
                if self.engine.score > self.high_score:
                    self.high_score = self.engine.score
                    save_game_data(self.high_score, self.settings)
            elif event == "level_up":
                self.toast = f"LEVEL {self.engine.level}"
                self.toast_ticks = 20
                self._play_sound("level")
            elif event.startswith("powerup:"):
                self.toast = "SHIELD CHARGED" if event.endswith("shield") else "SPEED BOOST"
                self.toast_ticks = 18
                self._play_sound("powerup")
            elif event == "shield":
                self.toast = "SHIELD SAVED YOU"
                self.toast_ticks = 16
                self._play_sound("powerup")

        if self.toast_ticks:
            self.toast_ticks -= 1
        self._update_header()
        if "collision" in events or "victory" in events:
            self.state = "GAME_OVER"
            self._cancel_loop()
            self._update_header()
            self.draw_scene()
            self._play_sound("over")
            if "collision" in events and self.settings["screen_shake"]:
                self._start_shake()
            return

        self.draw_scene()
        self._schedule_tick()

    def _on_key(self, event):
        key = event.keysym.lower()
        if key == "escape":
            self.show_menu()
            return "break"
        if key == "space":
            if self.state in ("PLAYING", "PAUSED"):
                self.toggle_pause()
            elif self.state == "GAME_OVER":
                self.start_game()
            elif self.state == "MENU":
                self.start_game()
            return "break"
        if key == "r":
            if self.state in ("PLAYING", "PAUSED", "GAME_OVER"):
                self.start_game()
            return "break"
        direction = {
            "up": "Up", "w": "Up", "down": "Down", "s": "Down",
            "left": "Left", "a": "Left", "right": "Right", "d": "Right",
        }.get(key)
        if direction and self.state == "PLAYING":
            self.engine.set_direction(direction)
            return "break"
        return None

    def _on_canvas_click(self, event):
        for x1, y1, x2, y2, action in reversed(self.buttons):
            if x1 <= event.x <= x2 and y1 <= event.y <= y2:
                self._play_sound("click")
                self._dispatch(action)
                return

    def _dispatch(self, action):
        if action == "play" or action == "restart":
            self.start_game()
        elif action == "resume":
            self.toggle_pause()
        elif action == "menu":
            self.show_menu()
        elif action == "settings":
            self.show_settings()
        elif action == "how":
            self.show_how_to_play()
        elif action == "exit":
            self.close()
        elif action.startswith("toggle:"):
            name = action.split(":", 1)[1]
            self.settings[name] = not self.settings[name]
            save_game_data(self.high_score, self.settings)
            if name == "music":
                if self.settings[name]:
                    self._start_music()
                else:
                    self._stop_music()
            self.draw_scene()
        elif action.startswith("difficulty:"):
            difficulty = action.split(":", 1)[1]
            self.settings["difficulty"] = difficulty
            self.engine.set_difficulty(difficulty)
            save_game_data(self.high_score, self.settings)
            self._update_header()
            self.draw_scene()

    def _on_canvas_motion(self, event):
        action = next((button[4] for button in reversed(self.buttons)
                       if button[0] <= event.x <= button[2] and button[1] <= event.y <= button[3]), None)
        if action != self.hover_action:
            self.hover_action = action
            self.canvas.configure(cursor="hand2" if action else "")
            self.draw_scene()

    def _on_canvas_leave(self, _event):
        if self.hover_action is not None:
            self.hover_action = None
            self.draw_scene()

    def _on_canvas_resize(self, _event):
        self.draw_scene()

    def _button(self, center_x, center_y, width, label, action, accent=False, height=42):
        x1, y1 = center_x - width / 2, center_y - height / 2
        x2, y2 = center_x + width / 2, center_y + height / 2
        hovered = action == self.hover_action
        fill = GREEN if accent else ("#263c30" if hovered else PANEL)
        text = BG if accent else (GREEN if hovered else TEXT)
        outline = GREEN if hovered or accent else PANEL_EDGE
        self.canvas.create_rectangle(x1, y1, x2, y2, fill=fill, outline=outline,
                                     width=1, tags="scene")
        self.canvas.create_text(center_x, center_y, text=label,
                                font=("Segoe UI", 9, "bold"), fill=text, tags="scene")
        self.buttons.append((x1, y1, x2, y2, action))

    def _draw_overlay(self, width, height):
        center_x, center_y = width / 2, height / 2
        self.canvas.create_rectangle(0, 0, width, height, fill=BG,
                                     stipple="gray50", outline="", tags="scene")
        if self.state == "MENU":
            self.canvas.create_text(center_x, height * 0.18, text="SNAKE",
                                    font=("Segoe UI", 42, "bold"), fill=TEXT, tags="scene")
            self.canvas.create_text(center_x, height * 0.27,
                                    text="CLASSIC GAMEPLAY. MODERN EXPERIENCE.",
                                    font=("Segoe UI", 10, "bold"), fill=GREEN, tags="scene")
            self.canvas.create_text(center_x, height * 0.35,
                                    text=f"PERSONAL BEST  {self.high_score:04d}",
                                    font=("Segoe UI", 9, "bold"), fill=MUTED, tags="scene")
            for label, action, fraction, accent in (
                ("PLAY", "play", 0.46, True), ("HOW TO PLAY", "how", 0.57, False),
                ("SETTINGS", "settings", 0.68, False), ("EXIT", "exit", 0.79, False),
            ):
                self._button(center_x, height * fraction, 230, label, action, accent)
        elif self.state == "HOW_TO_PLAY":
            self.canvas.create_text(center_x, height * 0.19, text="HOW TO PLAY",
                                    font=("Segoe UI", 25, "bold"), fill=TEXT, tags="scene")
            instructions = (
                ("01", "Move with arrow keys or WASD."),
                ("02", "Collect food to grow and score points."),
                ("03", "Gold is worth 25. Timed bonus food is worth 50."),
                ("04", "Avoid the walls, your tail, and obstacles."),
                ("05", "Power-ups grant a shield or a short speed boost."),
            )
            for index, (number, text) in enumerate(instructions):
                y = height * 0.34 + index * 43
                self.canvas.create_text(center_x - 240, y, text=number,
                                        font=("Segoe UI", 10, "bold"), fill=GREEN, tags="scene")
                self.canvas.create_text(center_x - 205, y, text=text, anchor="w",
                                        font=("Segoe UI", 10), fill=TEXT, tags="scene")
            self._button(center_x, height * 0.82, 180, "BACK", "menu")
        elif self.state == "SETTINGS":
            self.canvas.create_text(center_x, height * 0.13, text="SETTINGS",
                                    font=("Segoe UI", 25, "bold"), fill=TEXT, tags="scene")
            for index, (name, label) in enumerate((
                ("sound", "SOUND EFFECTS"), ("music", "AMBIENT MUSIC"),
                ("grid", "GRID LINES"), ("particles", "FOOD PARTICLES"),
                ("screen_shake", "SCREEN SHAKE"),
            )):
                y = height * 0.28 + index * 43
                self.canvas.create_text(center_x - 205, y, text=label, anchor="w",
                                        font=("Segoe UI", 9, "bold"), fill=TEXT, tags="scene")
                value = "ON" if self.settings[name] else "OFF"
                self._button(center_x + 190, y, 100, value, f"toggle:{name}",
                             accent=self.settings[name], height=34)
            y = height * 0.68
            self.canvas.create_text(center_x, y - 27, text="DIFFICULTY",
                                    font=("Segoe UI", 9, "bold"), fill=MUTED, tags="scene")
            spacing = min(104, (width - 72) / 4)
            start_x = center_x - spacing * 1.5
            for index, difficulty in enumerate(DIFFICULTIES):
                self._button(start_x + spacing * index, y + 13, spacing - 8,
                             difficulty.upper(), f"difficulty:{difficulty}",
                             accent=self.settings["difficulty"] == difficulty, height=34)
            self._button(center_x, height * 0.92, 150, "BACK", "menu")
        elif self.state == "PAUSED":
            self.canvas.create_text(center_x, center_y - 90, text="PAUSED",
                                    font=("Segoe UI", 30, "bold"), fill=TEXT, tags="scene")
            self.canvas.create_text(center_x, center_y - 47, text="Your run is safely paused.",
                                    font=("Segoe UI", 10), fill=MUTED, tags="scene")
            self._button(center_x, center_y + 8, 210, "RESUME", "resume", True)
            self._button(center_x, center_y + 62, 210, "RESTART RUN", "restart")
            self._button(center_x, center_y + 116, 210, "MAIN MENU", "menu")
        elif self.state == "GAME_OVER":
            title = "COURSE COMPLETE" if self.engine.food is None else "GAME OVER"
            self.canvas.create_text(center_x, height * 0.22, text=title,
                                    font=("Segoe UI", 26, "bold"), fill=CORAL, tags="scene")
            self.canvas.create_text(center_x, height * 0.32,
                                    text=f"FINAL SCORE  {self.engine.score:04d}",
                                    font=("Segoe UI", 12, "bold"), fill=TEXT, tags="scene")
            self.canvas.create_text(center_x, height * 0.39,
                                    text=f"BEST  {self.high_score:04d}     LEVEL  {self.engine.level}     FOOD  {self.engine.food_count}",
                                    font=("Segoe UI", 10), fill=MUTED, tags="scene")
            row_y = height * 0.55
            gap = min(180, width / 4)
            self._button(center_x - gap, row_y, 150, "PLAY AGAIN", "restart", True)
            self._button(center_x, row_y, 150, "MAIN MENU", "menu")
            self._button(center_x + gap, row_y, 120, "EXIT", "exit")
            self.canvas.create_text(center_x, height * 0.67,
                                    text="SPACE OR R TO START A NEW RUN",
                                    font=("Segoe UI", 8, "bold"), fill=MUTED, tags="scene")

    def draw_scene(self):
        if not hasattr(self, "canvas") or not self.canvas.winfo_exists():
            return
        self.canvas.delete("all")
        self.buttons = []
        width = max(400, self.canvas.winfo_width())
        height = max(360, self.canvas.winfo_height())
        cell = min((width - 64) / COLS, (height - 48) / ROWS)
        board_width, board_height = cell * COLS, cell * ROWS
        left = (width - board_width) / 2
        top = (height - board_height) / 2
        self.canvas.create_rectangle(left, top, left + board_width, top + board_height,
                                     fill=BOARD, outline=PANEL_EDGE, width=2, tags=("scene", "art"))
        if self.settings["grid"]:
            for column in range(1, COLS):
                x = left + column * cell
                self.canvas.create_line(x, top, x, top + board_height, fill=GRID,
                                        width=1, tags=("scene", "art"))
            for row in range(1, ROWS):
                y = top + row * cell
                self.canvas.create_line(left, y, left + board_width, y, fill=GRID,
                                        width=1, tags=("scene", "art"))

        for x, y in self.engine.obstacles:
            x1, y1 = left + x * cell, top + y * cell
            self.canvas.create_rectangle(x1 + 3, y1 + 3, x1 + cell - 3, y1 + cell - 3,
                                         fill="#3a4a3e", outline="#596b5d", width=1,
                                         tags=("scene", "art"))
        if self.engine.food:
            x, y = self.engine.food["pos"]
            center_x, center_y = left + (x + 0.5) * cell, top + (y + 0.5) * cell
            pulse = 0.87 + math.sin(self.tick_count * 0.35) * 0.08
            radius = cell * 0.32 * pulse
            kind = self.engine.food["kind"]
            color = {"normal": CORAL, "gold": GOLD, "bonus": BLUE}[kind]
            self.canvas.create_oval(center_x - radius * 1.35, center_y - radius * 1.35,
                                    center_x + radius * 1.35, center_y + radius * 1.35,
                                    fill=color, outline="", stipple="gray50", tags=("scene", "art"))
            self.canvas.create_oval(center_x - radius, center_y - radius,
                                    center_x + radius, center_y + radius,
                                    fill=color, outline=TEXT, width=1, tags=("scene", "art"))
        if self.engine.powerup:
            x, y = self.engine.powerup["pos"]
            center_x, center_y = left + (x + 0.5) * cell, top + (y + 0.5) * cell
            color = MINT if self.engine.powerup["kind"] == "shield" else GOLD
            self.canvas.create_oval(center_x - cell * 0.38, center_y - cell * 0.38,
                                    center_x + cell * 0.38, center_y + cell * 0.38,
                                    fill=color, outline=TEXT, width=1, tags=("scene", "art"))
            self.canvas.create_text(center_x, center_y,
                                    text="S" if self.engine.powerup["kind"] == "shield" else "+",
                                    font=("Segoe UI", max(8, int(cell * 0.42)), "bold"),
                                    fill=BG, tags=("scene", "art"))

        body_colors = ("#75d6a9", "#63c797", "#54b987", "#48a878")
        for index, (x, y) in enumerate(self.engine.snake):
            x1, y1 = left + x * cell, top + y * cell
            inset = max(2, cell * 0.09)
            color = GREEN if index == 0 else body_colors[min((index - 1) // 4, len(body_colors) - 1)]
            self.canvas.create_rectangle(x1 + inset, y1 + inset,
                                         x1 + cell - inset, y1 + cell - inset,
                                         fill=color, outline="", tags=("scene", "art"))
            if index == 0:
                self._draw_eyes(x1, y1, cell)

        if self.settings["particles"]:
            for particle in self.engine.particles:
                radius = max(1, cell * 0.07 * particle["life"] / 8)
                px = left + particle["x"] * cell
                py = top + particle["y"] * cell
                self.canvas.create_oval(px - radius, py - radius, px + radius, py + radius,
                                        fill=GOLD, outline="", tags=("scene", "art"))
        for popup in self.popups:
            px = left + popup["x"] * cell
            py = top + popup["y"] * cell - (12 - popup["life"]) * 1.4
            self.canvas.create_text(px, py, text=popup["text"], fill=popup["color"],
                                    font=("Segoe UI", 10, "bold"), tags=("scene", "art"))
        if self.toast_ticks:
            self.canvas.create_text(width / 2, top + 26, text=self.toast,
                                    fill=GOLD, font=("Segoe UI", 10, "bold"), tags=("scene", "art"))
        if self.state != "PLAYING":
            self._draw_overlay(width, height)

    def _draw_eyes(self, x, y, cell):
        direction = self.engine.direction
        if direction in ("Left", "Right"):
            eye_x = x + (cell * 0.66 if direction == "Right" else cell * 0.24)
            points = ((eye_x, y + cell * 0.34), (eye_x, y + cell * 0.66))
        else:
            eye_y = y + (cell * 0.66 if direction == "Down" else cell * 0.24)
            points = ((x + cell * 0.34, eye_y), (x + cell * 0.66, eye_y))
        for eye_x, eye_y in points:
            radius = max(1.5, cell * 0.07)
            self.canvas.create_oval(eye_x - radius, eye_y - radius, eye_x + radius, eye_y + radius,
                                    fill=BG, outline="", tags=("scene", "art"))

    def _start_shake(self):
        if self.shake_id is not None:
            return
        offsets = (-6, 5, -4, 3, 0)
        self._shake_offsets = iter(offsets)
        self._shake_previous = 0
        self._shake_frame()

    def _shake_frame(self):
        try:
            offset = next(self._shake_offsets)
        except StopIteration:
            self.shake_id = None
            return
        self.canvas.move("art", offset - self._shake_previous, 0)
        self._shake_previous = offset
        self.shake_id = self.root.after(28, self._shake_frame)

    def _cancel_shake(self):
        if self.shake_id is not None:
            try:
                self.root.after_cancel(self.shake_id)
            except tk.TclError:
                pass
            self.shake_id = None

    def _play_sound(self, event):
        if not self.settings["sound"] or winsound is None:
            return
        sound = {
            "food": winsound.MB_OK,
            "special": winsound.MB_ICONEXCLAMATION,
            "level": winsound.MB_ICONASTERISK,
            "powerup": winsound.MB_ICONASTERISK,
            "over": winsound.MB_ICONHAND,
            "pause": winsound.MB_OK,
            "start": winsound.MB_OK,
            "click": winsound.MB_OK,
        }.get(event, winsound.MB_OK)
        try:
            winsound.MessageBeep(sound)
        except RuntimeError:
            pass

    def _start_music(self):
        if winsound is None:
            return
        try:
            self.music_file = Path(tempfile.gettempdir()) / f"snake_ambient_{id(self)}.wav"
            sample_rate = 22050
            notes = (130.81, 164.81, 196.00, 164.81)
            samples = bytearray()
            for frequency in notes:
                for index in range(sample_rate // 2):
                    envelope = min(1.0, index / 500, (sample_rate // 2 - index) / 800)
                    value = int(math.sin(math.tau * frequency * index / sample_rate) * 1050 * envelope)
                    samples.extend(struct.pack("<h", value))
            with wave.open(str(self.music_file), "wb") as audio:
                audio.setnchannels(1)
                audio.setsampwidth(2)
                audio.setframerate(sample_rate)
                audio.writeframes(samples)
            winsound.PlaySound(str(self.music_file), winsound.SND_FILENAME |
                               winsound.SND_ASYNC | winsound.SND_LOOP)
        except (OSError, RuntimeError):
            self.music_file = None

    def _stop_music(self):
        if winsound is not None:
            try:
                winsound.PlaySound(None, 0)
            except RuntimeError:
                pass
        if self.music_file:
            try:
                self.music_file.unlink(missing_ok=True)
            except OSError:
                pass
            self.music_file = None

    def close(self):
        self._cancel_loop()
        self._cancel_shake()
        self._stop_music()
        self.root.destroy()


def main():
    root = tk.Tk()
    SnakeGame(root)
    root.mainloop()


if __name__ == "__main__":
    main()
