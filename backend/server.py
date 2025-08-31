import asyncio
import json
import random
from uuid import uuid4
from aiohttp import web
import pathlib

# --- Game Configuration ---
WIDTH, HEIGHT = 25, 25  # Должны быть нечетными
PLAYER_COLORS = ["#FF0000", "#0000FF", "#00FF00", "#FFFF00", "#FF00FF", "#00FFFF"]
GAME_MODES = {
    '1': 'unlimited',
    '2': 'slots',
    '3': 'turn_based'
}
DIRECTION_MAP = {
    '⬆️': 'up',
    '⬇️': 'down',
    '⬅️': 'left',
    '➡️': 'right'
}

# --- Game State Class ---
class Game:
    def __init__(self):
        self.players = {}
        self.maze = []
        self.spawn_points = [
            (1, 1),
            (WIDTH - 2, 1),
            (1, HEIGHT - 2),
            (WIDTH - 2, HEIGHT - 2)
        ]
        self.goal_pos = (WIDTH // 2, HEIGHT // 2)
        self.traps = {}
        self.game_mode = 'unlimited'
        self.command_limit = 5 # Default command limit for turn-based
        self.game_loop_task = None
        self.used_colors = set()
        self.turn_info = {}
        self.app = None # Will hold a reference to the web app
        self.reset_game()

    def reset_game(self):
        print(f"--- RESETTING GAME (mode: {self.game_mode}) ---")
        self.maze = self.generate_maze(WIDTH, HEIGHT)
        self.traps = self.place_traps(5)
        
        if self.game_loop_task:
            self.game_loop_task.cancel()
            self.game_loop_task = None # Ensure task is cleared

        # Reset all existing players' states instead of rebuilding the dict
        player_list = list(self.players.values())
        for i, player in enumerate(player_list):
            # Find a spawn point for the player
            spawn_point = self.spawn_points[i % len(self.spawn_points)]
            player.x, player.y = spawn_point
            player.start_x, player.start_y = spawn_point
            player.slots = 5
            self.reset_player_turn_state(player)

        if self.game_mode == 'slots':
            self.game_loop_task = asyncio.create_task(self.slots_regenerator())
        elif self.game_mode == 'turn_based':
            self.game_loop_task = asyncio.create_task(self.turn_based_loop())

    def reset_player_turn_state(self, player):
        player.commands = []
        player.is_ready = False

    def set_mode(self, mode_id, player_id):
        player = self.players.get(player_id)
        if not player or player.name.lower() != 'admin':
            print(f"--- Unauthorized mode change attempt by {player.name if player else 'Unknown'} ---")
            return False, "Только админ может менять режим игры."

        new_mode = GAME_MODES.get(mode_id)
        if new_mode and new_mode != self.game_mode:
            self.game_mode = new_mode
            self.reset_game()
            return True, f"Режим изменен на '{new_mode}' админом."
        return False, "Режим не изменен."

    def generate_maze(self, width, height):
        # Kruskal's algorithm for maze generation with a Disjoint Set Union (DSU) data structure
        
        # DSU maps each cell to its parent, creating sets of connected cells.
        # Cells are represented by (x, y) tuples.
        parent = {(x, y): (x, y) for y in range(1, height, 2) for x in range(1, width, 2)}

        def find(cell):
            if parent[cell] == cell:
                return cell
            # Path compression for efficiency
            parent[cell] = find(parent[cell])
            return parent[cell]

        def union(cell1, cell2):
            root1 = find(cell1)
            root2 = find(cell2)
            if root1 != root2:
                parent[root2] = root1
                return True
            return False

        # 1. Start with a grid full of walls.
        maze = [['#'] * width for _ in range(height)]
        
        # 2. Create a list of all interior walls that could be removed.
        walls = []
        for y in range(1, height - 1):
            for x in range(1, width - 1):
                if x % 2 == 1 and y % 2 == 0:  # Horizontal wall between (x, y-1) and (x, y+1)
                    walls.append(((x, y), (x, y - 1), (x, y + 1)))
                elif x % 2 == 0 and y % 2 == 1:  # Vertical wall between (x-1, y) and (x+1, y)
                    walls.append(((x, y), (x - 1, y), (x + 1, y)))
        
        random.shuffle(walls)

        # 3. Connect cells by removing walls.
        for wall_pos, cell1, cell2 in walls:
            # If the cells separated by this wall are not already connected...
            if find(cell1) != find(cell2):
                # ...connect them and remove the wall.
                union(cell1, cell2)
                maze[wall_pos[1]][wall_pos[0]] = ' '
                # Also clear the cell spaces themselves (they start as unknown).
                maze[cell1[1]][cell1[0]] = ' '
                maze[cell2[1]][cell2[0]] = ' '

        # Ensure all cell spaces are clear, as a final pass.
        for cell in parent:
            maze[cell[1]][cell[0]] = ' '

        # 4. Make the maze more spacious by removing a percentage of the remaining walls.
        possible_walls_to_remove = []
        for y in range(1, height - 1):
            for x in range(1, width - 1):
                # A wall is a candidate for removal if it's an interior wall.
                if maze[y][x] == '#':
                    # Check for horizontal walls separating two passages
                    if maze[y][x - 1] == ' ' and maze[y][x + 1] == ' ':
                        possible_walls_to_remove.append((x, y))
                    # Check for vertical walls separating two passages
                    elif maze[y - 1][x] == ' ' and maze[y + 1][x] == ' ':
                        possible_walls_to_remove.append((x, y))
        
        random.shuffle(possible_walls_to_remove)
        walls_to_remove_count = int(len(possible_walls_to_remove) * 0.20)
        
        for i in range(walls_to_remove_count):
            x, y = possible_walls_to_remove[i]
            maze[y][x] = ' '
            
        # Ensure spawn points and goal are not walls
        for x, y in self.spawn_points:
            if maze[y][x] == '#':
                maze[y][x] = ' '
        maze[self.goal_pos[1]][self.goal_pos[0]] = 'G'

        return maze

    def place_traps(self, count):
        traps = {}
        empty_tiles = [
            (x, y) for y in range(HEIGHT) for x in range(WIDTH) 
            if self.maze[y][x] == ' ' and (x, y) not in self.spawn_points and (x, y) != self.goal_pos
        ]
        for _ in range(count):
            if not empty_tiles: break
            x, y = random.choice(empty_tiles)
            empty_tiles.remove((x, y))
            trap_type = random.choice(['return_to_start', 'swap_positions'])
            traps[f"{x},{y}"] = trap_type
        return traps

    def get_state(self):
        return {
            "maze": self.maze,
            "players": {pid: p.to_dict() for pid, p in self.players.items()},
            "goal": self.goal_pos,
            "traps": self.traps,
            "mode": self.game_mode,
            "command_limit": self.command_limit
        }

    async def register(self, name):
        player_id = str(uuid4())

        available_colors = [c for c in PLAYER_COLORS if c not in self.used_colors]
        if available_colors:
            color = random.choice(available_colors)
        else:
            color = f"#{random.randint(0, 0xFFFFFF):06x}"
        
        # Cycle through spawn points for new players
        spawn_point = self.spawn_points[len(self.players) % len(self.spawn_points)]
        
        player = Player(player_id, spawn_point[0], spawn_point[1], color, name)
        self.players[player_id] = player
        self.used_colors.add(color)
        print(f"Player {player_id} ({name}) created at {spawn_point} with color {color}. Total players: {len(self.players)}")
        return player

    async def unregister(self, player_id):
        if player_id in self.players:
            player_color = self.players[player_id].color
            self.used_colors.discard(player_color)
            del self.players[player_id]
            print(f"Player {player_id} disconnected. Total players: {len(self.players)}")

    def is_wall(self, x, y):
        return self.maze[y][x] == '#'

    def execute_global_move(self, direction):
        """Moves all players in the specified direction."""
        mapped_direction = DIRECTION_MAP.get(direction, direction)
        dx, dy = 0, 0
        if mapped_direction == 'up': dy = -1
        elif mapped_direction == 'down': dy = 1
        elif mapped_direction == 'left': dx = -1
        elif mapped_direction == 'right': dx = 1

        # --- Player Collision Logic ---
        # 1. Propose move for each player
        proposed_moves = {}
        for p in self.players.values():
            new_x, new_y = p.x + dx, p.y + dy
            if not self.is_wall(new_x, new_y):
                proposed_moves[p.id] = (new_x, new_y)
            else:
                # If wall, they intend to stay in place
                proposed_moves[p.id] = (p.x, p.y)

        # 2. Find colliding moves (multiple players aiming for the same tile)
        target_counts = {}
        for pos in proposed_moves.values():
            target_counts[pos] = target_counts.get(pos, 0) + 1
        
        colliding_targets = {pos for pos, count in target_counts.items() if count > 1}

        # 3. Execute non-colliding moves
        for p in self.players.values():
            target_pos = proposed_moves[p.id]
            if target_pos not in colliding_targets:
                p.x, p.y = target_pos
        # --- End Collision Logic ---


    async def handle_move(self, player_id, direction):
        player = self.players.get(player_id)
        if not player: return
        print(f"[Move Attempt] Player {player_id} -> {direction} in '{self.game_mode}' mode")

        # Game mode specific move validation
        if self.game_mode == 'slots' and player.slots <= 0:
            print(f"[Move Rejected] Player {player_id} has no slots.")
            return [] # Return empty list of events
        if self.game_mode == 'turn_based':
            if len(player.commands) < self.command_limit:
                if direction in DIRECTION_MAP:
                    player.commands.append(direction)
                    print(f"[Command Added] Player {player_id} added '{direction}'. Commands: {player.commands}")
            else:
                print(f"[Command Rejected] Player {player_id} command list is full.")
            return [] # Don't move immediately

        if self.game_mode == 'slots':
            player.slots -= 1

        # This is the core logic change: one move affects ALL players.
        self.execute_global_move(direction)
        
        # After the global move, check events for all players.
        events = []
        # Iterate over a copy of player IDs in case a trap removes a player
        for p_id in list(self.players.keys()):
            p = self.players.get(p_id)
            if p:
                event = await self.check_game_events(p)
                if event:
                    events.append(event)
                    # If a player wins, stop checking for other events
                    if event.get('type') == 'game_over':
                        break
        return events

    async def check_game_events(self, player):
        pos_key = f"{player.x},{player.y}"
        
        # Check for win
        if (player.x, player.y) == self.goal_pos:
            return {
                'type': 'game_over',
                'winner_id': player.id,
                'winner_color': player.color
            }
        
        # Check for traps
        if pos_key in self.traps:
            trap_type = self.traps[pos_key]
            del self.traps[pos_key] # Trap disappears after use
            if trap_type == 'return_to_start':
                player.x, player.y = player.start_x, player.start_y
            elif trap_type == 'swap_positions':
                positions = [(p.x, p.y) for p in self.players.values()]
                random.shuffle(positions)
                for i, p in enumerate(self.players.values()):
                    p.x, p.y = positions[i]
            return {
                'type': 'notification',
                'message': f'Player {player.id[:4]}... activated a "{trap_type.replace("_", " ")}" trap!'
            }
        return None

    def remove_last_command(self, player_id):
        player = self.players.get(player_id)
        if player and self.game_mode == 'turn_based' and player.commands:
            player.commands.pop()
            print(f"Player {player_id} removed last command. Commands: {player.commands}")

    def toggle_player_ready(self, player_id):
        player = self.players.get(player_id)
        if player and self.game_mode == 'turn_based':
            player.is_ready = not player.is_ready
            print(f"Player {player.id} readiness set to {player.is_ready}")

    # --- Game Mode Coroutines ---
    async def slots_regenerator(self):
        while True:
            await asyncio.sleep(1)
            for player in self.players.values():
                if player.slots < 5:
                    player.slots += 1

    async def turn_based_loop(self):
        while self.game_mode == 'turn_based':
            # Phase 1: Collect commands
            self.turn_info = {'phase': 'collecting', 'executing_command': None}
            for p in self.players.values(): self.reset_player_turn_state(p)
            await broadcast_state(self.app)

            # Wait for all players to be ready
            while not (self.players and all(p.is_ready for p in self.players.values())):
                await asyncio.sleep(0.5)
                if self.game_mode != 'turn_based': return

            # Phase 2: Execute commands
            self.turn_info['phase'] = 'executing'
            await broadcast_state(self.app)
            await asyncio.sleep(1) # Brief pause before execution starts

            # Get a fixed order of players for this execution round
            player_order = sorted(list(self.players.values()), key=lambda p: p.name)
            game_over = False

            for i in range(self.command_limit):
                for player in player_order:
                    if i < len(player.commands):
                        direction = player.commands[i]
                        
                        # Set current executing command for UI feedback
                        self.turn_info['executing_command'] = {'player_id': player.id, 'command_index': i}
                        await broadcast_state(self.app)
                        await asyncio.sleep(0.4)

                        self.execute_global_move(direction)
                        
                        # Check events for all players
                        for p_check in player_order:
                            event = await self.check_game_events(p_check)
                            if event:
                                await broadcast_event(self.app, event)
                                if event.get('type') == 'game_over':
                                    self.reset_game()
                                    game_over = True
                                    break
                        
                        await broadcast_state(self.app)
                        if game_over: break
                        await asyncio.sleep(0.4)
                    if game_over: break
                if game_over: break
            
            if game_over:
                await asyncio.sleep(3) # Show winner
            
            if self.game_mode != 'turn_based': return
            
            # Loop back to collecting phase immediately


class Player:
    def __init__(self, id, x, y, color, name="Anonymous"):
        self.id = id
        self.name = name
        self.start_x = x
        self.start_y = y
        self.x = x
        self.y = y
        self.color = color
        self.slots = 5
        self.commands = []
        self.is_ready = False

    def to_dict(self):
        return {
            "name": self.name,
            "id": self.id,
            "x": self.x, "y": self.y, "color": self.color, 
            "slots": self.slots, "commands": self.commands,
            "is_ready": self.is_ready
        }

# --- WebSocket Handling ---
game = Game()

async def broadcast_state(app):
    if not app['websockets']: return
    state = game.get_state()
    if game.game_mode == 'turn_based':
        state['turn_info'] = game.turn_info
    message = json.dumps({"type": "gameState", "data": state})
    print(f"📢 Broadcasting state ({len(message)} bytes) to {len(app['websockets'])} clients.")
    for ws in app['websockets']:
        await ws.send_str(message)

async def broadcast_event(app, event):
    if not app['websockets']: return
    message = json.dumps({"type": "gameEvent", "data": event})
    print(f"📢 Broadcasting event ({len(message)} bytes) to {len(app['websockets'])} clients.")
    for ws in app['websockets']:
        await ws.send_str(message)

async def websocket_handler(request):
    ws = web.WebSocketResponse()
    await ws.prepare(request)
    
    app = request.app
    player = None
    
    try:
        async for msg in ws:
            if msg.type == web.WSMsgType.TEXT:
                data = json.loads(msg.data)
                
                if player is None:
                    if data.get('type') == 'join':
                        name = data.get('name', 'Anonymous')
                        player = await game.register(name)
                        app['websockets'][ws] = player
                        
                        print(f"🤝 Welcoming player {player.id} ({player.name})")
                        await ws.send_str(json.dumps({"type": "welcome", "id": player.id}))
                        await broadcast_state(app)
                    continue

                print(f"⬇️ Received message from {player.id}: {msg.data}")
                
                if data['type'] == 'move':
                    # handle_move now returns a list of events
                    events = await game.handle_move(player.id, data['direction'])
                    await broadcast_state(app)
                    for event in events:
                        await broadcast_event(app, event)
                        if event.get('type') == 'game_over':
                            game.reset_game()
                            await asyncio.sleep(2)
                            await broadcast_state(app)

                elif data['type'] == 'set_mode':
                    print(f"🔄 Player {player.id} ({player.name}) requested mode change to {data['mode_id']}")
                    success, message = game.set_mode(data['mode_id'], player.id)
                    if success:
                        await broadcast_state(app)
                    # Optionally, send a notification back to the admin or all players
                    await broadcast_event(app, {'type': 'notification', 'message': message})

                elif data['type'] == 'remove_command':
                    game.remove_last_command(player.id)
                    await broadcast_state(app)
                
                elif data['type'] == 'toggle_ready':
                    game.toggle_player_ready(player.id)
                    await broadcast_state(app)

                elif data['type'] == 'set_command_limit':
                    new_limit = data.get('limit')
                    if player.name.lower() == 'admin' and isinstance(new_limit, int) and 1 <= new_limit <= 10:
                        game.command_limit = new_limit
                        print(f"Admin {player.id} set command limit to {new_limit}")
                        await broadcast_state(app)

            elif msg.type == web.WSMsgType.ERROR:
                print(f'ws connection closed with exception {ws.exception()}')

    except Exception as e:
        if player:
            print(f"An error occurred with player {player.id} ({player.name}): {e}")
        else:
            print(f"An error occurred with a connecting player: {e}")
    finally:
        if player:
            print(f"🔌 Connection closed for player {player.id} ({player.name})")
            if ws in app['websockets']:
                del app['websockets'][ws]
            await game.unregister(player.id)
            await broadcast_state(app)
        
    return ws

async def on_shutdown(app):
    if game.game_loop_task:
        game.game_loop_task.cancel()
    for ws in list(app['websockets'].keys()):
        await ws.close(code=1001, message='Server shutdown')

def main():
    app = web.Application()
    app['websockets'] = {} # Using a dict to map ws to player
    game.app = app # Give game instance access to the app
    
    # Setup static file serving for the frontend
    frontend_path = pathlib.Path(__file__).parent.parent / 'frontend'
    app.router.add_static('/', frontend_path, show_index=True, follow_symlinks=True)
    
    # Setup WebSocket route
    app.router.add_get('/ws', websocket_handler)
    
    app.on_shutdown.append(on_shutdown)
    
    print("Server starting on http://0.0.0.0:8080")
    web.run_app(app, host="0.0.0.0", port=8080)

if __name__ == "__main__":
    main()
