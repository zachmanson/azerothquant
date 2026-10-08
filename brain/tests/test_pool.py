"""The Scan Pool client (#122, ADR-0026): what leaves the PC, and how the Brain talks to the
Worker."""

import gzip
import json
import ssl
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from brain.config import Era
from brain.pool import (
    HttpPool,
    PoolAdmin,
    PoolBusy,
    PoolEntry,
    PoolError,
    PoolPage,
    strip_scan,
    windows_root_context,
)
from brain.scan import Scan


def test_stripping_leaves_nothing_that_identifies_the_player_and_every_item_key_as_it_was():
    raw = {
        "requestedAt": 1_790_000_000,
        "realm": "Classic Beta PvP",
        "faction": "Alliance",
        "character": "Kash-Patel",
        "droppedRows": 2,
        "firstUpdateAt": 1_790_000_003,
        "readAt": 1_790_000_009,
        "vendorPrices": {"2589": 13},
        "itemInfo": {"2589": {"quality": 1}},
        "listings": [
            {
                "itemString": "item:2589::::::::20:1490",
                "quantity": 20,
                "buyout": 2000,
                "timeLeft": 4,
                "own": True,
                "name": "Linen Cloth",
            },
            {
                "itemString": "item:9768::::::::60:71::1:1:12743",
                "quantity": 1,
                "buyout": 5000,
                "timeLeft": 2,
            },
        ],
    }

    stripped = strip_scan(raw)

    assert "character" not in stripped
    assert stripped["listings"] == [
        {"itemString": "item:2589:::::::::", "quantity": 20, "buyout": 2000, "timeLeft": 4},
        {
            "itemString": "item:9768:::::::::::1:1:12743",
            "quantity": 1,
            "buyout": 5000,
            "timeLeft": 2,
        },
    ]
    kept = ("requestedAt", "realm", "faction", "droppedRows", "firstUpdateAt", "readAt")
    for field in (*kept, "vendorPrices", "itemInfo"):
        assert stripped[field] == raw[field]
    # The player's own Scan, still in their Archive, is untouched.
    assert raw["character"] == "Kash-Patel" and raw["listings"][0]["own"] is True
    before = [(r.item_key, r.unit_buyout) for r in Scan.from_saved(raw).rows]
    assert [(r.item_key, r.unit_buyout) for r in Scan.from_saved(stripped).rows] == before


def test_stripping_a_packed_scan_hides_which_rows_were_the_players_own():
    # #144: own rows are the only tables left in a packed Scan, and they sit where the game
    # listed them. Stripped, every row is packed and sorted, so nothing marks them out.
    raw = {
        "requestedAt": 1_790_000_000,
        "realm": "Classic Beta PvP",
        "faction": "Alliance",
        "character": "Kash-Patel",
        "droppedRows": 1,
        "droppedItemIDs": [4306],
        "listings": [
            {
                "itemString": "item:9768::::::::20:1490::1:1:12743",
                "quantity": 1,
                "buyout": 5000,
                "timeLeft": 2,
                "own": True,
                "name": "Scouting Belt of Nature Protection",
            },
        ],
        "packedListings": "item:2589::::::::60:71,20,2000,4;item:2589::::::::60:71,5,600,3",
    }

    stripped = strip_scan(raw)

    assert stripped["listings"] == []
    assert stripped["packedListings"] == (
        "item:2589:::::::::,20,2000,4;item:2589:::::::::,5,600,3;"
        "item:9768:::::::::::1:1:12743,1,5000,2"
    )
    assert stripped["droppedItemIDs"] == [4306]
    assert raw["listings"][0]["own"] is True
    before = sorted((r.item_key, r.unit_buyout) for r in Scan.from_saved(raw).rows)
    assert sorted((r.item_key, r.unit_buyout) for r in Scan.from_saved(stripped).rows) == before


class _StubWorker(BaseHTTPRequestHandler):
    """Answers as the Worker in pool/README.md would, and remembers each request."""

    requests: list[tuple[str, str, dict, bytes]] = []
    status = 201
    error = "something went wrong"

    def do_POST(self):
        body = self.rfile.read(int(self.headers["Content-Length"]))
        self.requests.append(("POST", self.path, dict(self.headers), body))
        if self.path == "/keys":
            self._reply(self.status, {"name": json.loads(body)["name"], "key": "newkey"})
            return
        self._reply(self.status, {"id": "abc"})

    def do_DELETE(self):
        self.requests.append(("DELETE", self.path, dict(self.headers), b""))
        self._reply(self.status, {"name": "bob", "revoked": True})

    def do_GET(self):
        self.requests.append(("GET", self.path, dict(self.headers), b""))
        if self.path.startswith("/scans/"):
            data = gzip.compress(json.dumps({"requestedAt": T0}).encode())
            self.send_response(200)
            self.send_header("Content-Type", "application/gzip")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
            return
        self._reply(
            self.status,
            {
                "entries": [
                    {
                        "id": "abc",
                        "era": "beta",
                        "realm": "Classic Beta PvP",
                        "faction": "Alliance",
                        "requestedAt": T0,
                        "mine": True,
                    },
                    # An Era this Brain doesn't know is left out, not an error.
                    {
                        "id": "def",
                        "era": "future",
                        "realm": "r",
                        "faction": "f",
                        "requestedAt": T0,
                        "mine": False,
                    },
                ],
                "rolledBack": ["old"],
                "cursor": "7",  # the Worker sends it as a string
                "more": False,
            },
        )

    def _reply(self, status, payload):
        if status >= 400:
            payload = {"error": self.error}
        data = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, *args):
        pass


