# CheshireTalk v2 — Documento Mestre de Planejamento

> Última atualização: 2026-05-26
> Status: **EM DESENVOLVIMENTO — Criptografia E2EE funcional**
> Autor: Lokan96
> Stack: FastAPI + Vanilla JS + Tailwind CSS
> Deploy: Render (free tier) + UptimeRobot anti-sleep

---

## 1. Diagnóstico do v1 (Problemas Identificados)

| Problema | Por que era amador | Como soava pro professor |
|---|---|---|
| Máximo 2 pessoas | Limitação arbitrária, não técnica | "O aluno não soube implementar broadcast" |
| Timer fixo 10min | Hardcoded, zero controle do usuário | "Falta análise de requisitos do usuário" |
| Front cyberpunk genérico | Scanlines + neon ≠ hacker. É cosplay | "Estética datada, não minimalista" |
| ECDH com bugs | Web Crypto API é robusta, o erro é arquitetural | "Não domina criptografia aplicada" |
| Senha mestre removida à força | `if False:` é gambiarra, não solução | "Falta engenharia de software" |
| Zero persistência = feature? | RAM wipe é trivial, não diferencial | "Confunde ausência de feature com segurança" |

---

## 2. Decisões Técnicas Confirmadas

| Decisão | Escolha | Implementação |
|---|---|---|
| Forward secrecy | B (completo) | Re-keying a cada 50 mensagens ou 5 min inatividade |
| Persistência | A (zero absoluto) | RAM-only, sem logs de conteúdo, metadata em memória (IPs hasheados) |
| Participantes | B (2-10 configurável) | Default 2, max 10, broadcast cifrado individual |
| Timer | Completamente personalizável | Slider 30s a 24h, ou input manual em segundos |
| Linguagem backend | FastAPI (Python) | Async nativo, WebSocket nativo, auto-docs |
| Frontend | Vanilla JS (ES2022) + Tailwind CSS | Zero bundle, carrega em <100ms |
| Deploy | Render (free tier) | WebSocket nativo, sem cartão, UptimeRobot anti-sleep |
| Protocolo WebSocket | JSON (por simplicidade) | MessagePack como upgrade futuro |
| Crypto backend | pycryptodome | Padrão indústria, auditado |
| Crypto frontend | Web Crypto API | X25519 + HKDF + AES-GCM nativo no browser |
| **Anti-MITM** | **TOFU + Fingerprint** | **SHA-256 da chave derivada, verificação manual** |

---

## 3. SDK — Arquitetura Técnica (CTEP v1.0)

### 3.1 Protocolo de Handshake

```
┌─────────────────────────────────────────────────────────────┐
│                    CTEP v1.0 — Handshake                   │
├─────────────────────────────────────────────────────────────┤
│ 1. Criador gera par X25519 (ephemeral)                     │
│ 2. Exporta chave pública → QR code / Base64                │
│ 3. Peer escaneia/insere → gera par X25519 próprio          │
│ 4. ECDH deriveBits(256) → segredo compartilhado            │
│ 5. HKDF-SHA256(salt=aleatório, info="CTEP-v1")            │
│    → chave AES-256-GCM                                     │
│ 6. Mensagens: AES-256-GCM(iv=12bytes aleatório)            │
│ 7. Forward secrecy: NOVO par X25519 a cada re-keying      │
│    (a cada 50 msgs ou 5min inatividade)                    │
└─────────────────────────────────────────────────────────────┘
```

### 3.2 Fluxo de Key Exchange (Corrigido)

**Problema encontrado e resolvido:** Double-derivation
- **Causa:** Ambos os peers derivavam a chave, gerando salts diferentes
- **Fix:** Só o INITIATOR (quem tem a chave pública do outro primeiro) deriva e gera o salt. O RESPONDER usa o salt recebido.

