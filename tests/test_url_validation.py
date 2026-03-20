"""Unit tests for SSRF URL validation utility."""

from app.core.url_validation import validate_url_for_ssrf


class TestValidateUrlForSsrf:
    """Tests for validate_url_for_ssrf()."""

    def test_rejects_non_http_scheme(self):
        ok, reason = validate_url_for_ssrf("ftp://example.com/path")
        assert not ok
        assert "scheme" in reason

    def test_rejects_file_scheme(self):
        ok, reason = validate_url_for_ssrf("file:///etc/passwd")
        assert not ok
        assert "scheme" in reason

    def test_rejects_empty_hostname(self):
        ok, reason = validate_url_for_ssrf("http:///path")
        assert not ok
        assert "hostname" in reason.lower()

    def test_rejects_loopback_ipv4(self):
        ok, reason = validate_url_for_ssrf("http://127.0.0.1/api")
        assert not ok
        assert "blocked" in reason.lower()

    def test_rejects_private_10_range(self):
        ok, reason = validate_url_for_ssrf("http://10.0.0.1/internal")
        assert not ok
        assert "blocked" in reason.lower()

    def test_rejects_private_172_range(self):
        ok, reason = validate_url_for_ssrf("http://172.16.0.1/internal")
        assert not ok
        assert "blocked" in reason.lower()

    def test_rejects_private_192_range(self):
        ok, reason = validate_url_for_ssrf("http://192.168.1.1/internal")
        assert not ok
        assert "blocked" in reason.lower()

    def test_rejects_link_local(self):
        ok, reason = validate_url_for_ssrf("http://169.254.169.254/metadata")
        assert not ok
        assert "blocked" in reason.lower()

    def test_rejects_unresolvable_hostname(self):
        ok, reason = validate_url_for_ssrf("https://this-host-definitely-does-not-exist-xyz123.invalid")
        assert not ok
        assert "resolve" in reason.lower()

    def test_accepts_valid_public_https(self):
        ok, reason = validate_url_for_ssrf("https://www.google.com")
        assert ok
        assert reason == ""

    def test_accepts_valid_public_http(self):
        ok, reason = validate_url_for_ssrf("http://www.google.com")
        assert ok
        assert reason == ""

    def test_rejects_localhost_hostname(self):
        ok, reason = validate_url_for_ssrf("http://localhost/api")
        assert not ok
        assert "blocked" in reason.lower()

    def test_rejects_empty_string(self):
        ok, reason = validate_url_for_ssrf("")
        assert not ok

    def test_rejects_javascript_scheme(self):
        ok, reason = validate_url_for_ssrf("javascript:alert(1)")
        assert not ok
        assert "scheme" in reason
