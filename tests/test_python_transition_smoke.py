import ssl
import unittest
import warnings

from examples.smoke_python_transition import BASE, GOLD, RECIPE
from keel.task_factory import environment_spec


class ControlTests(unittest.TestCase):
    def test_reference_fixture_constructs_socket_without_a_connection(self):
        namespace = {}
        exec(GOLD, namespace)
        wrapped = namespace['make_socket']()
        try:
            self.assertIsInstance(wrapped, ssl.SSLSocket)
        finally:
            wrapped.close()

    def test_base_fixture_follows_actual_interpreter_api_availability(self):
        namespace = {}
        exec(BASE, namespace)
        if not hasattr(ssl, 'wrap_socket'):
            with self.assertRaises(AttributeError):
                namespace['make_socket']()
        else:
            with warnings.catch_warnings():
                warnings.simplefilter('ignore', DeprecationWarning)
                wrapped = namespace['make_socket']()
            try:
                self.assertIsInstance(wrapped, ssl.SSLSocket)
            finally:
                wrapped.close()

    def test_control_uses_shared_factory_and_identical_dependencies(self):
        old, old_pins = environment_spec(RECIPE, 'old')
        new, new_pins = environment_spec(RECIPE, 'new')
        self.assertNotEqual(old, new)
        self.assertEqual(old_pins, new_pins)
