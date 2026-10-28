// Quarry regression checks for GHSA-mgcc-cww5-fp2q, based on upstream
// go-jose commit a0111f82742fa92bceec9ede40845e73319e6230 (Apache-2.0).
package jose

import (
	"crypto/rsa"
	"encoding/base64"
	"github.com/go-jose/go-jose/v3/json"
	"math/big"
	"strings"
	"testing"
)

func TestQuarryRSABounds(t *testing.T) {
	old := MaxRSAModulusBits
	defer func() { MaxRSAModulusBits = old }()
	odd := func(bits int) *byteBuffer {
		n := new(big.Int).Lsh(big.NewInt(1), uint(bits-1))
		return newBuffer(n.SetBit(n, 0, 1).Bytes())
	}
	for _, bits := range []int{4095, 4096, 4097, 1 << 20} {
		key := rawJSONWebKey{N: odd(bits), E: newBufferFromInt(65537)}
		_, err := key.rsaPublicKey()
		if (err != nil) != (bits > 4096) { t.Fatalf("public modulus %d: %v", bits, err) }
	}
	for _, kind := range []string{"valid", "large-modulus", "large-prime", "mismatch", "equal", "zero", "one"} {
		t.Run(kind, func(t *testing.T) {
			key, err := fromRsaPrivateKey(rsaTestKey); if err != nil { t.Fatal(err) }
			want := "p * q != n"
			switch kind {
			case "valid": want = ""
			case "large-modulus": key.N = odd(1 << 20); want = "modulus too large"
			case "large-prime": key.P = odd(1 << 20)
			case "mismatch": key.P = newBuffer(new(big.Int).Add(rsaTestKey.Primes[0], big.NewInt(2)).Bytes())
			case "equal": key.Q = key.P
			case "zero": key.P = newBuffer([]byte{})
			case "one": key.P = newBufferFromInt(1)
			}
			_, err = key.rsaPrivateKey()
			if want == "" { if err != nil { t.Fatal(err) } } else if err == nil || !strings.Contains(err.Error(), want) { t.Fatalf("expected %s; got %v", want, err) }
		})
	}
	MaxRSAModulusBits = rsaTestKey.N.BitLen()-1
	key, _ := fromRsaPrivateKey(rsaTestKey)
	if _, err := key.rsaPrivateKey(); err == nil { t.Fatal("lowered private cap ignored") }
	if _, err := (rawJSONWebKey{N:key.N,E:key.E}).rsaPublicKey(); err == nil { t.Fatal("lowered public cap ignored") }
	MaxRSAModulusBits++
	if _, err := key.rsaPrivateKey(); err != nil { t.Fatal(err) }
}

func TestQuarryStandaloneKeys(t *testing.T) {
	data, err := json.Marshal(JSONWebKey{Key:rsaTestKey}); if err != nil { t.Fatal(err) }
	var key JSONWebKey
	if err := json.Unmarshal(data,&key); err != nil { t.Fatal(err) }
	if _, ok := key.Key.(*rsa.PrivateKey); !ok { t.Fatal("standalone private key lost") }
	var keys JSONWebKeySet
	if err := json.Unmarshal([]byte(`{"keys":[`+string(data)+`]}`), &keys); err != nil || len(keys.Keys)!=1 { t.Fatalf("standalone JWKS: %v",err) }
}

