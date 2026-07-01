package filestore

import (
	"crypto/rand"
	"testing"
)

// BenchmarkEncrypt measures AES-256-GCM encryption performance.
func BenchmarkEncrypt(b *testing.B) {
	key := make([]byte, KeyLen)
	rand.Read(key)
	plaintext := make([]byte, 1024) // 1 KB
	rand.Read(plaintext)

	b.ResetTimer()
	for i := 0; i < b.N; i++ {
		_, err := encrypt(key, plaintext)
		if err != nil {
			b.Fatal(err)
		}
	}
}

// BenchmarkDecrypt measures AES-256-GCM decryption performance.
func BenchmarkDecrypt(b *testing.B) {
	key := make([]byte, KeyLen)
	rand.Read(key)
	plaintext := make([]byte, 1024)
	rand.Read(plaintext)
	encrypted, err := encrypt(key, plaintext)
	if err != nil {
		b.Fatal(err)
	}

	b.ResetTimer()
	for i := 0; i < b.N; i++ {
		_, err := decrypt(key, encrypted)
		if err != nil {
			b.Fatal(err)
		}
	}
}

// BenchmarkEncryptLarge measures encryption of larger payloads.
func BenchmarkEncryptLarge(b *testing.B) {
	key := make([]byte, KeyLen)
	rand.Read(key)
	plaintext := make([]byte, 64*1024) // 64 KB
	rand.Read(plaintext)

	b.ResetTimer()
	for i := 0; i < b.N; i++ {
		_, err := encrypt(key, plaintext)
		if err != nil {
			b.Fatal(err)
		}
	}
}

// BenchmarkDeriveKey measures argon2id key derivation performance.
func BenchmarkDeriveKey(b *testing.B) {
	salt := make([]byte, SaltLen)
	rand.Read(salt)
	passphrase := "correct horse battery staple"

	b.ResetTimer()
	for i := 0; i < b.N; i++ {
		deriveKey(passphrase, salt)
	}
}

// BenchmarkScrub measures the output-scrubbing performance.
func BenchmarkScrub(b *testing.B) {
	secret := "ghp_supersecrettokenvalue"
	output := make([]byte, 4096)
	for i := range output {
		if i%100 == 0 {
			output[i] = secret[0]
		} else {
			output[i] = 'x'
		}
	}
	str := string(output)

	b.ResetTimer()
	for i := 0; i < b.N; i++ {
		scrub(str, secret)
	}
}

// BenchmarkScrubNoMatch measures scrub performance when no scrubbing occurs.
func BenchmarkScrubNoMatch(b *testing.B) {
	secret := "never appears in the output"
	output := make([]byte, 4096)
	for i := range output {
		output[i] = 'x'
	}
	str := string(output)

	b.ResetTimer()
	for i := 0; i < b.N; i++ {
		scrub(str, secret)
	}
}