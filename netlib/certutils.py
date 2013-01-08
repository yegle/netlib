import os, ssl, hashlib, socket, time, datetime, tempfile, shutil
from pyasn1.type import univ, constraint, char, namedtype, tag
from pyasn1.codec.der.decoder import decode
from pyasn1.error import PyAsn1Error
import OpenSSL
import netlib

CERT_SLEEP_TIME = 1
CERT_EXPIRY = str(365 * 3)


def create_ca():
    key = OpenSSL.crypto.PKey()
    key.generate_key(OpenSSL.crypto.TYPE_RSA, 1024)
    ca = OpenSSL.crypto.X509()
    ca.set_serial_number(int(time.time()*10000))
    ca.set_version(2)
    ca.get_subject().CN = "mitmproxy"
    ca.get_subject().O = "mitmproxy"
    ca.gmtime_adj_notBefore(0)
    ca.gmtime_adj_notAfter(24 * 60 * 60 * 720)
    ca.set_issuer(ca.get_subject())
    ca.set_pubkey(key)
    ca.add_extensions([
      OpenSSL.crypto.X509Extension("basicConstraints", True,
                                   "CA:TRUE"),
      OpenSSL.crypto.X509Extension("nsCertType", True,
                                   "sslCA"),
      OpenSSL.crypto.X509Extension("extendedKeyUsage", True,
                                    "serverAuth,clientAuth,emailProtection,timeStamping,msCodeInd,msCodeCom,msCTLSign,msSGC,msEFS,nsSGC"
                                    ),
      OpenSSL.crypto.X509Extension("keyUsage", False,
                                   "keyCertSign, cRLSign"),
      OpenSSL.crypto.X509Extension("subjectKeyIdentifier", False, "hash",
                                   subject=ca),
      ])
    ca.sign(key, "sha1")
    return key, ca


def dummy_ca(path):
    dirname = os.path.dirname(path)
    if not os.path.exists(dirname):
        os.makedirs(dirname)
    if path.endswith(".pem"):
        basename, _ = os.path.splitext(path)
        basename = os.path.basename(basename)
    else:
        basename = os.path.basename(path)

    key, ca = create_ca()

    # Dump the CA plus private key
    f = open(path, "w")
    f.write(OpenSSL.crypto.dump_privatekey(OpenSSL.crypto.FILETYPE_PEM, key))
    f.write(OpenSSL.crypto.dump_certificate(OpenSSL.crypto.FILETYPE_PEM, ca))
    f.close()

    # Dump the certificate in PEM format
    f = open(os.path.join(dirname, basename + "-cert.pem"), "w")
    f.write(OpenSSL.crypto.dump_certificate(OpenSSL.crypto.FILETYPE_PEM, ca))
    f.close()

    # Create a .cer file with the same contents for Android
    f = open(os.path.join(dirname, basename + "-cert.cer"), "w")
    f.write(OpenSSL.crypto.dump_certificate(OpenSSL.crypto.FILETYPE_PEM, ca))
    f.close()

    # Dump the certificate in PKCS12 format for Windows devices
    f = open(os.path.join(dirname, basename + "-cert.p12"), "w")
    p12 = OpenSSL.crypto.PKCS12()
    p12.set_certificate(ca)
    p12.set_privatekey(key)
    f.write(p12.export())
    f.close()
    return True


def dummy_cert(fp, ca, commonname, sans):
    """
        Generates and writes a certificate to fp.

        ca: Path to the certificate authority file, or None.
        commonname: Common name for the generated certificate.
        sans: A list of Subject Alternate Names.

        Returns cert path if operation succeeded, None if not.
    """
    ss = []
    for i in sans:
        ss.append("DNS: %s"%i)
    ss = ", ".join(ss)

    raw = file(ca, "r").read()
    ca = OpenSSL.crypto.load_certificate(OpenSSL.crypto.FILETYPE_PEM, raw)
    key = OpenSSL.crypto.load_privatekey(OpenSSL.crypto.FILETYPE_PEM, raw)

    req = OpenSSL.crypto.X509Req()
    subj = req.get_subject()
    subj.CN = commonname
    req.set_pubkey(ca.get_pubkey())
    req.sign(key, "sha1")
    if ss:
        req.add_extensions([OpenSSL.crypto.X509Extension("subjectAltName", True, ss)])

    cert = OpenSSL.crypto.X509()
    cert.gmtime_adj_notBefore(-3600)
    cert.gmtime_adj_notAfter(60 * 60 * 24 * 30)
    cert.set_issuer(ca.get_subject())
    cert.set_subject(req.get_subject())
    cert.set_serial_number(int(time.time()*10000))
    if ss:
        cert.add_extensions([OpenSSL.crypto.X509Extension("subjectAltName", True, ss)])
    cert.set_pubkey(req.get_pubkey())
    cert.sign(key, "sha1")

    fp.write(OpenSSL.crypto.dump_certificate(OpenSSL.crypto.FILETYPE_PEM, cert))
    fp.close()