```
Peer A (Criador/Initiator)          Peer B (Entrado/Responder)
     |                                       |
     | 1. Gera par X25519                     |
     | 2. Entra na sala (join)                |
     | 3. Recebe lista de peers (joined)      |
     | 4. Deriva chave com pubkey do Peer B   |
     | 5. Envia public_key + salt             |----> 6. Recebe public_key + salt
     |                                       | 7. Deriva com MESMO salt
     | 8. Recebe key_exchange_complete <------| 8. Envia key_exchange_complete
     | 9. Marca como derived (NÃO deriva      |
     |    de novo!)                          |
```

### 3.3 Estrutura de Pastas

```
cheshiretalk-v2/
├── .github/
│   └── workflows/
│       └── deploy.yml              # CI/CD Render
├── src/
│   ├── __init__.py
│   ├── main.py                     # Entry point FastAPI + SocketIO
│   ├── config.py                   # Settings (Pydantic, env vars)
│   ├── state.py                    # Instâncias globais (room_manager, socket_manager)
│   ├── api/
│   │   ├── __init__.py
│   │   └── rooms.py                # REST endpoints (criar, listar, deletar salas)
│   ├── ws/
│   │   ├── __init__.py
│   │   └── manager.py              # WebSocket events (join, leave, message, typing)
│   ├── core/
│   │   ├── __init__.py
│   │   ├── crypto.py               # X25519 + HKDF + AES-GCM (backend)
│   │   └── room.py                 # Room model, lifecycle, cleanup
│   └── static/                     # Landing page, assets
│       ├── index.html              # UI completa (Tailwind CDN)
│       └── js/
│           └── app.js                # CryptoEngine + WebSocket client + UI
├── tests/
├── docs/
│   └── planejamento.md             # Este arquivo
├── Dockerfile
├── docker-compose.yml
├── requirements.txt
├── setup.py                        # Instalação em modo dev
├── run.sh                          # Script de execução local
├── git_commit_ai.py                # Script de commit automatizado com Groq
└── README.md
```

---

## 4. Requisitos Funcionais (RF1-RF10)

| RF | Descrição | Status |
|----|-----------|--------|
| RF01 | Criar sala: ID aleatório 6 chars, QR code chave pública ECDH | ✅ |
| RF02 | Entrar sala: canal_id + chave pública peer (Base64/QR) | ✅ |
| RF03 | Configurar timer: 30s a 24h ou manual | ✅ |
| RF04 | Enviar mensagem: criptografa → broadcast individual | ✅ |
| RF05 | Receber mensagem: descriptografa → exibe | ✅ |
| RF06 | Indicar digitação: debounce 500ms | ✅ |
| RF07 | Autodestruir: timer expira ou usuário sai | ✅ |
| RF08 | Modo educacional: passo-a-passo criptografia (toggle) | ⚠️ Parcial |
| RF09 | Multi-participante: 2-10, default 2 | ✅ |
| RF10 | Re-keying: novo par X25519 a cada N mensagens | ⚠️ Estrutura pronta |

---

## 5. Requisitos Não-Funcionais (RNF1-RNF10)

| RNF | Descrição | Status |
|-----|-----------|--------|
| RNF01 | Segurança: E2EE default, servidor nunca vê plaintext | ✅ |
| RNF02 | Performance: Handshake <500ms, mensagem <100ms local, <2s remoto | ✅ |
| RNF03 | Escalabilidade: 100 salas simultâneas, 10 participantes/sala | ✅ |
| RNF04 | Usabilidade: Setup <30s, sem cadastro | ✅ |
| RNF05 | Confiabilidade: 99.9% uptime, auto-reconnect | ⚠️ Pendente |
| RNF06 | Privacidade: Zero persistência, metadata mínimo | ✅ |
| RNF07 | Educação: Visualizador <100ms overhead | ⚠️ Parcial |
| RNF08 | Compatibilidade: Chrome 90+, Firefox 88+, Safari 14+, Edge 90+ | ✅ |
| RNF09 | Acessibilidade: WCAG 2.1 AA | ❌ Pendente |
| RNF10 | Internacionalização: i18n ready (PT-BR, EN-US) | ❌ Pendente |

