"""Private test CA/certificate generator, run only in Docker by production_rehearsal.py."""
import ipaddress
from datetime import UTC, datetime, timedelta
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID

folder = Path('/out')
now = datetime.now(UTC)
ca_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
ca_name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, 'Quarry local rehearsal CA')])
ca = (x509.CertificateBuilder().subject_name(ca_name).issuer_name(ca_name)
      .public_key(ca_key.public_key()).serial_number(x509.random_serial_number())
      .not_valid_before(now-timedelta(minutes=5)).not_valid_after(now+timedelta(days=2))
      .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
      .add_extension(x509.SubjectKeyIdentifier.from_public_key(ca_key.public_key()),critical=False)
      .add_extension(x509.AuthorityKeyIdentifier.from_issuer_public_key(ca_key.public_key()),critical=False)
      .add_extension(x509.KeyUsage(False,False,False,False,False,True,True,False,False),critical=True)
      .sign(ca_key, hashes.SHA256()))
key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
leaf = (x509.CertificateBuilder().subject_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME,'localhost')]))
        .issuer_name(ca_name).public_key(key.public_key()).serial_number(x509.random_serial_number())
        .not_valid_before(now-timedelta(minutes=5)).not_valid_after(now+timedelta(days=1))
        .add_extension(x509.BasicConstraints(ca=False,path_length=None),critical=True)
        .add_extension(x509.AuthorityKeyIdentifier.from_issuer_public_key(ca_key.public_key()),critical=False)
        .add_extension(x509.KeyUsage(True,False,True,False,False,False,False,False,False),critical=True)
        .add_extension(x509.ExtendedKeyUsage([ExtendedKeyUsageOID.SERVER_AUTH]),critical=False)
        .add_extension(x509.SubjectAlternativeName([x509.DNSName('localhost'),x509.DNSName('mailpit'),
                        x509.IPAddress(ipaddress.ip_address('127.0.0.1'))]),critical=False)
        .sign(ca_key,hashes.SHA256()))
(folder/'ca.pem').write_bytes(ca.public_bytes(serialization.Encoding.PEM))
(folder/'server.pem').write_bytes(leaf.public_bytes(serialization.Encoding.PEM))
(folder/'server.key').write_bytes(key.private_bytes(serialization.Encoding.PEM,
                                    serialization.PrivateFormat.PKCS8,serialization.NoEncryption()))
(folder/'server.key').chmod(0o600)
# CA private key is never persisted. Certificates/leaf key remain in ignored local storage.
