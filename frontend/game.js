document.addEventListener('DOMContentLoaded', () => {
    const canvas = document.getElementById('gameCanvas');
    const ctx = canvas.getContext('2d');
    const gameModeSelect = document.getElementById('gameMode');
    const gameStatusEl = document.getElementById('gameStatus');
    const uiInfoEl = document.getElementById('uiInfo');
    const playerListEl = document.querySelector('#player-list ul');
    const commandLimitControl = document.getElementById('command-limit-control');
    const commandLimitInput = document.getElementById('commandLimit');

    // Login elements
    const loginContainer = document.getElementById('login-container');
    const nameInput = document.getElementById('nameInput');
    const joinButton = document.getElementById('joinButton');
    const gameContainer = document.querySelector('.container');

    const TILE_SIZE = 25;
    const DIRS = {
        UP: '⬆️',
        DOWN: '⬇️',
        LEFT: '⬅️',
        RIGHT: '➡️'
    };
    let myId = null;
    let gameState = {};
    let ws = null;

    // --- Login Logic ---
    function initLogin() {
        const cachedName = localStorage.getItem('playerName');
        if (cachedName) {
            nameInput.value = cachedName;
        }

        joinButton.addEventListener('click', joinGame);
        nameInput.addEventListener('keyup', (e) => {
            if (e.key === 'Enter') {
                joinGame();
            }
        });
    }

    function joinGame() {
        const name = nameInput.value.trim();
        if (name) {
            localStorage.setItem('playerName', name);
            loginContainer.style.display = 'none';
            gameContainer.style.display = 'flex';
            setupWebSocket(name);
        } else {
            alert('Пожалуйста, введите имя.');
        }
    }


    function setupWebSocket(name) {
        ws = new WebSocket(`ws://${window.location.host}/ws`);
        console.log("Setting up WebSocket...");
        ws.onopen = () => {
            console.log('✅ WebSocket connection established.');
            ws.send(JSON.stringify({ type: 'join', name: name }));
        };
        ws.onclose = () => {
            console.error('❌ WebSocket connection closed.');
            gameStatusEl.textContent = 'Отключено от сервера.';
        };
        ws.onerror = (err) => console.error('❌ WebSocket error:', err);
        ws.onmessage = handleServerMessage;
    }

    function handleServerMessage(event) {
        console.log("⬇️ Received message from server:", event.data);
        const message = JSON.parse(event.data);
        switch (message.type) {
            case 'welcome':
                myId = message.id;
                break;
            case 'gameState':
                const oldMode = gameState.mode;
                const oldTurnPhase = gameState.turn_info?.phase;
                gameState = message.data;

                if (gameState.mode === 'turn_based' && oldTurnPhase === 'executing' && gameState.turn_info.phase === 'collecting') {
                    // Game is resetting for a new turn
                } else if (oldMode && oldMode !== gameState.mode) {
                    gameStatusEl.textContent = 'Админ сменил режим игры! Новая игра началась.';
                }
                // When game state arrives, ensure UI components are in the correct state
                gameModeSelect.value = Object.entries(GAME_MODES).find(([id, name]) => name === gameState.mode)?.[0] || '1';
                commandLimitInput.value = gameState.command_limit;

                updateAdminControls();
                window.requestAnimationFrame(draw);
                break;
            case 'game_over':
                const winner = gameState.players[message.winner_id];
                const winnerName = winner ? winner.name : 'Неизвестный игрок';
                const winnerColor = message.winner_color;
                const winnerText = message.winner_id === myId ? "Вы победили!" : `Победил ${winnerName}!`;
                gameStatusEl.innerHTML = `<span style="color:${winnerColor}; font-weight:bold;">${winnerText}</span>`;
                break;
            case 'notification':
                gameStatusEl.textContent = message.message;
                break;
        }
    }

    function updateAdminControls() {
        const me = gameState.players?.[myId];
        const isAdmin = me && me.name.toLowerCase() === 'admin';
        const controls = document.querySelector('.game-controls');
        
        if (isAdmin) {
            controls.style.display = 'block';
            if (gameState.mode === 'turn_based') {
                commandLimitControl.style.display = 'block';
            } else {
                commandLimitControl.style.display = 'none';
            }
        } else {
            controls.style.display = 'none';
        }
    }

    function draw() {
        if (!gameState.maze) return;
        
        canvas.width = gameState.maze[0].length * TILE_SIZE;
        canvas.height = gameState.maze.length * TILE_SIZE;

        ctx.clearRect(0, 0, canvas.width, canvas.height);
        
        drawMaze();
        drawTraps();
        drawPlayers();
        drawPredictedPaths(); // Updated call
        drawPlayerList();
        drawUI();
    }

    function drawMaze() {
        const { maze, goal } = gameState;
        for (let y = 0; y < maze.length; y++) {
            for (let x = 0; x < maze[y].length; x++) {
                if (maze[y][x] === '#') {
                    ctx.fillStyle = '#607d8b';
                    ctx.fillRect(x * TILE_SIZE, y * TILE_SIZE, TILE_SIZE, TILE_SIZE);
                }
            }
        }
        // Draw Goal
        ctx.fillStyle = '#ffc107';
        ctx.fillRect(goal[0] * TILE_SIZE, goal[1] * TILE_SIZE, TILE_SIZE, TILE_SIZE);
    }
    
    function drawTraps() {
        const { traps } = gameState;
        for (const [pos, type] of Object.entries(traps)) {
            const [x, y] = pos.split(',').map(Number);
            ctx.fillStyle = type === 'return_to_start' ? '#f44336' : '#9c27b0';
            ctx.beginPath();
            ctx.arc(x * TILE_SIZE + TILE_SIZE / 2, y * TILE_SIZE + TILE_SIZE / 2, TILE_SIZE / 3, 0, Math.PI * 2);
            ctx.fill();
        }
    }

    function calculatePredictedPaths() {
        if (gameState.mode !== 'turn_based' || !gameState.players) {
            return {};
        }

        let simulatedPlayers = JSON.parse(JSON.stringify(gameState.players));
        const paths = {};
        for (const p of Object.values(simulatedPlayers)) {
            paths[p.id] = [{x: p.x, y: p.y}];
        }
        
        const sortedPlayers = Object.values(simulatedPlayers).sort((a, b) => a.name.localeCompare(b.name));
        
        const isWall = (x, y) => {
            if (y < 0 || y >= gameState.maze.length || x < 0 || x >= gameState.maze[0].length) {
                return true; 
            }
            return gameState.maze[y][x] === '#';
        };

        for (let i = 0; i < gameState.command_limit; i++) {
            for (const player of sortedPlayers) {
                if (i < player.commands.length) {
                    const direction = player.commands[i];
                    let dx = 0, dy = 0;
                    if (direction === DIRS.UP) dy = -1;
                    else if (direction === DIRS.DOWN) dy = 1;
                    else if (direction === DIRS.LEFT) dx = -1;
                    else if (direction === DIRS.RIGHT) dx = 1;

                    // --- Simulate Global Move ---
                    const proposedMoves = {};
                    for (const p of Object.values(simulatedPlayers)) {
                        const newX = p.x + dx;
                        const newY = p.y + dy;
                        if (!isWall(newX, newY)) {
                            proposedMoves[p.id] = { x: newX, y: newY };
                        } else {
                            proposedMoves[p.id] = { x: p.x, y: p.y };
                        }
                    }

                    const targetCounts = {};
                    for (const pos of Object.values(proposedMoves)) {
                        const key = `${pos.x},${pos.y}`;
                        targetCounts[key] = (targetCounts[key] || 0) + 1;
                    }
                    
                    const collidingTargets = new Set();
                    for (const [key, count] of Object.entries(targetCounts)) {
                        if (count > 1) {
                            collidingTargets.add(key);
                        }
                    }
                    
                    for (const p of Object.values(simulatedPlayers)) {
                        const targetPos = proposedMoves[p.id];
                        const key = `${targetPos.x},${targetPos.y}`;
                        if (!collidingTargets.has(key)) {
                            p.x = targetPos.x;
                            p.y = targetPos.y;
                        }
                    }
                    // --- End Simulation ---
                    
                    for (const p of Object.values(simulatedPlayers)) {
                        paths[p.id].push({x: p.x, y: p.y});
                    }
                }
            }
        }
        return paths;
    }

    function drawPredictedPaths() {
        if (gameState.mode !== 'turn_based' || gameState.turn_info?.phase !== 'collecting') {
            return;
        }

        const predictedPaths = calculatePredictedPaths();
        
        for (const [playerId, path] of Object.entries(predictedPaths)) {
            if (path.length <= 1) continue;

            const player = gameState.players[playerId];
            if (!player) continue;

            const startPoint = path[0];
            const endPoint = path[path.length - 1];

            // Don't draw if the path is trivial
            if (startPoint.x === endPoint.x && startPoint.y === endPoint.y) {
                continue;
            }

            ctx.strokeStyle = player.color;
            ctx.fillStyle = player.color;
            ctx.lineWidth = 2;
            ctx.globalAlpha = 0.5;

            // Draw the path line
            ctx.beginPath();
            ctx.moveTo(
                path[0].x * TILE_SIZE + TILE_SIZE / 2,
                path[0].y * TILE_SIZE + TILE_SIZE / 2
            );
            for (let i = 1; i < path.length; i++) {
                ctx.lineTo(
                    path[i].x * TILE_SIZE + TILE_SIZE / 2,
                    path[i].y * TILE_SIZE + TILE_SIZE / 2
                );
            }
            ctx.stroke();

            // Draw the final destination point
            ctx.beginPath();
            ctx.arc(
                endPoint.x * TILE_SIZE + TILE_SIZE / 2, 
                endPoint.y * TILE_SIZE + TILE_SIZE / 2, 
                TILE_SIZE / 3, 0, Math.PI * 2
            );
            ctx.fill();
            
            ctx.globalAlpha = 1.0; // Reset alpha
        }
    }

    function drawPlayers() {
        const { players } = gameState;
        for (const [id, player] of Object.entries(players)) {
            ctx.fillStyle = player.color;
            ctx.beginPath();
            ctx.arc(player.x * TILE_SIZE + TILE_SIZE / 2, player.y * TILE_SIZE + TILE_SIZE / 2, TILE_SIZE / 2 - 2, 0, Math.PI * 2);
            ctx.fill();
            if (id === myId) {
                ctx.strokeStyle = '#FFFFFF';
                ctx.lineWidth = 2;
                ctx.stroke();
            }
        }
    }

    function drawPlayerList() {
        if (!gameState.players) {
            playerListEl.innerHTML = '';
            return;
        }
        let listHtml = '';
        const sortedPlayers = Object.values(gameState.players).sort((a, b) => a.name.localeCompare(b.name));

        for (const player of sortedPlayers) {
            const isMe = player.id === myId;
            const readyClass = player.is_ready ? 'ready' : '';
            listHtml += `
                <li class="${readyClass}">
                    <span class="player-color-dot" style="background-color: ${player.color};"></span>
                    <span class="player-name">${player.name} ${isMe ? '(Вы)' : ''}</span>
                </li>
            `;
        }
        playerListEl.innerHTML = listHtml;
    }

    function drawUI() {
        const me = gameState.players?.[myId];
        if (!me) {
            uiInfoEl.innerHTML = '';
            return;
        }

        let html = '';
        if (gameState.mode === 'slots') {
            html += '<div><b>Слоты действий:</b></div><div class="slots-container">';
            for (let i = 0; i < 5; i++) {
                html += `<div class="slot ${i < me.slots ? 'filled' : ''}"></div>`;
            }
            html += '</div>';
        } else if (gameState.mode === 'turn_based' && gameState.turn_info) {
            const info = gameState.turn_info;
            html = '<div class="turn-based-info">';

            // Display phase info
            if (info.phase === 'collecting') {
                const allReady = Object.values(gameState.players).every(p => p.is_ready);
                if (allReady) {
                    gameStatusEl.textContent = 'Все готовы! Начинаем выполнение...';
                } else if (me.is_ready) {
                    gameStatusEl.textContent = 'Вы готовы. Ожидаем остальных игроков...';
                } else {
                    gameStatusEl.innerHTML = `Соберите до ${gameState.command_limit} команд.<br/>Нажмите <b>Пробел</b>, когда будете готовы.`;
                }
            } else if (info.phase === 'executing') {
                gameStatusEl.textContent = 'Выполнение команд...';
            }

            // Display all player command queues
            const sortedPlayers = Object.values(gameState.players).sort((a, b) => a.name.localeCompare(b.name));
            for (const player of sortedPlayers) {
                const isMe = player.id === myId;
                html += `<div class="player-commands">
                    <div class="player-name">${player.name}${isMe ? ' (Вы)' : ''}</div>
                    <div class="commands-queue">`;
                
                for (let i = 0; i < gameState.command_limit; i++) {
                    const cmd = player.commands[i];
                    const executingInfo = info.executing_command;
                    const isExecuting = executingInfo && executingInfo.player_id === player.id && executingInfo.command_index === i;
                    const executingClass = isExecuting ? 'executing' : '';

                    if (cmd) {
                        html += `<div class="command ${executingClass}">${cmd}</div>`;
                    } else {
                        html += `<div class="command placeholder ${executingClass}"></div>`;
                    }
                }
                html += `</div></div>`;
            }
            html += '</div>';
        }
        uiInfoEl.innerHTML = html;
    }

    function sendMove(direction) {
        if (gameState.mode === 'turn_based') {
            const me = gameState.players?.[myId];
            if (me && me.commands.length >= gameState.command_limit) {
                console.log("Command queue full.");
                return; // Don't send if queue is full
            }
        }
        console.log(`⬆️ Sending move: ${direction}`);
        ws.send(JSON.stringify({ type: 'move', direction }));
    }

    function handleKeyDown(e) {
        // Allow typing in name input
        if (document.activeElement === nameInput) return;

        // Turn-based mode specific controls
        if (gameState.mode === 'turn_based') {
            const phase = gameState.turn_info?.phase;
            if (phase === 'collecting') {
                 switch (e.key) {
                    case 'ArrowUp':
                    case 'w':
                        sendMove(DIRS.UP);
                        break;
                    case 'ArrowDown':
                    case 's':
                        sendMove(DIRS.DOWN);
                        break;
                    case 'ArrowLeft':
                    case 'a':
                        sendMove(DIRS.LEFT);
                        break;
                    case 'ArrowRight':
                    case 'd':
                        sendMove(DIRS.RIGHT);
                        break;
                    case 'Backspace':
                        ws.send(JSON.stringify({ type: 'remove_command' }));
                        break;
                    case ' ': // Spacebar
                        e.preventDefault(); // prevent scrolling
                        ws.send(JSON.stringify({ type: 'toggle_ready' }));
                        break;
                }
                return; // Don't process general controls
            }
            // Block input during execution
            if (phase === 'executing') return;
        }

        // General controls for other modes
        switch (e.key) {
            case 'ArrowUp':
            case 'w':
                sendMove(gameState.mode === 'turn_based' ? DIRS.UP : 'up');
                break;
            case 'ArrowDown':
            case 's':
                sendMove(gameState.mode === 'turn_based' ? DIRS.DOWN : 'down');
                break;
            case 'ArrowLeft':
            case 'a':
                sendMove(gameState.mode === 'turn_based' ? DIRS.LEFT : 'left');
                break;
            case 'ArrowRight':
            case 'd':
                sendMove(gameState.mode === 'turn_based' ? DIRS.RIGHT : 'right');
                break;
        }
    }
    
    gameModeSelect.addEventListener('change', (e) => {
        const newModeId = e.target.value;
        console.log(`⬆️ Sending set_mode: ${newModeId}`);
        ws.send(JSON.stringify({ type: 'set_mode', mode_id: newModeId }));
    });

    commandLimitInput.addEventListener('change', (e) => {
        const newLimit = parseInt(e.target.value, 10);
        if (ws && !isNaN(newLimit)) {
            console.log(`⬆️ Sending set_command_limit: ${newLimit}`);
            ws.send(JSON.stringify({ type: 'set_command_limit', 'limit': newLimit }));
        }
    });

    document.addEventListener('keydown', handleKeyDown);
    initLogin();
});

const GAME_MODES = {
    '1': 'unlimited',
    '2': 'slots',
    '3': 'turn_based'
};