---

## 6. Paleta Visual — Minimalista Técnico

| Elemento | Cor |
|----------|-----|
| Background | `#0d1117` (GitHub dark) |
| Background secundário | `#161b22` |
| Background terciário | `#21262d` |
| Texto primário | `#c9d1d9` |
| Texto secundário/muted | `#8b949e` |
| Acento info | `#58a6ff` |
| Acento sucesso | `#3fb950` |
| Acento alerta | `#d29922` |
| Acento erro | `#f85149` |
| Bordas | `#30363d` |
| Fontes | Inter (interface), JetBrains Mono (código) |

---

## 7. Deploy — Análise de Opções 2026

### 7.1 Cenário: Escola com Firefox + DNS over HTTPS (DoH)

**Sua configuração:** Firefox + DoH ativo na escola. Isso muda o jogo:

| Aspecto | Sem DoH | Com DoH |
|---------|---------|---------|
| DNS blocking | Vulnerável | Bypassado |
| SNI/ECH | Visível | Escondido |
| HTTPS | Padrão | Primeiro |
| .onrender.com | Provavelmente bloqueado | **Alta chance de funcionar** |
| .railway.app | Provavelmente bloqueado | **Alta chance de funcionar** |
| Cloudflare Tunnel | Backup | Backup se falhar |

**Conclusão:** Com DoH ativo, Render é viável na escola. A chance de bloqueio cai drasticamente.

### 7.2 Opções de Deploy Comparadas

| Plataforma | WebSocket | Sleep | Limite | Cartão? | Bloqueio Escola? | Nota |
|-----------|-----------|-------|--------|---------|-----------------|------|
| **Render** | ✅ Nativo | 15min idle | 750h/mês | ❌ Não | ⚠️ Possível (DoH ajuda) | **Melhor UX, recomendado** |
| **Railway** | ✅ Nativo | Scale-to-zero | $5 crédito/mês | ❌ Não | ⚠️ Possível | Crédito acaba = pausa |
| **Koyeb** | ✅ Nativo | No sleep | Nano instance | ✅ Sim | ❓ | Exige cartão |
| **Fly.io** | ✅ Nativo | No sleep | $5 crédito | ✅ Sim | Baixo | Exige cartão |
| **Northflank** | ✅ Nativo | No sleep | 1 service free | ❌ Não | Baixo | Requer cartão no free |
| **Glitch** | ✅ Nativo | Não dorme | Público | ❌ Não | Raramente | Só Node.js |
| **Cloudflare Workers** | ✅ Durable Objects | No sleep | 100k req/dia | ❌ Não | Muito baixo | Edge compute, não Python nativo |
| **Supabase Realtime** | ✅ Built-in | 7 dias inatividade | 200 conexões | ❌ Não | Muito baixo | BaaS, não PaaS |
| **GitHub Pages** | ❌ Static only | — | Static | ❌ Não | Não | Só frontend |

### 7.3 Decisão Final

| Cenário | Solução |
|---------|---------|
| **Desenvolvimento** | Local (`python3 -m uvicorn src.main:socket_app --host 0.0.0.0 --port 8000`) |
| **Deploy Principal** | **Render** (free, UptimeRobot anti-sleep) |
| **Backup na Escola** | Cloudflare Tunnel do PC de casa (se Render falhar) |
| **Portfólio** | GitHub Pages (landing estática) + Render (API) |
| **Demo Professor** | Render (grátis, sleep aceitável com UptimeRobot) |

### 7.4 Anti-Sleep (UptimeRobot)

Render dorme após 15min. Solução: UptimeRobot gratuito pinga a cada 5min:

```
GET /api/v1/health → retorna {"status": "ok"}
```

