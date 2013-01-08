import textwrap
from netlib import http, odict
import tutils

from six.moves import cStringIO

def test_httperror():
    e = http.HttpError(404, "Not found")
    assert str(e)


def test_has_chunked_encoding():
    h = odict.ODictCaseless()
    assert not http.has_chunked_encoding(h)
    h["transfer-encoding"] = ["chunked"]
    assert http.has_chunked_encoding(h)


def test_read_chunked():
    s = cStringIO.StringIO("1\r\na\r\n0\r\n")
    tutils.raises("closed prematurely", http.read_chunked, 500, s, None)

    s = cStringIO.StringIO("1\r\na\r\n0\r\n\r\n")
    assert http.read_chunked(500, s, None) == "a"

    s = cStringIO.StringIO("\r\n\r\n1\r\na\r\n0\r\n\r\n")
    assert http.read_chunked(500, s, None) == "a"

    s = cStringIO.StringIO("\r\n")
    tutils.raises("closed prematurely", http.read_chunked, 500, s, None)

    s = cStringIO.StringIO("1\r\nfoo")
    tutils.raises("malformed chunked body", http.read_chunked, 500, s, None)

    s = cStringIO.StringIO("foo\r\nfoo")
    tutils.raises(http.HttpError, http.read_chunked, 500, s, None)

    s = cStringIO.StringIO("5\r\naaaaa\r\n0\r\n\r\n")
    tutils.raises("too large", http.read_chunked, 500, s, 2)


def test_request_connection_close():
    h = odict.ODictCaseless()
    assert http.request_connection_close((1, 0), h)
    assert not http.request_connection_close((1, 1), h)

    h["connection"] = ["keep-alive"]
    assert not http.request_connection_close((1, 1), h)

    h["connection"] = ["close"]
    assert http.request_connection_close((1, 1), h)


def test_response_connection_close():
    h = odict.ODictCaseless()
    assert http.response_connection_close((1, 1), h)

    h["content-length"] = [10]
    assert not http.response_connection_close((1, 1), h)

    h["connection"] = ["close"]
    assert http.response_connection_close((1, 1), h)


def test_read_http_body_response():
    h = odict.ODictCaseless()
    h["content-length"] = [7]
    s = cStringIO.StringIO("testing")
    assert http.read_http_body_response(s, h, None) == "testing"


    h = odict.ODictCaseless()
    s = cStringIO.StringIO("testing")
    assert not http.read_http_body_response(s, h, None)

    h = odict.ODictCaseless()
    h["connection"] = ["close"]
    s = cStringIO.StringIO("testing")
    assert http.read_http_body_response(s, h, None) == "testing"


def test_get_header_tokens():
    h = odict.ODictCaseless()
    assert http.get_header_tokens(h, "foo") == []
    h["foo"] = ["bar"]
    assert http.get_header_tokens(h, "foo") == ["bar"]
    h["foo"] = ["bar, voing"]
    assert http.get_header_tokens(h, "foo") == ["bar", "voing"]
    h["foo"] = ["bar, voing", "oink"]
    assert http.get_header_tokens(h, "foo") == ["bar", "voing", "oink"]


def test_read_http_body_request():
    h = odict.ODictCaseless()
    h["expect"] = ["100-continue"]
    r = cStringIO.StringIO("testing")
    w = cStringIO.StringIO()
    assert http.read_http_body_request(r, w, h, (1, 1), None) == ""
    assert "100 Continue" in w.getvalue()


def test_read_http_body():
    h = odict.ODictCaseless()
    s = cStringIO.StringIO("testing")
    assert http.read_http_body(500, s, h, False, None) == ""

    h["content-length"] = ["foo"]
    s = cStringIO.StringIO("testing")
    tutils.raises(http.HttpError, http.read_http_body, 500, s, h, False, None)

    h["content-length"] = [5]
    s = cStringIO.StringIO("testing")
    assert len(http.read_http_body(500, s, h, False, None)) == 5
    s = cStringIO.StringIO("testing")
    tutils.raises(http.HttpError, http.read_http_body, 500, s, h, False, 4)

    h = odict.ODictCaseless()
    s = cStringIO.StringIO("testing")
    assert len(http.read_http_body(500, s, h, True, 4)) == 4
    s = cStringIO.StringIO("testing")
    assert len(http.read_http_body(500, s, h, True, 100)) == 7

    h = odict.ODictCaseless()
    h["transfer-encoding"] = ["chunked"]
    s = cStringIO.StringIO("5\r\naaaaa\r\n0\r\n\r\n")
    assert http.read_http_body(500, s, h, True, 100) == "aaaaa"


def test_parse_http_protocol():
    assert http.parse_http_protocol("HTTP/1.1") == (1, 1)
    assert http.parse_http_protocol("HTTP/0.0") == (0, 0)
    assert not http.parse_http_protocol("HTTP/a.1")
    assert not http.parse_http_protocol("HTTP/1.a")
    assert not http.parse_http_protocol("foo/0.0")
    assert not http.parse_http_protocol("HTTP/x")


