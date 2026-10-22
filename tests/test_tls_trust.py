"""Offline regression check for the default CA bundle used by Requests."""

import hashlib
import ssl
import unittest

from requests.utils import DEFAULT_CA_BUNDLE_PATH


# Root certificate SHA-256 fingerprints from the incident's published inventory:
# https://emudhra.we-have-a-problem.com/roots.json
# Include the AAA cross-signing path as well as eMudhra's own roots.
AFFECTED_ROOTS = {
    "7DD78D5F4F13459A83DFF9ABBBA62EDBAF6F2D102BF257FD712F4D9F2746ED8D": "emSign Root TLS CA - G3",
    "F2EDAAFF3D9B701FB4D14C9F285F8C0BAD90FC3BCC1FA07D47F4718EDABA34A5": "emSign Root CS CA - G3",
    "D7A7A0FB5D7E2731D771E9484EBCDEF71D5F0C3E0A2948782BC83EE0EA699EF4": "AAA Certificate Services",
    "86A1ECBA089C4A8D3BBE2734C612BA341D813E043CF9E8A862CD5C57A36BBE6B": "emSign ECC Root CA - G3",
}


class CertificateTrustTests(unittest.TestCase):
    def test_requests_default_bundle_excludes_affected_roots(self):
        # Load only Requests' bundle, without adding the OS trust store.
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        context.load_verify_locations(cafile=DEFAULT_CA_BUNDLE_PATH)
        certificates = context.get_ca_certs(binary_form=True)
        self.assertTrue(certificates, "Requests' CA bundle must not be empty")
        fingerprints = {
            hashlib.sha256(certificate).hexdigest().upper()
            for certificate in certificates
        }
        affected = [
            name for fingerprint, name in AFFECTED_ROOTS.items()
            if fingerprint in fingerprints
        ]
        self.assertEqual(
            affected, [],
            "Update this environment with python -m pip install --upgrade -r requirements.txt; "
            f"Requests still trusts affected roots: {affected}",
        )


if __name__ == "__main__":
    unittest.main()