- UptimeRobot gratuito: 50 monitors, ping a cada 5min
- Mantém Render acordado 24/7

---

## 8. Segurança — Análise de Ameaças e Mitigações

### 8.1 🚨 MITM no Key Exchange (Crítico)

**Problema:** O ECDH troca chaves públicas através do servidor. Um servidor comprometido poderia substituir as chaves públicas de ambos os peers por chaves suas — ataque man-in-the-middle clássico.

**Mitigação: TOFU (Trust on First Use)**

Modelo adotado por Signal, SSH e Matrix:
- O primeiro key exchange é confiado upon first contact
- **Fingerprint SHA-256** da chave pública derivada é exibido para ambos os usuários
- Verificação manual fora de banda (por voz, por exemplo)
- Alertas para rotações de chave inesperadas

**Implementação no CheshireTalk:**
```javascript
// Gerar fingerprint da chave pública
async function getFingerprint(publicKeyB64) {
    const data = Uint8Array.from(atob(publicKeyB64), c => c.charCodeAt(0));
    const hash = await crypto.subtle.digest('SHA-256', data);
    return Array.from(new Uint8Array(hash))
        .map(b => b.toString(16).padStart(2, '0').toUpperCase())
        .join(':')
        .match(/.{1,15}/g)
        .join('
'); // Formato: A3:F2:9C:... em 3 linhas de 5 octetos
}
// Ex: A3:F2:9C:4B:E1  D8:7A:01:3F:B2  5C:E9:11:7D:8A
```

**Status:** ⚠️ Estrutura pronta, implementação pendente no frontend

### 8.2 ⚠️ Cross-Site WebSocket Hijacking (CSWSH)

**Problema:** Browsers incluem cookies nos requests de handshake WebSocket. Um site malicioso pode hijackar conexões autenticadas.

**Mitigação:** Validar o header `Origin` no servidor ao aceitar conexões.

```python
# Em src/ws/manager.py, no evento connect
@sio.on("connect")
async def on_connect(sid, environ):
    origin = environ.get('HTTP_ORIGIN', '')
    allowed_origins = ['https://seudominio.com', 'http://localhost:8000']
    if origin and origin not in allowed_origins:
        return False  # Rejeita conexão
```

**Status:** ⚠️ Pendente implementação

### 8.3 ✅ Metadata Privacy

**O que já está implementado:**
- Zero persistência de conteúdo (RAM-only)
- IPs hasheados (SHA-256 com salt rotativo)
- Sem logs de quem falou com quem
- Sem histórico de mensagens no servidor

**O que documentar no TCC:**
- O servidor conhece apenas: ID da sala, timestamp de criação, número de participantes
- Não há correlação entre identidade e conteúdo
- Metadata mínimo = privacidade real

---

## 9. Melhorias Futuras (Pós-MVP)

### 9.1 Criptografia Avançada

| Melhoria | Descrição | Prioridade |
|----------|-----------|------------|
| **Double Ratchet** | Signal Protocol — cada mensagem com chave única | Alta |
| **X3DH** | Extended Triple Diffie-Hellman — autenticação mútua | Média |
| **Post-Quantum** | PQXDH (ML-KEM + X25519) — resistência quântica | Baixa (futuro) |
| **Perfect Forward Secrecy** | Apagar chaves antigas automaticamente | Alta |

### 9.2 Arquitetura

| Melhoria | Descrição | Prioridade |
|----------|-----------|------------|
| **MessagePack** | Protocolo binário — 50% menos bytes que JSON | Média |
| **Pub/Sub** | Redis/SQS para escalar WebSocket horizontalmente | Baixa |
| **Sharding** | Distribuir salas entre múltiplos servidores | Baixa |
| **WebRTC P2P** | Conexão direta entre peers (sem servidor de relay) | Média |

### 9.3 UX/Frontend

