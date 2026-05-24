const $ = id => document.getElementById(id);

const state = {
    socket: null,
    roomId: null,
    sid: null,
    crypto: null,
    peers: new Map(),
    messageCount: 0,
    connected: false,
    typingTimeout: null,
    timerInterval: null,
};

class CryptoEngine {
    constructor() {
        this.keyPair = null;
        this.aesKeys = new Map();
    }

    async generateKeyPair() {
        this.keyPair = await window.crypto.subtle.generateKey(
            { name: 'X25519' },
            true,
            ['deriveBits']
        );
        return this.exportPublicKey();
    }

    async exportPublicKey() {
        const raw = await window.crypto.subtle.exportKey('raw', this.keyPair.publicKey);
        return btoa(String.fromCharCode(...new Uint8Array(raw)))
            .replace(/\+/g, '-').replace(/\//g, '_').replace(/=/g, '');
    }

    async importPeerPublicKey(b64) {
        const pad = b64.length % 4;
        if (pad) b64 += '='.repeat(4 - pad);
        const b64std = b64.replace(/-/g, '+').replace(/_/g, '/');
        const raw = Uint8Array.from(atob(b64std), c => c.charCodeAt(0));
        return window.crypto.subtle.importKey('raw', raw, { name: 'X25519' }, false, []);
    }

    async deriveSharedSecret(peerPublicKey, peerId, saltB64 = null) {
        const sharedBits = await window.crypto.subtle.deriveBits(
            { name: 'X25519', public: peerPublicKey },
            this.keyPair.privateKey,
            256
        );
        const sharedSecret = new Uint8Array(sharedBits);
        
        let salt;
        if (saltB64) {
            const pad = saltB64.length % 4;
            if (pad) saltB64 += '='.repeat(4 - pad);
            const saltStd = saltB64.replace(/-/g, '+').replace(/_/g, '/');
            salt = Uint8Array.from(atob(saltStd), c => c.charCodeAt(0));
        } else {
            salt = window.crypto.getRandomValues(new Uint8Array(32));
        }

        const hkdfKey = await window.crypto.subtle.importKey(
            'raw', sharedSecret, 'HKDF', false, ['deriveKey']
        );
        const aesKey = await window.crypto.subtle.deriveKey(
            { name: 'HKDF', hash: 'SHA-256', salt, info: new TextEncoder().encode('CTEP-v1') },
            hkdfKey,
            { name: 'AES-GCM', length: 256 },
            false,
            ['encrypt', 'decrypt']
        );
        
        this.aesKeys.set(peerId, aesKey);
        
        const saltOut = btoa(String.fromCharCode(...salt))
            .replace(/\+/g, '-').replace(/\//g, '_').replace(/=/g, '');
        return { salt: saltOut, publicKey: await this.exportPublicKey() };
    }

    async encrypt(peerId, plaintext) {
        const aesKey = this.aesKeys.get(peerId);
        if (!aesKey) throw new Error('Chave AES não derivada para ' + peerId);
        const iv = window.crypto.getRandomValues(new Uint8Array(12));
        const ciphertext = await window.crypto.subtle.encrypt(
            { name: 'AES-GCM', iv },
            aesKey,
            new TextEncoder().encode(plaintext)
        );
        return {
            iv: btoa(String.fromCharCode(...iv)).replace(/\+/g, '-').replace(/\//g, '_').replace(/=/g, ''),
            ciphertext: btoa(String.fromCharCode(...new Uint8Array(ciphertext))).replace(/\+/g, '-').replace(/\//g, '_').replace(/=/g, '')
        };
    }

    async decrypt(peerId, ivB64, ciphertextB64) {
        const aesKey = this.aesKeys.get(peerId);
        if (!aesKey) throw new Error('Chave AES não derivada para ' + peerId);
        
        const pad = s => {
            const p = s.length % 4;
            return p ? s + '='.repeat(4 - p) : s;
        };
        const iv = Uint8Array.from(atob(pad(ivB64).replace(/-/g, '+').replace(/_/g, '/')), c => c.charCodeAt(0));
        const ct = Uint8Array.from(atob(pad(ciphertextB64).replace(/-/g, '+').replace(/_/g, '/')), c => c.charCodeAt(0));
        
        const plaintext = await window.crypto.subtle.decrypt({ name: 'AES-GCM', iv }, aesKey, ct);
        return new TextDecoder().decode(plaintext);
    }

    reset() {
        this.keyPair = null;
        this.aesKeys.clear();
    }
}

function showScreen(id) {
    document.querySelectorAll('.screen').forEach(s => s.classList.add('hidden'));
    $(id).classList.remove('hidden');
}

function addMessage(text, type = 'system') {
    const container = $('messages');
    const div = document.createElement('div');
    const time = new Date().toLocaleTimeString('pt-BR', { hour: '2-digit', minute: '2-digit' });
    const colors = {
        system: 'text-[#8b949e] italic',
        self: 'ml-auto bg-[rgba(31,111,235,0.15)] text-[#c9d1d9]',
        peer: 'bg-[#21262d] text-[#c9d1d9]',
    };
    div.className = `max-w-[80%] p-3 rounded-lg text-sm ${colors[type] || colors.system}`;
    div.innerHTML = `<div class="flex items-center gap-2"><span class="opacity-50 text-xs">${time}</span><span>${escapeHtml(text)}</span></div>`;
    container.appendChild(div);
    container.scrollTop = container.scrollHeight;
}

function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

function setStatus(text, type = 'info') {
    const el = $('status-indicator');
    el.textContent = text;
    const colors = { info: 'text-[#58a6ff]', success: 'text-[#3fb950]', error: 'text-[#f85149]', warning: 'text-[#d29922]' };
    el.className = `text-center mt-4 text-xs font-mono ${colors[type] || colors.info}`;
}

function updateTimer(expiresAt) {
    if (state.timerInterval) clearInterval(state.timerInterval);
    state.timerInterval = setInterval(() => {
        const remaining = Math.max(0, expiresAt - Date.now() / 1000);
        const mins = Math.floor(remaining / 60);
        const secs = Math.floor(remaining % 60);
        $('timer-display').textContent = `${mins.toString().padStart(2, '0')}:${secs.toString().padStart(2, '0')}`;
        if (remaining <= 0) {
            clearInterval(state.timerInterval);
            leaveRoom();
            addMessage('Sala auto-destruída.', 'system');
        }
    }, 1000);
}

async function createRoom() {
    const participants = parseInt($('participants-slider').value);
    const timerPreset = document.querySelector('.timer-preset.active');
    const timerCustom = parseInt($('timer-custom').value);
    const ttl = timerCustom && timerCustom >= 30 && timerCustom <= 86400
        ? timerCustom
        : parseInt(timerPreset?.dataset.seconds || 600);
    const password = $('room-password').value || null;
    const forwardSecrecy = $('forward-secrecy').checked;

    try {
        setStatus('Criando sala...', 'info');
        const res = await fetch('/api/v1/rooms', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ max_participants: participants, ttl_seconds: ttl, password, forward_secrecy: forwardSecrecy })
        });
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const data = await res.json();
        state.roomId = data.room_id;
        $('room-id-display').textContent = data.room_id;
        $('qr-code').textContent = `https://${location.host}/?room=${data.room_id}`;
        updateTimer(data.expires_at);
        await connectWebSocket(data.room_id, password);
        showScreen('chat-screen');
        setStatus('Conectado • E2EE ativo', 'success');
        addMessage('Sala criada. Aguardando peers...', 'system');
    } catch (err) {
        console.error(err);
        setStatus('Erro ao criar sala: ' + err.message, 'error');
    }
}

async function joinRoom() {
    const roomId = $('join-room-id').value.trim().toUpperCase();
    const password = $('join-password').value || null;
    if (!roomId) return setStatus('Informe o ID da sala', 'warning');

    try {
        setStatus('Entrando na sala...', 'info');
        const res = await fetch(`/api/v1/rooms/${roomId}`);
        if (!res.ok) throw new Error('Sala não encontrada');
        const data = await res.json();
        state.roomId = roomId;
        $('room-id-display').textContent = roomId;
        updateTimer(data.expires_at);
        await connectWebSocket(roomId, password);
        showScreen('chat-screen');
        setStatus('Conectado • E2EE ativo', 'success');
        addMessage('Entrou na sala. Troca de chaves em andamento...', 'system');
    } catch (err) {
        setStatus('Erro: ' + err.message, 'error');
    }
}

async function leaveRoom() {
    if (state.socket) {
        state.socket.disconnect();
        state.socket = null;
    }
    if (state.timerInterval) clearInterval(state.timerInterval);
    state.roomId = null;
    state.peers.clear();
    state.messageCount = 0;
    state.connected = false;
    if (state.crypto) state.crypto.reset();
    $('messages').innerHTML = '';
    showScreen('home-screen');
    setStatus('Desconectado', 'info');
}

async function connectWebSocket(roomId, password) {
    return new Promise((resolve, reject) => {
        state.crypto = new CryptoEngine();
        state.crypto.generateKeyPair().then(publicKey => {
            state.socket = io({ transports: ['websocket'] });

            state.socket.on('connect', () => {
                state.sid = state.socket.id;
                state.socket.emit('join', { room_id: roomId, public_key: publicKey, password });
            });

            state.socket.on('joined', async (data) => {
                state.connected = true;
                if (data.peers) {
                    for (const peer of data.peers) {
                        await handlePeerJoin(peer);
                    }
                }
                resolve();
            });

            state.socket.on('peer_joined', async (data) => {
                if (data.sid === state.sid) return;
                state.peers.set(data.sid, { sid: data.sid, publicKey: data.public_key, derived: false });
                addMessage(`Peer entrou (${data.sid.slice(0, 6)}...)`, 'system');
                updatePeerCount();
            });

            state.socket.on('peer_left', (data) => {
                state.peers.delete(data.sid);
                addMessage(`Peer saiu (${data.sid.slice(0, 6)}...)`, 'system');
                updatePeerCount();
            });

            // Recebemos public_key do outro peer (como RESPONDER)
            state.socket.on('public_key', async (data) => {
                let peer = state.peers.get(data.sid);
                if (!peer) {
                    peer = { sid: data.sid, publicKey: data.public_key, derived: false };
                    state.peers.set(data.sid, peer);
                }
                
                peer.publicKey = data.public_key;
                const peerKey = await state.crypto.importPeerPublicKey(data.public_key);
                
                // Somos o RESPONDER — usamos o salt do INITIATOR
                const result = await state.crypto.deriveSharedSecret(peerKey, data.sid, data.salt);
                peer.derived = true;
                
                // Enviamos nossa chave pública de volta (sem salt, o initiator já tem)
                state.socket.emit('key_exchange_complete', { target_sid: data.sid, public_key: result.publicKey });
                addCryptoStep('ECDH', `Chave derivada com peer ${data.sid.slice(0, 6)}`);
            });

            // Recebemos confirmação de key exchange (como INITIATOR)
            // FIX: NÃO derivamos de novo! Já derivamos no handlePeerJoin.
            // Só marcamos o peer como derived = true.
            state.socket.on('key_exchange_complete', async (data) => {
                const peer = state.peers.get(data.sid);
                if (!peer) return;
                if (peer.derived) return;
                
                // O initiator JÁ derivou a chave no handlePeerJoin com o salt que gerou.
                // Agora só confirma que o responder recebeu e derivou também.
                peer.derived = true;
                addCryptoStep('ECDH', `Key exchange confirmado com peer ${data.sid.slice(0, 6)}`);
            });

            state.socket.on('message', async (data) => {
                try {
                    const plaintext = await state.crypto.decrypt(data.from_sid, data.iv, data.ciphertext);
                    addMessage(`${plaintext}`, 'peer');
                    state.messageCount++;
                } catch (err) {
                    console.error('Decryption error:', err);
                    addMessage('Falha ao decifrar mensagem', 'system');
                }
            });

            state.socket.on('typing', () => {
                $('typing-indicator').textContent = 'Peer digitando...';
                setTimeout(() => $('typing-indicator').textContent = '', 2000);
            });

            state.socket.on('error', (data) => {
                setStatus('Erro: ' + data.message, 'error');
                reject(new Error(data.message));
            });

            state.socket.on('disconnect', () => {
                state.connected = false;
                setStatus('Desconectado', 'warning');
            });
        }).catch(reject);
    });
}

// handlePeerJoin: chamado no 'joined' — somos o INITIATOR
async function handlePeerJoin(data) {
    if (data.sid === state.sid) return;
    
    state.peers.set(data.sid, { sid: data.sid, publicKey: data.public_key, derived: false });
    
    if (data.public_key) {
        const peerKey = await state.crypto.importPeerPublicKey(data.public_key);
        // Somos o INITIATOR — geramos salt e enviamos
        const result = await state.crypto.deriveSharedSecret(peerKey, data.sid, null);
        state.socket.emit('public_key', { target_sid: data.sid, public_key: result.publicKey, salt: result.salt });
    }
    updatePeerCount();
}

function updatePeerCount() {
    $('peer-count').textContent = state.peers.size;
}

async function sendMessage() {
    const input = $('message-input');
    const text = input.value.trim();
    if (!text || !state.connected) return;
    if (state.peers.size === 0) {
        addMessage('Aguardando peers para cifrar...', 'system');
        return;
    }

    input.value = '';
    addMessage(text, 'self');

    for (const [peerSid, peer] of state.peers) {
        if (!peer.derived) continue;
        try {
            const encrypted = await state.crypto.encrypt(peerSid, text);
            state.socket.emit('message', {
                target_sid: peerSid,
                iv: encrypted.iv,
                ciphertext: encrypted.ciphertext
            });
            state.messageCount++;
        } catch (err) {
            console.error('Erro ao cifrar:', err);
        }
    }
}

function sendTyping() {
    if (state.socket && state.connected) {
        state.socket.emit('typing', {});
    }
}

async function performRekey() {
    if (!state.connected || state.peers.size === 0) return;
    addMessage('Re-keying iniciado...', 'system');
    const newPublicKey = await state.crypto.generateKeyPair();
    for (const [peerSid, peer] of state.peers) {
        const peerKey = await state.crypto.importPeerPublicKey(peer.publicKey);
        const result = await state.crypto.deriveSharedSecret(peerKey, peerSid, null);
        state.socket.emit('public_key', { target_sid: peerSid, public_key: result.publicKey, salt: result.salt });
    }
    addMessage('Re-keying concluído', 'system');
}

function addCryptoStep(step, detail) {
    const list = $('crypto-steps');
    const li = document.createElement('li');
    li.className = 'text-xs font-mono border-l-2 border-[#3fb950] pl-2';
    li.innerHTML = `<span class="text-[#3fb950]">[${step}]</span> ${escapeHtml(detail)}`;
    list.appendChild(li);
    list.scrollTop = list.scrollHeight;
}

function toggleCryptoModal(show) {
    $('crypto-modal').classList.toggle('hidden', !show);
}

document.addEventListener('DOMContentLoaded', () => {
    const slider = $('participants-slider');
    slider.addEventListener('input', () => {
        $('participants-value').textContent = slider.value;
    });

    document.querySelectorAll('.timer-preset').forEach(btn => {
        btn.addEventListener('click', () => {
            document.querySelectorAll('.timer-preset').forEach(b => {
                b.classList.remove('active', 'border-[#58a6ff]', 'text-[#58a6ff]');
            });
            btn.classList.add('active', 'border-[#58a6ff]', 'text-[#58a6ff]');
        });
    });

    $('btn-create').addEventListener('click', createRoom);
    $('btn-join').addEventListener('click', joinRoom);
    $('btn-leave').addEventListener('click', leaveRoom);
    $('btn-send').addEventListener('click', sendMessage);
    $('btn-rekey').addEventListener('click', performRekey);

    $('btn-close-qr').addEventListener('click', () => $('qr-modal').classList.add('hidden'));
    $('btn-show-crypto').addEventListener('click', () => toggleCryptoModal(true));
    $('btn-close-crypto').addEventListener('click', () => toggleCryptoModal(false));

    $('message-input').addEventListener('keypress', (e) => {
        if (e.key === 'Enter') sendMessage();
        else sendTyping();
    });

    const params = new URLSearchParams(location.search);
    if (params.has('room')) {
        $('join-room-id').value = params.get('room');
    }

    fetch('/api/v1/health').then(r => r.ok && setStatus('Servidor online', 'success')).catch(() => setStatus('Servidor offline', 'error'));
});