def test_parse_init_connect():
    assert http.parse_init_connect("CONNECT host.com:443 HTTP/1.0")
    assert not http.parse_init_connect("bogus")
    assert not http.parse_init_connect("GET host.com:443 HTTP/1.0")
    assert not http.parse_init_connect("CONNECT host.com443 HTTP/1.0")
    assert not http.parse_init_connect("CONNECT host.com:443 foo/1.0")
    assert not http.parse_init_connect("CONNECT host.com:foo HTTP/1.0")


def test_prase_init_proxy():
    u = "GET http://foo.com:8888/test HTTP/1.1"
    m, s, h, po, pa, httpversion = http.parse_init_proxy(u)
    assert m == "GET"
    assert s == "http"
    assert h == "foo.com"
    assert po == 8888
    assert pa == "/test"
    assert httpversion == (1, 1)

    assert not http.parse_init_proxy("invalid")
    assert not http.parse_init_proxy("GET invalid HTTP/1.1")
    assert not http.parse_init_proxy("GET http://foo.com:8888/test foo/1.1")


def test_parse_init_http():
    u = "GET /test HTTP/1.1"
    m, u, httpversion= http.parse_init_http(u)
    assert m == "GET"
    assert u == "/test"
    assert httpversion == (1, 1)

    assert not http.parse_init_http("invalid")
    assert not http.parse_init_http("GET invalid HTTP/1.1")
    assert not http.parse_init_http("GET /test foo/1.1")


class TestReadHeaders:
    def _read(self, data, verbatim=False):
        if not verbatim:
            data = textwrap.dedent(data)
            data = data.strip()
        s = cStringIO.StringIO(data)
        return http.read_headers(s)

    def test_read_simple(self):
        data = """
            Header: one
            Header2: two
            \r\n
        """
        h = self._read(data)
        assert h.lst == [["Header", "one"], ["Header2", "two"]]

    def test_read_multi(self):
        data = """
            Header: one
            Header: two
            \r\n
        """
        h = self._read(data)
        assert h.lst == [["Header", "one"], ["Header", "two"]]

    def test_read_continued(self):
        data = """
            Header: one
            \ttwo
            Header2: three
            \r\n
        """
        h = self._read(data)
        assert h.lst == [["Header", "one\r\n two"], ["Header2", "three"]]

    def test_read_continued_err(self):
        data = "\tfoo: bar\r\n"
        assert self._read(data, True) is None

    def test_read_err(self):
        data = """
            foo
        """
        assert self._read(data) is None


def test_read_response():
    def tst(data, method, limit):
        data = textwrap.dedent(data)
        r = cStringIO.StringIO(data)
        return  http.read_response(r, method, limit)

    tutils.raises("blank server response", tst, "", "GET", None)
    tutils.raises("invalid server response", tst, "foo", "GET", None)
    data = """
        HTTP/1.1 200 OK
    """
    assert tst(data, "GET", None) == ((1, 1), 200, 'OK', odict.ODictCaseless(), '')
    data = """
        HTTP/1.1 200
    """
    assert tst(data, "GET", None) == ((1, 1), 200, '', odict.ODictCaseless(), '')
    data = """
        HTTP/x 200 OK
    """
    tutils.raises("invalid http version", tst, data, "GET", None)
    data = """
        HTTP/1.1 xx OK
    """
    tutils.raises("invalid server response", tst, data, "GET", None)

    data = """
        HTTP/1.1 100 CONTINUE

        HTTP/1.1 200 OK
    """
    assert tst(data, "GET", None) == ((1, 1), 200, 'OK', odict.ODictCaseless(), '')

    data = """
        HTTP/1.1 200 OK
        Content-Length: 3

        foo
    """
    assert tst(data, "GET", None)[4] == 'foo'
    assert tst(data, "HEAD", None)[4] == ''

    data = """
        HTTP/1.1 200 OK
        \tContent-Length: 3

        foo
    """
    tutils.raises("invalid headers", tst, data, "GET", None)


def test_parse_url():
    assert not http.parse_url("")

    u = "http://foo.com:8888/test"
    s, h, po, pa = http.parse_url(u)
    assert s == "http"
    assert h == "foo.com"
    assert po == 8888
    assert pa == "/test"

    s, h, po, pa = http.parse_url("http://foo/bar")
    assert s == "http"
    assert h == "foo"
    assert po == 80
    assert pa == "/bar"

    s, h, po, pa = http.parse_url("http://foo")
    assert pa == "/"

    s, h, po, pa = http.parse_url("https://foo")
    assert po == 443

    assert not http.parse_url("https://foo:bar")
    assert not http.parse_url("https://foo:")