T0 = 1_790_000_000


@pytest.fixture
def worker():
    _StubWorker.requests = []
    _StubWorker.status = 201
    _StubWorker.error = "something went wrong"
    server = HTTPServer(("127.0.0.1", 0), _StubWorker)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.server_port}"
    server.shutdown()
    server.server_close()


def test_a_push_sends_the_scan_gzipped_with_its_market_in_headers(worker):
    raw = {"requestedAt": T0, "realm": "Classic Beta PvP", "faction": "Alliance", "listings": []}

    pool_id = HttpPool(worker, "k123").push(Era.BETA, raw)

    assert pool_id == "abc"
    [(method, path, headers, body)] = _StubWorker.requests
    assert (method, path) == ("POST", "/scans")
    assert headers["Authorization"] == "Bearer k123"
    assert headers["X-Scan-Era"] == "beta"
    assert headers["X-Scan-Realm"] == "Classic%20Beta%20PvP"
    assert headers["X-Scan-Faction"] == "Alliance"
    assert headers["X-Scan-Requested-At"] == str(T0)
    assert json.loads(gzip.decompress(body)) == raw


def test_a_push_percent_encodes_a_market_outside_latin_1(worker):
    raw = {"requestedAt": T0, "realm": "Пиратская бухта", "faction": "Орда", "listings": []}

    HttpPool(worker, "k").push(Era.LIVE, raw)

    [(_, _, headers, _)] = _StubWorker.requests
    assert headers["X-Scan-Realm"] == (
        "%D0%9F%D0%B8%D1%80%D0%B0%D1%82%D1%81%D0%BA%D0%B0%D1%8F%20%D0%B1%D1%83%D1%85%D1%82%D0%B0"
    )
    assert headers["X-Scan-Faction"] == "%D0%9E%D1%80%D0%B4%D0%B0"


def test_a_rate_limited_push_is_busy_not_failed(worker):
    _StubWorker.status = 429

    with pytest.raises(PoolBusy):
        HttpPool(worker, "k").push(Era.BETA, {"requestedAt": T0, "realm": "r", "faction": "f"})


@pytest.mark.parametrize("status", [401, 403, 500])
def test_a_refused_request_is_a_pool_error(worker, status):
    _StubWorker.status = status

    with pytest.raises(PoolError, match=str(status)):
        HttpPool(worker, "k").list_since(None)


def test_an_unreachable_pool_is_a_pool_error():
    with pytest.raises(PoolError):
        HttpPool("http://127.0.0.1:9", "k", timeout=2).list_since(None)


def test_listing_reads_the_index_page(worker):
    page = HttpPool(worker, "k").list_since(3)

    assert _StubWorker.requests[0][1] == "/scans?since=3"
    assert page == PoolPage(
        entries=[PoolEntry("abc", Era.BETA, "Classic Beta PvP", "Alliance", T0, mine=True)],
        rolled_back=["old"],
        cursor=7,
        more=False,
    )


def test_the_first_listing_asks_for_the_whole_index(worker):
    HttpPool(worker, "k").list_since(None)

    assert _StubWorker.requests[0][1] == "/scans"


def test_fetching_unzips_the_scan(worker):
    assert HttpPool(worker, "k").fetch("abc") == {"requestedAt": T0}
    assert _StubWorker.requests[0][1] == "/scans/abc"


def test_adding_a_member_key_sends_the_name_with_the_admin_secret(worker):
    key = PoolAdmin(worker, "s3cret").add_key("bob")

    assert key == "newkey"
    [(method, path, headers, body)] = _StubWorker.requests
    assert (method, path) == ("POST", "/keys")
    assert headers["Authorization"] == "Bearer s3cret"
    assert headers["Content-Type"] == "application/json"
    assert json.loads(body) == {"name": "bob"}


def test_revoking_a_member_key_deletes_it_by_name(worker):
    PoolAdmin(worker, "s3cret").revoke_key("bob the/2nd")

    [(method, path, headers, _)] = _StubWorker.requests
    assert (method, path) == ("DELETE", "/keys/bob%20the%2F2nd")
    assert headers["Authorization"] == "Bearer s3cret"


