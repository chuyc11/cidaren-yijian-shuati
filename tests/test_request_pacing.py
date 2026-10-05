"""Bound transport stalls and keep automatic retries restricted to safe methods."""
import unittest
from unittest.mock import Mock, patch
import api.request_header as headers


class RequestPacingTests(unittest.TestCase):
    def test_default_has_separate_connection_and_read_deadlines(self):
        with patch.object(headers, '_orig_session_request') as request:
            headers._session_request_with_timeout(Mock(), 'GET', 'https://example.invalid')
        self.assertEqual(request.call_args.kwargs['timeout'], (5, 15))

    def test_explicit_timeout_remains_authoritative(self):
        with patch.object(headers, '_orig_session_request') as request:
            headers._session_request_with_timeout(Mock(), 'POST', 'https://example.invalid', timeout=45)
        self.assertEqual(request.call_args.kwargs['timeout'], 45)

    def test_transport_does_not_stack_three_retries_or_replay_post_status_errors(self):
        session = headers.requests.Session()
        headers.mount_retries(session)
        try:
            retry = session.get_adapter('https://').max_retries
            self.assertEqual(retry.total, 1)
            self.assertTrue(retry.is_retry('GET', 503))
            self.assertFalse(retry.is_retry('POST', 503))
            self.assertTrue(retry.respect_retry_after_header)
        finally:
            session.close()


if __name__ == '__main__':
    unittest.main()
