

from datetime import timedelta
from unittest.mock import MagicMock, patch

import requests
from django.test import SimpleTestCase, TestCase, override_settings
from django.utils import timezone

from apps.admindashboardx.cheburcheck import probe_addresses
from apps.admindashboardx.models import ServerHealthState
from apps.admindashboardx.panel_health import exclude_panel_down_servers
from apps.admindashboardx.tasks import check_server_health
from bot.models import Server


class _Resp:
    def __init__(self, status_code=200, text="", json_data=None, lines=None):
        self.status_code = status_code
        self.text = text
        self._json = json_data
        self._lines = lines or []

    def json(self):
        if self._json is None:
            raise ValueError("no json")
        return self._json

    def iter_lines(self, decode_unicode=True):
        yield from self._lines

    def close(self):
        return None


def _sse(*events):
    lines = []
    for name, data in events:
        lines.extend([f"event: {name}", f"data: {data}", ""])
    return lines


@override_settings(
    CHEBURCHECK_API_TOKEN="test-token",
    CHEBURCHECK_API_BASE="https://cheburcheck.ru/api/v1",
)
class CheburcheckClientTests(SimpleTestCase):
    def _run(self, handler, ips):
        session = MagicMock()
        session.get.side_effect = handler
        with patch("apps.admindashboardx.cheburcheck.requests.Session", return_value=session):
            return probe_addresses(ips), session

    def test_missing_token_does_not_call_api(self):
        with override_settings(CHEBURCHECK_API_TOKEN=""):
            with patch("apps.admindashboardx.cheburcheck.requests.Session") as session_cls:
                result = probe_addresses(["1.1.1.1"])
        session_cls.assert_not_called()
        self.assertEqual(result["1.1.1.1"]["status"], "no_access")
        self.assertEqual(result["1.1.1.1"]["detail"], "нет доступа")

    def test_healthcheck_failure_is_no_access(self):
        def handler(url, **kwargs):
            if url.endswith("/healthcheck"):
                raise requests.ConnectionError("down")
            raise AssertionError(url)

        result, _session = self._run(handler, ["1.1.1.1", "8.8.8.8"])
        self.assertEqual(result["1.1.1.1"]["status"], "no_access")
        self.assertEqual(result["8.8.8.8"]["status"], "no_access")

    def test_empty_scanners_are_question(self):
        def handler(url, **kwargs):
            if url.endswith("/healthcheck"):
                return _Resp(200, text="OK")
            if url.endswith("/check"):
                return _Resp(200, json_data={"id": "signed id", "blocked": False})
            self.assertEqual(url, "https://cheburcheck.ru/api/v1/probe/signed%20id")
            self.assertEqual(kwargs["headers"]["Authorization"], "Bearer test-token")
            self.assertNotIn("test-token", url)
            self.assertNotIn("token=", url)
            return _Resp(200, lines=_sse(
                ("started", '{"online_probes": 1}'),
                ("done", '{"response_count": 0}'),
            ))

        result, _session = self._run(handler, ["1.1.1.1"])
        self.assertEqual(result["1.1.1.1"]["status"], "question")
        self.assertEqual(result["1.1.1.1"]["detail"], "нет ответа сканеров")

    def test_uncertain_only_is_question(self):
        def handler(url, **kwargs):
            if url.endswith("/healthcheck"):
                return _Resp(200, text="OK")
            if url.endswith("/check"):
                return _Resp(200, json_data={"id": "abc", "blocked": False})
            return _Resp(200, lines=_sse(
                ("result", '{"verdicts": ["uncertain"]}'),
                ("done", '{"response_count": 1}'),
            ))

        result, _session = self._run(handler, ["1.1.1.1"])
        self.assertEqual(result["1.1.1.1"]["status"], "question")
        self.assertEqual(result["1.1.1.1"]["detail"], "неясно")

    def test_block_verdict_is_down(self):
        def handler(url, **kwargs):
            if url.endswith("/healthcheck"):
                return _Resp(200, text="OK")
            if url.endswith("/check"):
                return _Resp(200, json_data={"id": "abc", "blocked": False})
            return _Resp(200, lines=_sse(
                ("result", '{"verdicts": ["ok"]}'),
                ("result", '{"verdicts": ["tspu_block", "sni_block"]}'),
                ("done", '{"response_count": 2}'),
            ))

        result, _session = self._run(handler, ["1.1.1.1"])
        self.assertEqual(result["1.1.1.1"]["status"], "down")
        self.assertEqual(result["1.1.1.1"]["detail"], "ТСПУ, SNI")

    def test_ok_verdict_is_ok(self):
        def handler(url, **kwargs):
            if url.endswith("/healthcheck"):
                return _Resp(200, text="OK")
            if url.endswith("/check"):
                return _Resp(200, json_data={"id": "abc", "blocked": False})
            return _Resp(200, lines=_sse(
                ("result", '{"verdicts": ["whitelist"]}'),
                ("done", '{"response_count": 1}'),
            ))

        result, _session = self._run(handler, ["1.1.1.1"])
        self.assertEqual(result["1.1.1.1"], {"status": "ok", "detail": "доступен"})

    def test_blocklist_without_scanners_is_down(self):
        def handler(url, **kwargs):
            if url.endswith("/healthcheck"):
                return _Resp(200, text="OK")
            if url.endswith("/check"):
                return _Resp(200, json_data={"id": "abc", "blocked": True})
            return _Resp(200, lines=_sse(("done", '{"response_count": 0}')))

        result, _session = self._run(handler, ["1.1.1.1"])
        self.assertEqual(result["1.1.1.1"]["status"], "down")
        self.assertEqual(result["1.1.1.1"]["detail"], "в списке блокировок")

    def test_auth_error_marks_remaining_addresses(self):
        def handler(url, **kwargs):
            if url.endswith("/healthcheck"):
                return _Resp(200, text="OK")
            if url.endswith("/check"):
                target = kwargs["params"]["target"]
                if target != "1.1.1.1":
                    raise AssertionError(target)
                return _Resp(401)
            raise AssertionError(url)

        result, _session = self._run(handler, ["1.1.1.1", "8.8.8.8"])
        self.assertEqual(result["1.1.1.1"]["status"], "no_access")
        self.assertEqual(result["8.8.8.8"]["status"], "no_access")

    def test_partial_results_survive_probe_timeout(self):
        class _SlowResp(_Resp):
            def iter_lines(self, decode_unicode=True):
                yield from _sse(("result", '{"verdicts": ["tspu_block"]}'))
                raise requests.Timeout("slow")

        def handler(url, **kwargs):
            if url.endswith("/healthcheck"):
                return _Resp(200, text="OK")
            if url.endswith("/check"):
                return _Resp(200, json_data={"id": "abc", "blocked": False})
            return _SlowResp(200)

        result, _session = self._run(handler, ["1.1.1.1"])
        self.assertEqual(result["1.1.1.1"]["status"], "down")
        self.assertEqual(result["1.1.1.1"]["detail"], "ТСПУ")

    def test_probe_timeout_is_question(self):
        def handler(url, **kwargs):
            if url.endswith("/healthcheck"):
                return _Resp(200, text="OK")
            if url.endswith("/check"):
                return _Resp(200, json_data={"id": "abc", "blocked": False})
            raise requests.Timeout("slow")

        result, _session = self._run(handler, ["1.1.1.1"])
        self.assertEqual(result["1.1.1.1"]["status"], "question")

    def test_duplicate_ip_is_checked_once(self):
        checks = []

        def handler(url, **kwargs):
            if url.endswith("/healthcheck"):
                return _Resp(200, text="OK")
            if url.endswith("/check"):
                checks.append(kwargs["params"]["target"])
                return _Resp(200, json_data={"id": None, "blocked": False})
            raise AssertionError(url)

        result, _session = self._run(handler, ["1.1.1.1", "1.1.1.1", " "])
        self.assertEqual(checks, ["1.1.1.1"])
        self.assertEqual(result["1.1.1.1"]["status"], "question")


