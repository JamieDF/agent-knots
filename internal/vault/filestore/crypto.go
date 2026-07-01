// Package filestore implements Vault on top of local files.
//
// Layout:
//
//	~/.agentjam/vault/
//	├── vault.enc       # AES-256-GCM encrypted credential entries
//	├── vault.key       # Key-encryption-key, optionally fetched from OS
//	│                   # keychain (preferred) or derived from passphrase
//	└── vault.log       # Append-only audit log
//
// The on-disk format is JSON for inspectability. Each entry's "value" field
// is encrypted with AES-256-GCM; metadata (ID, tags, description) is stored
// in cleartext for filtering without unlock.
//
// # Concurrency
//
// All exported methods are safe for concurrent use. Internally, a sync.RWMutex
// guards the in-memory credential map.
package filestore

import (
	"crypto/aes"
	"crypto/cipher"
	"crypto/rand"
	"errors"
	"fmt"
	"io"

	"golang.org/x/crypto/argon2"
)

// Crypto parameters. These are conservative defaults that balance security
// and CPU cost on a laptop.
const (
	// KeyLen is the AES-256 key length.
	KeyLen = 32

	// SaltLen is the salt length for argon2id.
	SaltLen = 16

	// NonceLen is the GCM nonce length.
	NonceLen = 12

	// ArgonTime is the argon2id time cost.
	ArgonTime = 2

	// ArgonMemory is the argon2id memory cost in KiB (64 MiB).
	ArgonMemory = 64 * 1024

	// ArgonThreads is the argon2id thread count.
	ArgonThreads = 2
)

// deriveKey derives a 32-byte AES key from a passphrase using argon2id.
//
// The salt should be randomly generated and stored alongside the ciphertext.
// On unlock, the caller re-derives the key from the passphrase + stored salt
// and attempts decryption; a successful GCM Open proves the passphrase was
// correct.
func deriveKey(passphrase string, salt []byte) []byte {
	return argon2.IDKey([]byte(passphrase), salt, ArgonTime, ArgonMemory, ArgonThreads, KeyLen)
}

// encrypt encrypts plaintext with key using AES-256-GCM. The returned blob
// is nonce || ciphertext || tag, suitable for storage.
func encrypt(key, plaintext []byte) ([]byte, error) {
	if len(key) != KeyLen {
		return nil, fmt.Errorf("crypto: key length %d, want %d", len(key), KeyLen)
	}

	block, err := aes.NewCipher(key)
	if err != nil {
		return nil, fmt.Errorf("crypto: new cipher: %w", err)
	}

	gcm, err := cipher.NewGCM(block)
	if err != nil {
		return nil, fmt.Errorf("crypto: new gcm: %w", err)
	}

	nonce := make([]byte, NonceLen)
	if _, err := io.ReadFull(rand.Reader, nonce); err != nil {
		return nil, fmt.Errorf("crypto: read nonce: %w", err)
	}

	sealed := gcm.Seal(nil, nonce, plaintext, nil)
	return append(nonce, sealed...), nil
}

// decrypt decrypts a blob produced by encrypt. Returns an error if the
// passphrase was wrong or the data was tampered with.
func decrypt(key, blob []byte) ([]byte, error) {
	if len(blob) < NonceLen {
		return nil, errors.New("crypto: blob too short")
	}
	if len(key) != KeyLen {
		return nil, fmt.Errorf("crypto: key length %d, want %d", len(key), KeyLen)
	}

	block, err := aes.NewCipher(key)
	if err != nil {
		return nil, fmt.Errorf("crypto: new cipher: %w", err)
	}

	gcm, err := cipher.NewGCM(block)
	if err != nil {
		return nil, fmt.Errorf("crypto: new gcm: %w", err)
	}

	nonce := blob[:NonceLen]
	ciphertext := blob[NonceLen:]
	plaintext, err := gcm.Open(nil, nonce, ciphertext, nil)
	if err != nil {
		return nil, fmt.Errorf("crypto: open: %w", err)
	}
	return plaintext, nil
}

// newSalt returns a fresh random salt.
func newSalt() ([]byte, error) {
	salt := make([]byte, SaltLen)
	if _, err := io.ReadFull(rand.Reader, salt); err != nil {
		return nil, fmt.Errorf("crypto: read salt: %w", err)
	}
	return salt, nil
}