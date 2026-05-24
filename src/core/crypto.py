import os
import secrets
import base64
from typing import Optional, Tuple

from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey, X25519PublicKey
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives import serialization


class CryptoManager:
    """Gerenciador de criptografia E2EE do CheshireTalk v2
    
    Protocolo CTEP v1.0:
    1. X25519 ECDH para troca de chaves
    2. HKDF-SHA256 para derivação de chave simétrica
    3. AES-256-GCM para cifragem de mensagens
    4. Re-keying automático a cada N mensagens ou timeout
    """
    
    def __init__(self):
        self._private_key: Optional[X25519PrivateKey] = None
        self._public_key: Optional[X25519PublicKey] = None
        self._shared_secret: Optional[bytes] = None
        self._aes_key: Optional[bytes] = None
        self._message_count = 0
        self._last_rekey = 0.0
    
    def generate_keypair(self) -> str:
        """Gera par de chaves X25519 e retorna chave pública em Base64"""
        self._private_key = X25519PrivateKey.generate()
        self._public_key = self._private_key.public_key()
        return self.export_public_key()
    
    def export_public_key(self) -> str:
        """Exporta chave pública em Base64 URL-safe"""
        if not self._public_key:
            raise ValueError("Chave pública não gerada")
        raw = self._public_key.public_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PublicFormat.Raw
        )
        return base64.urlsafe_b64encode(raw).decode().rstrip("=")
    
    def import_peer_public_key(self, b64_key: str) -> X25519PublicKey:
        """Importa chave pública do peer a partir de Base64"""
        padding = 4 - len(b64_key) % 4
        if padding != 4:
            b64_key += "=" * padding
        raw = base64.urlsafe_b64decode(b64_key)
        return X25519PublicKey.from_public_bytes(raw)
    
    def derive_shared_secret(self, peer_public_key: X25519PublicKey, 
                            salt: Optional[bytes] = None,
                            info: bytes = b"CTEP-v1-AES256GCM") -> bytes:
        """Deriva segredo compartilhado via ECDH + HKDF"""
        if not self._private_key:
            raise ValueError("Chave privada não gerada")
        
        shared = self._private_key.exchange(peer_public_key)
        
        if salt is None:
            salt = os.urandom(32)
        
        hkdf = HKDF(
            algorithm=hashes.SHA256(),
            length=32,
            salt=salt,
            info=info,
            backend=default_backend()
        )
        self._shared_secret = hkdf.derive(shared)
        self._aes_key = self._shared_secret
        self._message_count = 0
        self._last_rekey = __import__("time").time()
        
        return self._shared_secret
    
    def encrypt(self, plaintext: str) -> dict:
        """Cifra mensagem com AES-256-GCM"""
        if not self._aes_key:
            raise ValueError("Chave AES não derivada")
        
        iv = os.urandom(12)
        aesgcm = AESGCM(self._aes_key)
        data = plaintext.encode("utf-8")
        ciphertext = aesgcm.encrypt(iv, data, None)
        
        self._message_count += 1
        
        return {
            "iv": base64.urlsafe_b64encode(iv).decode().rstrip("="),
            "ciphertext": base64.urlsafe_b64encode(ciphertext).decode().rstrip("="),
        }
    
    def decrypt(self, iv_b64: str, ciphertext_b64: str) -> str:
        """Decifra mensagem com AES-256-GCM"""
        if not self._aes_key:
            raise ValueError("Chave AES não derivada")
        
        for b64 in [iv_b64, ciphertext_b64]:
            padding = 4 - len(b64) % 4
            if padding != 4:
                b64 += "=" * padding
        
        iv = base64.urlsafe_b64decode(iv_b64)
        ciphertext = base64.urlsafe_b64decode(ciphertext_b64)
        
        aesgcm = AESGCM(self._aes_key)
        plaintext = aesgcm.decrypt(iv, ciphertext, None)
        
        return plaintext.decode("utf-8")
    
    def should_rekey(self, threshold: int = 50, timeout: int = 300) -> bool:
        """Verifica se é necessário re-keying"""
        if self._message_count >= threshold:
            return True
        if __import__("time").time() - self._last_rekey > timeout:
            return True
        return False
    
    def rekey(self, peer_public_key: X25519PublicKey, salt: Optional[bytes] = None) -> str:
        """Gera novo par de chaves e re-deriva segredo"""
        self.generate_keypair()
        self.derive_shared_secret(peer_public_key, salt)
        return self.export_public_key()
    
    def reset(self):
        """Limpa todas as chaves da memória"""
        self._private_key = None
        self._public_key = None
        self._shared_secret = None
        self._aes_key = None
        self._message_count = 0
        self._last_rekey = 0.0