class CheburcheckHealthTaskTests(SimpleTestCase):
    def test_main_health_task_does_not_report_chebur(self):
        payload = {
            "checked_at": "2026-11-23T12:00:00+00:00",
            "summary": {"servers": 1, "ok": 1, "down": 0, "ping_ok": 1, "ping_down": 0},
        }
        with patch("apps.admindashboardx.panel_health.collect_and_store", return_value=payload):
            result = check_server_health()
        self.assertNotIn("chebur_ok", result)

    def test_chebur_task_runs_separate_round(self):
        from apps.admindashboardx.tasks import check_cheburcheck

        with patch("apps.admindashboardx.chebur_job.run_chebur_round", return_value={"checked": 2}) as mocked:
            result = check_cheburcheck()
        mocked.assert_called_once_with()
        self.assertEqual(result["checked"], 2)


class Clock:
    def __init__(self):
        self.t = 0.0
        self.slept = []

    def monotonic(self):
        return self.t

    def sleep(self, seconds):
        self.slept.append(seconds)
        self.t += seconds


class CheburRoundTests(TestCase):
    def _server(self, ip, hosting="node"):
        return Server.objects.create(hosting=hosting, ip_address=ip, is_active=True)

    def test_checks_oldest_first_and_stops_before_next_window(self):
        from apps.admindashboardx.chebur_job import run_chebur_round

        never = self._server("10.0.0.3", "never")
        older = self._server("10.0.0.1", "older")
        fresh = self._server("10.0.0.2", "fresh")
        now = timezone.now()
        ServerHealthState.objects.create(
            server=older,
            channel=ServerHealthState.CHANNEL_CHEBUR,
            status="ok",
            detail="доступен",
            streak_started_at=now - timedelta(hours=2),
            last_checked_at=now - timedelta(hours=2),
        )
        ServerHealthState.objects.create(
            server=fresh,
            channel=ServerHealthState.CHANNEL_CHEBUR,
            status="ok",
            detail="доступен",
            streak_started_at=now,
            last_checked_at=now,
        )
        seen = []
        clock = Clock()

        def probe(ip):
            seen.append(ip)
            return {"status": "question", "detail": "нет ответа сканеров"}

        result = run_chebur_round(
            servers=[fresh, older, never],
            probe_one=probe,
            sleep=clock.sleep,
            monotonic=clock.monotonic,
            gap=40,
            window=40,
            buffer=40,
        )
        self.assertEqual(seen, ["10.0.0.3"])
        self.assertEqual(clock.slept, [])
        self.assertEqual(result["checked"], 1)
        self.assertEqual(result["skipped"], 2)
        state = ServerHealthState.objects.get(server=never, channel=ServerHealthState.CHANNEL_CHEBUR)
        self.assertEqual(state.status, "question")

    def test_gap_is_forty_seconds_between_nodes(self):
        from apps.admindashboardx.chebur_job import run_chebur_round

        first = self._server("10.1.0.1")
        second = self._server("10.1.0.2")
        clock = Clock()
        run_chebur_round(
            servers=[first, second],
            probe_one=lambda ip: {"status": "ok", "detail": "доступен"},
            sleep=clock.sleep,
            monotonic=clock.monotonic,
            gap=40,
            window=30 * 60,
            buffer=120,
        )
        self.assertEqual(clock.slept, [40])
        self.assertEqual(
            ServerHealthState.objects.filter(channel=ServerHealthState.CHANNEL_CHEBUR).count(),
            2,
        )

    def test_same_ip_is_one_request(self):
        from apps.admindashboardx.chebur_job import run_chebur_round

        first = self._server("10.2.0.1", "a")
        second = self._server("10.2.0.1", "b")
        seen = []

        def probe(ip):
            seen.append(ip)
            return {"status": "down", "detail": "ТСПУ"}

        run_chebur_round(
            servers=[first, second],
            probe_one=probe,
            sleep=lambda _seconds: None,
            monotonic=lambda: 0,
            gap=40,
            window=100,
            buffer=0,
        )
        self.assertEqual(seen, ["10.2.0.1"])
        self.assertEqual(
            ServerHealthState.objects.filter(status="down", channel=ServerHealthState.CHANNEL_CHEBUR).count(),
            2,
        )

    def test_api_error_stops_the_round(self):
        from apps.admindashboardx.chebur_job import run_chebur_round
        from apps.admindashboardx.cheburcheck import CheburcheckUnavailable

        first = self._server("10.3.0.1")
        second = self._server("10.3.0.2")
        seen = []

        def probe(ip):
            seen.append(ip)
            raise CheburcheckUnavailable("429")

        result = run_chebur_round(
            servers=[first, second],
            probe_one=probe,
            sleep=lambda _seconds: None,
            monotonic=lambda: 0,
            gap=40,
            window=300,
            buffer=0,
        )
        self.assertEqual(seen, ["10.3.0.1"])
        self.assertTrue(result["api_down"])
        self.assertEqual(result["skipped"], 1)
        self.assertEqual(
            ServerHealthState.objects.get(server=first, channel=ServerHealthState.CHANNEL_CHEBUR).status,
            "no_access",
        )
        self.assertFalse(
            ServerHealthState.objects.filter(server=second, channel=ServerHealthState.CHANNEL_CHEBUR).exists()
        )

    def test_preflight_failure_marks_every_node(self):
        from apps.admindashboardx.chebur_job import PreflightFailed, run_chebur_round

        first = self._server("10.4.0.1")
        second = self._server("10.4.0.2")
        with patch("apps.admindashboardx.chebur_job._LiveProbe", side_effect=PreflightFailed("down")):
            result = run_chebur_round(servers=[first, second])
        self.assertTrue(result["api_down"])
        self.assertEqual(result["no_access"], 2)
        self.assertEqual(
            ServerHealthState.objects.filter(status="no_access", channel=ServerHealthState.CHANNEL_CHEBUR).count(),
            2,
        )


class CheburcheckKeyIssueTests(TestCase):
    def test_chebur_down_does_not_exclude_server(self):
        server = Server.objects.create(hosting="kept", ip_address="10.9.9.1")
        now = timezone.now()
        ServerHealthState.objects.create(
            server=server,
            channel=ServerHealthState.CHANNEL_CHEBUR,
            status="down",
            detail="ТСПУ",
            streak_started_at=now,
            last_checked_at=now,
        )
        kept = exclude_panel_down_servers(Server.objects.filter(pk=server.pk))
        self.assertEqual(list(kept), [server])
