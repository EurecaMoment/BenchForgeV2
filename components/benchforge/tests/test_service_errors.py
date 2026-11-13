import unittest

from benchforge_backend.service import gallery_path, request_error_status


class ServiceErrorContracts(unittest.TestCase):
    def test_http_error_classes_keep_client_and_server_failures_distinct(self):
        self.assertEqual(request_error_status('POST', ValueError('invalid request')), 400)
        self.assertEqual(request_error_status('POST', KeyError('required field')), 400)
        self.assertEqual(request_error_status('GET', KeyError('missing run')), 404)
        self.assertEqual(request_error_status('GET', FileNotFoundError('missing artifact')), 404)
        self.assertEqual(request_error_status('POST', PermissionError('forbidden')), 403)
        self.assertEqual(request_error_status('POST', RuntimeError('database unavailable')), 500)

    def test_gallery_link_is_relative_and_uses_the_configured_request_origin(self):
        self.assertEqual(gallery_path('run 1'), '/gallery/run%201')


if __name__ == '__main__':
    unittest.main()
