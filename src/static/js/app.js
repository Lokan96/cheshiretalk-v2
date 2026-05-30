// CheshireTalk v2 — CryptoEngine + UI
class CryptoEngine {
    constructor() {
        this.keyPair = null;
        this.peerKeys = new Map();
        this.sessionCounter = 0;
        this.lastActivity = Date.now();
        this.REKEY_MSG_LIMIT = 50;
        this.REKEY_TIME_LIMIT = 5 * 60 * 1000;
    }

    async init() {
        this.keyPair = await crypto.subtle.generateKey(
            { name: "X25519" }, false, ["deriveBits"]
        );
        console.log("[CryptoEngine] Par X25519 gerado");
    }

    async getPublicKeyBase64() {
        const exported = await crypto.subtle.exportKey("raw", this.keyPair.publicKey);
        return btoa(String.fromCharCode(...new Uint8Array(exported)));
    }

    async getFingerprint(publicKeyB64) {
        const data = Uint8Array.from(atob(publicKeyB64), c => c.charCodeAt(0));
        const hash = await crypto.subtle.digest("SHA-256", data);
        const hex = Array.from(new Uint8Array(hash))
            .map(b => b.toString(16).padStart(2, "0").toUpperCase())
            .join(":");
        return hex.match(/.{1,15}/g).join("\n");
    }

    async deriveKey(peerPublicKeyB64, salt, isInitiator) {
        const peerData = Uint8Array.from(atob(peerPublicKeyB64), c => c.charCodeAt(0));
        const peerKey = await crypto.subtle.importKey("raw", peerData, { name: "X25519" }, false, []);
        const sharedSecret = await crypto.subtle.deriveBits(
            { name: "X25519", public: peerKey }, this.keyPair.privateKey, 256
        );
        const aesKey = await crypto.subtle.deriveKey(
            { name: "HKDF", hash: "SHA-256", salt: salt || crypto.getRandomValues(new Uint8Array(16)), info: new TextEncoder().encode("CTEP-v1") },
            await crypto.subtle.importKey("raw", sharedSecret, "HKDF", false, ["deriveKey"]),
            { name: "AES-GCM", length: 256 }, false, ["encrypt", "decrypt"]
        );
        return { aesKey, salt: salt || new Uint8Array(16) };
    }

    async encryptMessage(plaintext, peerId) {
        const peer = this.peerKeys.get(peerId);
        if (!peer || !peer.aesKey) throw new Error("Chave não derivada");
        const iv = crypto.getRandomValues(new Uint8Array(12));
        const ciphertext = await crypto.subtle.encrypt(
            { name: "AES-GCM", iv }, peer.aesKey, new TextEncoder().encode(plaintext)
        );
        this.sessionCounter++;
        this.lastActivity = Date.now();
        if (this.sessionCounter >= this.REKEY_MSG_LIMIT || (Date.now() - this.lastActivity) > this.REKEY_TIME_LIMIT) {
            this.triggerRekey(peerId);
        }
        return {
            type: "encrypted_message",
            payload: btoa(String.fromCharCode(...new Uint8Array(ciphertext))),
            iv: btoa(String.fromCharCode(...iv)),
            sender: "self", timestamp: new Date().toISOString()
        };
    }

    async decryptMessage(payload, iv, peerId) {
        const peer = this.peerKeys.get(peerId);
        if (!peer || !peer.aesKey) throw new Error("Chave não derivada");
        const ciphertext = Uint8Array.from(atob(payload), c => c.charCodeAt(0));
        const ivBytes = Uint8Array.from(atob(iv), c => c.charCodeAt(0));
        const decrypted = await crypto.subtle.decrypt(
            { name: "AES-GCM", iv: ivBytes }, peer.aesKey, ciphertext
        );
        return new TextDecoder().decode(decrypted);
    }

    async triggerRekey(peerId) {
        console.log("[CryptoEngine] Re-keying iniciado");
        this.sessionCounter = 0; this.lastActivity = Date.now();
        await this.init();
        if (window.socket) window.socket.emit("rekey_request", { peerId });
    }
}