def test_a_taken_name_is_a_pool_error_with_the_worker_s_reason(worker):
    _StubWorker.status = 409
    _StubWorker.error = "name already taken"

    with pytest.raises(PoolError, match="409 name already taken"):
        PoolAdmin(worker, "s3cret").add_key("bob")


@pytest.mark.parametrize(
    "call",
    [lambda url: HttpPool(url, "k").list_since(None), lambda url: PoolAdmin(url, "s").add_key("n")],
)
def test_every_request_names_the_brain(worker, call):
    # Cloudflare turns away Python-urllib's own User-Agent with a 403 (error 1010).
    call(worker)

    [(_, _, headers, _)] = _StubWorker.requests
    assert headers["User-Agent"].startswith("azerothquant-brain")


# Two throwaway self-signed certificates, standing in for Windows' certificate stores.
ROOT_PEM = """-----BEGIN CERTIFICATE-----
MIIBfjCCASWgAwIBAgIUHURkLE0FhKZegjpOvAe3LWhlSnEwCgYIKoZIzj0EAwIw
FDESMBAGA1UEAwwJVGVzdCByb290MCAXDTI2MTAwMTAxMTk1N1oYDzIxMjYwOTA3
MDExOTU3WjAUMRIwEAYDVQQDDAlUZXN0IHJvb3QwWTATBgcqhkjOPQIBBggqhkjO
PQMBBwNCAAQb3zEFKmLBPLRAwD3tafHZcz6VprTBmHv0937BYw21ddkDb0rvVn4m
yTwZwLqO6nOlUChWKrBuhBAzRqtiHKmAo1MwUTAdBgNVHQ4EFgQU/NwkoO5W5PbB
IX81O6sa8pYuxucwHwYDVR0jBBgwFoAU/NwkoO5W5PbBIX81O6sa8pYuxucwDwYD
VR0TAQH/BAUwAwEB/zAKBggqhkjOPQQDAgNHADBEAiBRVJuoTRml9dRClvNM/azg
BsBjwwbIDGRVIZs7r8/ioAIgQkLyvq9dtYaR85EHNn1ITpjym8+GpRGBjT3IiHaQ
Iac=
-----END CERTIFICATE-----
"""
CA_PEM = """-----BEGIN CERTIFICATE-----
MIIBfDCCASGgAwIBAgIUChW/UdP0TxceaMrE13Gx8E35bPgwCgYIKoZIzj0EAwIw
EjEQMA4GA1UEAwwHVGVzdCBjYTAgFw0yNjEwMDEwMTE5NTdaGA8yMTI2MDkwNzAx
MTk1N1owEjEQMA4GA1UEAwwHVGVzdCBjYTBZMBMGByqGSM49AgEGCCqGSM49AwEH
A0IABFGbtjXSrjz4y6WxyRSQUGRtY3gooD8IWONaxduqUwngN8dVi5mSKByNRdLu
kEc07aigY4N24c8eMtt/5b8hR5ejUzBRMB0GA1UdDgQWBBScpXUlQ0/LYaFj//h4
kMkXm96KbjAfBgNVHSMEGDAWgBScpXUlQ0/LYaFj//h4kMkXm96KbjAPBgNVHRMB
Af8EBTADAQH/MAoGCCqGSM49BAMCA0kAMEYCIQCX7e2+EIARiZR1F4mnHDk17zM7
vuG8RIZuGsigeaFopwIhAO2ur/6EVXGr5HPmZSYo9haKqRgjI7VCo7y4OWtbXd17
-----END CERTIFICATE-----
"""
SERVER_AUTH = "1.3.6.1.5.5.7.3.1"


def _trusted_names(context: ssl.SSLContext) -> set[str]:
    return {
        dict(rdn[0] for rdn in cert["subject"])["commonName"] for cert in context.get_ca_certs()
    }


def test_on_windows_only_the_root_store_is_trusted():
    # Windows caches intermediates in the CA store, expired ones included. Python trusts that
    # store too, so an expired ISRG Root X2 cross-sign there failed every request to the
    # Worker (#124).
    stores = {
        "ROOT": [(ssl.PEM_cert_to_DER_cert(ROOT_PEM), "x509_asn", True)],
        "CA": [(ssl.PEM_cert_to_DER_cert(CA_PEM), "x509_asn", True)],
    }

    context = windows_root_context(lambda store: stores[store])

    assert _trusted_names(context) == {"Test root"}
    assert context.verify_mode == ssl.CERT_REQUIRED
    assert context.check_hostname


@pytest.mark.parametrize(
    "trust, trusted",
    [(True, True), ({SERVER_AUTH}, True), ({"1.3.6.1.5.5.7.3.3"}, False)],
)
def test_a_root_is_trusted_only_for_server_auth(trust, trusted):
    root = [(ssl.PEM_cert_to_DER_cert(ROOT_PEM), "x509_asn", trust)]

    context = windows_root_context(lambda store: root)

    assert _trusted_names(context) == ({"Test root"} if trusted else set())
