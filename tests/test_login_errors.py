"""A security challenge is actionable and must not be called token expiry."""
import logging
import unittest
from unittest.mock import Mock, patch
import api.login as login
import api.request_header as headers
from view.main_window import UiMainWindow
from test_class_tasks import response


class LoginErrorTests(unittest.TestCase):
    def setUp(self):
        logging.disable(logging.CRITICAL)

    def verify(self, code, message):
        session = Mock(get=Mock(return_value=response(code=code, msg=message)))
        with patch.object(headers, 'set_token'), patch.object(headers, 'rqs_session', session):
            return login.verify_token('offline-placeholder')

    def test_security_challenge_has_its_own_status(self):
        self.assertEqual(self.verify(11003, '需安全验证！'), 8)

    def test_other_business_errors_are_not_called_expired(self):
        self.assertEqual(self.verify(10001, '参数错误'), 9)

    def test_explicit_expiry_keeps_legacy_expired_status(self):
        self.assertEqual(self.verify(11001, '登录已过期，请重新登录'), 1)

    def test_ui_security_status_tells_user_the_required_action(self):
        ui = Mock()
        UiMainWindow._on_login_result(ui, 8)
        text = ui.warn_info.setText.call_args.args[0]
        self.assertIn('安全验证', text)
        self.assertNotIn('过期', text)


if __name__ == '__main__':
    unittest.main()