class CertStore:
    """
        Implements an on-disk certificate store.
    """
    def __init__(self, certdir=None):
        """
            certdir: The certificate store directory. If None, a temporary
            directory will be created, and destroyed when the .cleanup() method
            is called.
        """
        if certdir:
            self.remove = False
            self.certdir = certdir
        else:
            self.remove = True
            self.certdir = tempfile.mkdtemp(prefix="certstore")

    def check_domain(self, commonname):
        try:
            commonname.decode("idna")
            commonname.decode("ascii")
        except:
            return False
        if ".." in commonname:
            return False
        if "/" in commonname:
            return False
        return True

    def get_cert(self, commonname, sans, cacert=False):
        """
            Returns the path to a certificate.

            commonname: Common name for the generated certificate. Must be a
            valid, plain-ASCII, IDNA-encoded domain name.

            sans: A list of Subject Alternate Names.

            cacert: An optional path to a CA certificate. If specified, the
            cert is created if it does not exist, else return None.

            Return None if the certificate could not be found or generated.
        """
        if not self.check_domain(commonname):
            return None
        certpath = os.path.join(self.certdir, commonname + ".pem")
        if os.path.exists(certpath):
            return certpath
        elif cacert:
            f = open(certpath, "w")
            dummy_cert(f, cacert, commonname, sans)
            return certpath

    def cleanup(self):
        if self.remove:
            shutil.rmtree(self.certdir)


class _GeneralName(univ.Choice):
    # We are only interested in dNSNames. We use a default handler to ignore
    # other types.
    componentType = namedtype.NamedTypes(
        namedtype.NamedType('dNSName', char.IA5String().subtype(
                implicitTag=tag.Tag(tag.tagClassContext, tag.tagFormatSimple, 2)
            )
        ),
    )


class _GeneralNames(univ.SequenceOf):
    componentType = _GeneralName()
    sizeSpec = univ.SequenceOf.sizeSpec + constraint.ValueSizeConstraint(1, 1024)


class SSLCert:
    def __init__(self, cert):
        """
            Returns a (common name, [subject alternative names]) tuple.
        """
        self.x509 = cert

    @classmethod
    def from_pem(klass, txt):
        x509 = OpenSSL.crypto.load_certificate(OpenSSL.crypto.FILETYPE_PEM, txt)
        return klass(x509)

    @classmethod
    def from_der(klass, der):
        pem = ssl.DER_cert_to_PEM_cert(der)
        return klass.from_pem(pem)

    def to_pem(self):
        return OpenSSL.crypto.dump_certificate(OpenSSL.crypto.FILETYPE_PEM, self.x509)

    def digest(self, name):
        return self.x509.digest(name)

    @property
    def issuer(self):
        return self.x509.get_issuer().get_components()

    @property
    def notbefore(self):
        t = self.x509.get_notBefore()
        return datetime.datetime.strptime(t, "%Y%m%d%H%M%SZ")

    @property
    def notafter(self):
        t = self.x509.get_notAfter()
        return datetime.datetime.strptime(t, "%Y%m%d%H%M%SZ")

    @property
    def has_expired(self):
        return self.x509.has_expired()

    @property
    def subject(self):
        return self.x509.get_subject().get_components()

    @property
    def serial(self):
        return self.x509.get_serial_number()

    @property
    def keyinfo(self):
        pk = self.x509.get_pubkey()
        types = {
            OpenSSL.crypto.TYPE_RSA: "RSA",
            OpenSSL.crypto.TYPE_DSA: "DSA",
        }
        return (
            types.get(pk.type(), "UNKNOWN"),
            pk.bits()
        )

    @property
    def cn(self):
        cn = None
        for i in self.subject:
            if i[0] == "CN":
                cn = i[1]
        return cn

    @property
    def altnames(self):
        altnames = []
        for i in range(self.x509.get_extension_count()):
            ext = self.x509.get_extension(i)
            if ext.get_short_name() == "subjectAltName":
                try:
                    dec = decode(ext.get_data(), asn1Spec=_GeneralNames())
                except PyAsn1Error:
                    continue
                for i in dec[0]:
                    altnames.append(i[0].asOctets())
        return altnames


def get_remote_cert(host, port, sni):
    c = netlib.tcp.TCPClient(host, port)
    c.connect()
    c.convert_to_ssl(sni=sni)
    return c.cert
