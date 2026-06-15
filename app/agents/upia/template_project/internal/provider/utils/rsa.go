package utils

import (
	"crypto"
	"crypto/rand"
	"crypto/rsa"
	"crypto/sha256"
	"crypto/x509"
	"encoding/pem"
	"errors"
	"fmt"
)

//go:generate mockgen -destination=mocks/rsa.go -package=mocks -source=rsa.go

type RsaUtils interface {
	GenerateRSASignature(data []byte) ([]byte, error)
	VerifyRSASignature(data, signature []byte) error
}

type Config struct {
	rsaPrivateKey *rsa.PrivateKey
	rsaPublicKey  *rsa.PublicKey
}

type utilities struct {
	rsaPrivateKey *rsa.PrivateKey
	rsaPublicKey  *rsa.PublicKey
}

func NewRsaUtils(privateKey, pubKey string) (RsaUtils, error) {
	rsaPrivKey, err := parseRsaPrivateKeyFromPem(privateKey)
	if err != nil {
		return nil, err
	}
	rsaPubKey, err := parseRsaPublicKeyFromPem(pubKey)
	if err != nil {
		return nil, err
	}
	return &utilities{
		rsaPrivateKey: rsaPrivKey,
		rsaPublicKey:  rsaPubKey,
	}, nil
}

func (u *utilities) GenerateRSASignature(data []byte) ([]byte, error) {
	msgHash := sha256.New()
	_, err := msgHash.Write(data)
	if err != nil {
		return nil, err
	}
	msgHashSum := msgHash.Sum(nil)
	signature, err := rsa.SignPKCS1v15(rand.Reader, u.rsaPrivateKey, crypto.SHA256, msgHashSum)
	if err != nil {
		return nil, err
	}
	return signature, nil
}

func (u *utilities) VerifyRSASignature(data, signature []byte) error {
	msgHash := sha256.New()
	_, err := msgHash.Write(data)
	if err != nil {
		return err
	}
	msgHashSum := msgHash.Sum(nil)
	err = rsa.VerifyPKCS1v15(u.rsaPublicKey, crypto.SHA256, msgHashSum, signature)
	if err != nil {
		return err
	}
	return nil
}

func parseRsaPrivateKeyFromPem(privPEM string) (*rsa.PrivateKey, error) {
	block, _ := pem.Decode([]byte(privPEM))
	if block == nil {
		return nil, errors.New("failed to parse PEM block containing the key")
	}
	var (
		parsedKey interface{}
		err       error
	)
	if parsedKey, err = x509.ParsePKCS1PrivateKey(block.Bytes); err != nil {
		if parsedKey, err = x509.ParsePKCS8PrivateKey(block.Bytes); err != nil {
			return nil, fmt.Errorf("failed to parse key from PEM block: %w", err)
		}
	}

	privateKey, ok := parsedKey.(*rsa.PrivateKey)
	if !ok {
		return nil, fmt.Errorf("failed to parse private key: %w", err)
	}
	return privateKey, nil
}

func parseRsaPublicKeyFromPem(pubPEM string) (*rsa.PublicKey, error) {
	block, _ := pem.Decode([]byte(pubPEM))
	if block == nil {
		return nil, errors.New("failed to parse PEM block containing the key")
	}

	pub, err := x509.ParsePKIXPublicKey(block.Bytes)
	if err != nil {
		return nil, err
	}

	switch pub := pub.(type) {
	case *rsa.PublicKey:
		return pub, nil
	default:
		break // fall through
	}
	return nil, fmt.Errorf("key type is not RSA")
}
