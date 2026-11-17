"""Reject malformed executable configuration before starting any child."""
from fractions import Fraction
import sys
import unittest
from unittest.mock import patch

from agent_retry_rodeo.process_agent import ProcessAgent


class ProcessConfigurationTests(unittest.TestCase):
    def test_argv_must_not_be_reinterpreted_as_characters_or_mapping_keys(self):
        commands = ['python', b'python', {'python': 'ignored'},
                    (x for x in ['python']), {'python'}, 42, None]
        for command in commands:
            with self.subTest(kind=type(command).__name__), patch('subprocess.Popen') as spawn:
                with self.assertRaisesRegex(ValueError, 'nonempty argument list or tuple'):
                    ProcessAgent(command)
                spawn.assert_not_called()

    def test_nul_in_an_argument_is_rejected_at_configuration_time(self):
        for command in [['python', 'a\0b'], ['py\0thon']]:
            with self.subTest(command=command), self.assertRaisesRegex(ValueError, 'nonempty argument list or tuple'):
                ProcessAgent(command)

    def test_invalid_timeout_has_consistent_value_error(self):
        for timeout in [True, False, '3', None, 1j, 10**1000]:
            with self.subTest(kind=type(timeout).__name__), patch('subprocess.Popen') as spawn:
                with self.assertRaisesRegex(ValueError, 'positive and finite'):
                    ProcessAgent([sys.executable], timeout)
                spawn.assert_not_called()

    def test_list_and_tuple_preserve_exact_arguments_and_snapshot_caller_list(self):
        arguments = [sys.executable, '-c', 'pass', 'two words']
        adapter = ProcessAgent(arguments)
        arguments[0] = 'changed'
        self.assertEqual(adapter.command, [sys.executable, '-c', 'pass', 'two words'])
        self.assertEqual(ProcessAgent(tuple(adapter.command)).command, adapter.command)

    def test_valid_real_timeouts_are_preserved(self):
        for timeout in [1, .25, Fraction(1, 2)]:
            with self.subTest(timeout=timeout):
                self.assertEqual(ProcessAgent([sys.executable], timeout).timeout, timeout)