func TestQuarryEmbeddedPrivateKeys(t *testing.T) {
	enc := func(value []byte) string { return base64.RawURLEncoding.EncodeToString(value) }
	marshal := func(value interface{}) string { data,err:=json.Marshal(value); if err!=nil { t.Fatal(err) }; return string(data) }
	for _, field := range []string{"k","d","p","q","dp","dq","qi"} {
		for _, placement := range []string{"protected","unprotected","conflicting-headers"} {
			t.Run(field+"/"+placement,func(t *testing.T) {
				jwk := map[string]interface{}{"kty":"RSA","n":"AQAB","e":"AQAB",field:enc([]byte("quarry-private-error-sentinel"))}
				protected:=map[string]interface{}{"alg":"RS256"}
				header:=map[string]interface{}{}
				if placement=="protected" { protected["jwk"]=jwk } else { header["jwk"]=jwk }
				if placement=="conflicting-headers" { protected["jwk"]=map[string]interface{}{"kty":"RSA","n":"AQAB","e":"AQAB"} }
				p:=enc([]byte(marshal(protected))); payload:=enc([]byte("example")); sig:=enc([]byte("signature"))
				messages:=map[string]string{
					"flattened":marshal(map[string]interface{}{"protected":p,"header":header,"payload":payload,"signature":sig}),
					"general":marshal(map[string]interface{}{"payload":payload,"signatures":[]interface{}{map[string]interface{}{"protected":p,"header":header,"signature":sig}}}),
				}
				if placement=="protected" { messages["compact"]=p+"."+payload+"."+sig }
				for format,msg:=range messages {
					_,err:=ParseSigned(msg)
					if err==nil || !strings.Contains(err.Error(),"JWK contains private parameters") { t.Fatalf("%s: expected early private rejection, got %v",format,err) }
					if strings.Contains(err.Error(),"quarry-private-error-sentinel") || strings.Contains(err.Error(),enc([]byte("quarry-private-error-sentinel"))) { t.Fatal("private material leaked in error") }
				}
				// The same early restriction applies to JWE jwk and ephemeral epk.
				raw:=json.RawMessage(marshal(jwk))
				if _,err:=(rawHeader{headerEPK:&raw}).getEPK(); err==nil || !strings.Contains(err.Error(),"JWK contains private parameters") { t.Fatalf("epk: %v",err) }
				if _,err:=(rawHeader{headerJWK:&raw}).sanitized(); err==nil { t.Fatal("JWE jwk accepted private material") }
			})
		}
	}
}

func TestQuarryGeneralUnprotectedHeader(t *testing.T) {
	p:=base64.RawURLEncoding.EncodeToString([]byte(`{"alg":"RS256"}`))
	msg:=`{"payload":"ZXhhbXBsZQ","signatures":[{"protected":"`+p+`","header":{"kid":"from-unprotected"},"signature":"c2ln"}]}`
	obj,err:=ParseSigned(msg); if err!=nil { t.Fatal(err) }
	if obj.Signatures[0].Header.KeyID!="from-unprotected" || obj.Signatures[0].Unprotected.KeyID!="from-unprotected" { t.Fatal("general unprotected header not sanitized") }
}

func TestQuarryEncryptedPrivateHeaders(t *testing.T) {
	enc:=func(value string) string { return base64.RawURLEncoding.EncodeToString([]byte(value)) }
	sentinel:="cXVhcnJ5LXByaXZhdGUtZXJyb3Itc2VudGluZWw"
	protected:=enc(`{"alg":"dir","enc":"A256GCM","jwk":{"kty":"oct","k":"`+sentinel+`"}}`)
	for format,msg:=range map[string]string{
		"compact":protected+"..aXY.Y2lwaGVy.dGFn",
		"flattened":`{"protected":"`+protected+`","encrypted_key":"","iv":"aXY","ciphertext":"Y2lwaGVy","tag":"dGFn"}`,
		"general":`{"protected":"`+protected+`","recipients":[{"encrypted_key":""}],"iv":"aXY","ciphertext":"Y2lwaGVy","tag":"dGFn"}`,
	} {
		_,err:=ParseEncrypted(msg)
		if err==nil || !strings.Contains(err.Error(),"JWK contains private parameters") { t.Fatalf("%s: %v",format,err) }
		if strings.Contains(err.Error(),sentinel) || strings.Contains(err.Error(),"quarry-private-error-sentinel") { t.Fatalf("%s: JWE error leaks private header",format) }
	}
}

func TestQuarryCryptoRoundTrips(t *testing.T) {
	payload:=[]byte("quarry valid cryptographic round trip")
	signer,err:=NewSigner(SigningKey{Algorithm:RS256,Key:rsaTestKey},nil); if err!=nil { t.Fatal(err) }
	signed,err:=signer.Sign(payload); if err!=nil { t.Fatal(err) }
	parsed,err:=ParseSigned(signed.FullSerialize()); if err!=nil { t.Fatal(err) }
	plain,err:=parsed.Verify(&rsaTestKey.PublicKey); if err!=nil || string(plain)!=string(payload) { t.Fatalf("RSA round trip: %v",err) }
	encrypter,err:=NewEncrypter(A256GCM,Recipient{Algorithm:ECDH_ES,Key:&ecTestKey256.PublicKey},nil); if err!=nil { t.Fatal(err) }
	encrypted,err:=encrypter.Encrypt(payload); if err!=nil { t.Fatal(err) }
	decoded,err:=ParseEncrypted(encrypted.FullSerialize()); if err!=nil { t.Fatal(err) }
	plain,err=decoded.Decrypt(ecTestKey256); if err!=nil || string(plain)!=string(payload) { t.Fatalf("ECDH round trip: %v",err) }
}