const App = {
    socket: null, crypto: new CryptoEngine(), currentRoom: null,
    peers: new Map(), verifiedFingerprints: new Set(), pendingFingerprint: null,

    async init() {
        await this.crypto.init();
        this.setupEventListeners();
        this.showScreen('home');
    },

    setupEventListeners() {
        document.getElementById('btn-create-room').addEventListener('click', () => this.createRoom());
        document.getElementById('btn-join-room').addEventListener('click', () => this.showScreen('join'));
        document.getElementById('btn-confirm-join').addEventListener('click', () => this.joinRoom());
        document.getElementById('btn-send').addEventListener('click', () => this.sendMessage());
        document.getElementById('msg-input').addEventListener('keypress', (e) => { if (e.key === 'Enter') this.sendMessage(); });
        document.getElementById('btn-verify-fingerprint').addEventListener('click', () => this.verifyFingerprint());
        document.getElementById('btn-dismiss-fingerprint').addEventListener('click', () => this.dismissFingerprint());
    },

    showScreen(screenId) {
        document.querySelectorAll('.screen').forEach(s => s.classList.add('hidden'));
        document.getElementById('screen-' + screenId).classList.remove('hidden');
    },

    async createRoom() {
        const maxP = parseInt(document.getElementById('max-participants').value) || 2;
        const ttl = parseInt(document.getElementById('ttl-seconds').value) || 600;
        try {
            const res = await fetch('/api/v1/rooms', {
                method: 'POST', headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ max_participants: maxP, ttl_seconds: ttl })
            });
            const data = await res.json();
            this.currentRoom = data.room_id;
            document.getElementById('room-code').textContent = this.currentRoom;
            const pubKey = await this.crypto.getPublicKeyBase64();
            document.getElementById('my-public-key').textContent = pubKey;
            if (typeof QRCode !== 'undefined') {
                new QRCode(document.getElementById('qr-code'), { text: pubKey, width: 200, height: 200 });
            }
            this.connectWebSocket(); this.showScreen('room');
        } catch (err) { console.error(err); alert("Erro ao criar sala"); }
    },

    async joinRoom() {
        this.currentRoom = document.getElementById('join-room-code').value.trim();
        const peerPubKey = document.getElementById('join-pubkey').value.trim();
        if (!this.currentRoom || !peerPubKey) { alert("Preencha todos os campos"); return; }
        this.connectWebSocket(); this.showScreen('room');
    },

    connectWebSocket() {
        this.socket = io();
        this.socket.on('connect', () => {
            this.socket.emit('join', { room_id: this.currentRoom, public_key: this.crypto.getPublicKeyBase64() });
        });
        this.socket.on('joined', (data) => {
            data.peers.forEach(peer => {
                if (peer.id !== this.socket.id) {
                    this.peers.set(peer.id, { publicKey: peer.public_key, verified: false });
                    this.showFingerprintModal(peer.id, peer.public_key);
                }
            });
        });
        this.socket.on('peer_joined', (data) => {
            this.peers.set(data.peer_id, { publicKey: data.public_key, verified: false });
            this.showFingerprintModal(data.peer_id, data.public_key);
        });
        this.socket.on('public_key', async (data) => {
            const peer = this.peers.get(data.peer_id);
            if (peer && !peer.derived) {
                const salt = crypto.getRandomValues(new Uint8Array(16));
                const { aesKey } = await this.crypto.deriveKey(data.public_key, salt, true);
                this.crypto.peerKeys.set(data.peer_id, { publicKey: data.public_key, aesKey, salt, derived: true });
                this.socket.emit('key_exchange', { peer_id: data.peer_id, public_key: await this.crypto.getPublicKeyBase64(), salt: btoa(String.fromCharCode(...salt)) });
            }
        });
        this.socket.on('key_exchange', async (data) => {
            const salt = Uint8Array.from(atob(data.salt), c => c.charCodeAt(0));
            const { aesKey } = await this.crypto.deriveKey(data.public_key, salt, false);
            this.crypto.peerKeys.set(data.peer_id, { publicKey: data.public_key, aesKey, salt, derived: true });
            this.socket.emit('key_exchange_complete', { peer_id: data.peer_id });
        });
        this.socket.on('key_exchange_complete', (data) => {
            this.addSystemMessage("🔐 Canal seguro estabelecido");
        });
        this.socket.on('encrypted_message', async (data) => {
            try {
                const plaintext = await this.crypto.decryptMessage(data.payload, data.iv, data.sender);
                this.addMessage(data.sender, plaintext, false);
            } catch (err) { this.addSystemMessage("❌ Erro ao descriptografar"); }
        });
        this.socket.on('peer_left', (data) => {
            this.peers.delete(data.peer_id); this.crypto.peerKeys.delete(data.peer_id);
            this.addSystemMessage("Peer saiu da sala");
        });
    },

    async showFingerprintModal(peerId, publicKey) {
        const fingerprint = await this.crypto.getFingerprint(publicKey);
        document.getElementById('fingerprint-peer-id').textContent = peerId.slice(0, 8);
        document.getElementById('fingerprint-value').textContent = fingerprint;
        document.getElementById('fingerprint-modal').classList.remove('hidden');
        this.pendingFingerprint = { peerId, publicKey, fingerprint };
    },

    verifyFingerprint() {
        if (this.pendingFingerprint) {
            this.verifiedFingerprints.add(this.pendingFingerprint.peerId);
            this.peers.get(this.pendingFingerprint.peerId).verified = true;
            document.getElementById('fingerprint-modal').classList.add('hidden');
            this.addSystemMessage("✅ Fingerprint verificado. Canal confiável.");
        }
    },

    dismissFingerprint() {
        document.getElementById('fingerprint-modal').classList.add('hidden');
        this.addSystemMessage("⚠️ Fingerprint NÃO verificado. Risco de MITM.");
    },

    async sendMessage() {
        const input = document.getElementById('msg-input');
        const text = input.value.trim(); if (!text) return;
        input.value = '';
        for (const [peerId, peer] of this.peers) {
            if (peer.verified) {
                try {
                    const encrypted = await this.crypto.encryptMessage(text, peerId);
                    this.socket.emit('encrypted_message', { ...encrypted, room_id: this.currentRoom });
                } catch (err) { console.error(err); }
            }
        }
        this.addMessage('self', text, true);
    },

    addMessage(sender, text, isSelf) {
        const container = document.getElementById('messages');
        const div = document.createElement('div');
        div.className = `message ${isSelf ? 'self' : 'peer'}`;
        div.innerHTML = `<span class="sender">${isSelf ? 'Você' : sender.slice(0, 8)}</span><span class="text">${this.escapeHtml(text)}</span><span class="time">${new Date().toLocaleTimeString()}</span>`;
        container.appendChild(div); container.scrollTop = container.scrollHeight;
    },

    addSystemMessage(text) {
        const container = document.getElementById('messages');
        const div = document.createElement('div'); div.className = 'system-message'; div.textContent = text;
        container.appendChild(div); container.scrollTop = container.scrollHeight;
    },

    escapeHtml(text) {
        const div = document.createElement('div'); div.textContent = text; return div.innerHTML;
    }
};

document.addEventListener('DOMContentLoaded', () => App.init());