| Melhoria | Descrição | Prioridade |
|----------|-----------|------------|
| **QR Code scan** | Câmera para escanear chaves públicas | Média |
| **Notificações** | Push notifications quando app em background | Média |
| **Tema claro/escuro** | Toggle de tema | Baixa |
| **Mobile app** | PWA com service worker | Média |
| **i18n** | PT-BR, EN-US, ES | Baixa |

### 9.4 Segurança

| Melhoria | Descrição | Prioridade |
|----------|-----------|------------|
| **Rate limiting robusto** | Token bucket por IP + por sala | Alta |
| **Anti-spam** | CAPTCHA ou proof-of-work | Média |
| **Audit logs** | Metadata de entrada/saída (sem conteúdo) | Média |
| **Honeypot** | Salas fake para detectar scanners | Baixa |

---

## 10. Stack Tecnológica Atual

| Camada | Tecnologia | Versão |
|--------|-----------|--------|
| Backend | Python | 3.12 |
| Framework | FastAPI | 0.111.0 |
| WebSocket | python-socketio | 5.11.0 |
| Servidor | uvicorn | 0.30.0 |
| Criptografia backend | pycryptodome | 3.20.0 |
| Config | pydantic-settings | 2.2.0 |
| Criptografia frontend | Web Crypto API | Nativo (SubtleCrypto) |
| Frontend | Vanilla JS | ES2022 |
| CSS | Tailwind CSS | CDN |
| QR Code | qrcode.js | CDN |
| Socket Client | Socket.IO | CDN |
| Deploy | Render | Free tier |
| Anti-sleep | UptimeRobot | Free tier |

---

## 11. Comandos Úteis

```bash
# Desenvolvimento local
cd ~/TCC/cheshiretalk-v2
source .venv/bin/activate
export PYTHONPATH=/home/grimm/TCC/cheshiretalk-v2
python3 -m uvicorn src.main:socket_app --host 0.0.0.0 --port 8000

# Git com IA
python3 ~/git_commit_ai.py push

# Agente local Groq
python3 ~/agente_local_v21.py

# Teste de API
curl -s http://localhost:8000/api/v1/health
curl -s -X POST http://localhost:8000/api/v1/rooms   -H "Content-Type: application/json"   -d '{"max_participants":2,"ttl_seconds":300}'
```

---

## 12. Bugs Conhecidos e Resolvidos

| Bug | Causa | Solução | Data |
|-----|-------|---------|------|
| WebSocket recusando conexão | FastAPI app não expunha Socket.IO | Mudar `src.main:app` para `src.main:socket_app` | 2026-05-26 |
| Eventos não casando | Frontend emitia `join`, backend ouvia `join_room` | Unificar nomes de eventos | 2026-05-26 |
| Double-derivation | Ambos os peers geravam salts diferentes | Initiator gera salt, responder usa o mesmo | 2026-05-26 |
| Decifragem falhando | Chaves AES diferentes dos dois lados | Corrigir fluxo de key exchange | 2026-05-26 |
| Disco 100% cheio | Ollama + backups + caches | Limpar `~/.ollama`, backups antigos, caches | 2026-05-26 |

---

## 13. Referências e Pesquisa

- Signal Protocol Documentation: https://signal.org/docs/
- Double Ratchet Algorithm: Signal's forward secrecy implementation
- WebSocket Security Cheat Sheet: OWASP
- Render Free Tier 2026: Platforms with real free tier
- WebRTC P2P: Peer-to-peer messaging without servers
- X25519/ECDH: W3C Cryptography Guidelines
- Cloudflare Workers: Durable Objects for WebSocket
- TOFU Model: Trust on First Use (SSH, Signal, Matrix)
- CSWSH: Cross-Site WebSocket Hijacking (OWASP)

---

*Documento gerado em 2026-05-26. Última atualização: sincronização com estrutura atual do projeto + deep search de melhorias + análise de segurança (MITM/TOFU, CSWSH, metadata privacy).*
