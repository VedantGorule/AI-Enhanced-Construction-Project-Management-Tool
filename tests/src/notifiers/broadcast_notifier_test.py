from __future__ import annotations

import os
import subprocess
import unittest
from unittest.mock import MagicMock
from unittest.mock import Mock
from unittest.mock import patch

import requests

from src.notifiers.broadcast_notifier import BroadcastNotifier
from src.notifiers.broadcast_notifier import main


class TestBroadcastNotifier(unittest.TestCase):

    def setUp(self):
        """
        Set up the BroadcastNotifier instance for each test.
        """
        self.notifier = BroadcastNotifier('http://localhost:8080/broadcast')

    @patch('src.notifiers.broadcast_notifier.requests.post')
    def test_broadcast_message_success(self, mock_post):
        """
        Test that a message is successfully broadcasted.
        """
        mock_post.return_value = Mock(status_code=200)
        message = 'Test broadcast message'
        result = self.notifier.broadcast_message(message)

        self.assertTrue(result)
        mock_post.assert_called_once_with(
            self.notifier.broadcast_url, json={'message': message},
        )

    @patch('src.notifiers.broadcast_notifier.requests.post')
    def test_broadcast_message_failure(self, mock_post):
        """
        Test that a failure in broadcasting the message is handled correctly.
        """
        mock_post.return_value = Mock(status_code=500)
        message = 'Test broadcast message'
        result = self.notifier.broadcast_message(message)

        self.assertFalse(result)
        mock_post.assert_called_once_with(
            self.notifier.broadcast_url, json={'message': message},
        )

    @patch('src.notifiers.broadcast_notifier.requests.post')
    def test_broadcast_message_exception(self, mock_post):
        """
        Test that an exception during the broadcast is handled correctly.
        """
        mock_post.side_effect = requests.exceptions.RequestException(
            'Network error',
        )

        message = 'Test broadcast message'
        result = self.notifier.broadcast_message(message)

        self.assertFalse(result)
        mock_post.assert_called_once_with(
            self.notifier.broadcast_url, json={'message': message},
        )

    @patch(
        'src.notifiers.broadcast_notifier.BroadcastNotifier.broadcast_message',
    )
    @patch('src.notifiers.broadcast_notifier.print')
    def test_main(
        self,
        mock_print,
        mock_broadcast_message,
    ):
        """
        Ensure broadcasts a message and prints the status.
        """
        mock_broadcast_message.return_value = True

        main()

        # Assert broadcast_message was called once
        mock_broadcast_message.assert_called_once_with(
            'Test broadcast message',
        )

        # Assert the print function was called with the expected output
        mock_print.assert_called_once_with('Broadcast status: True')

    @patch('requests.post')
    def test_main_as_script(self, mock_post: MagicMock) -> None:
        """
        Test running the broadcast_notifier.py script as the main program.
        """
        mock_response: MagicMock = MagicMock()
        mock_response.status_code = 200
        mock_post.return_value = mock_response

        # Get the absolute path to the broadcast_notifier.py script
        script_path = os.path.abspath(
            os.path.join(
                os.path.dirname(__file__),
                '../../../src/notifiers/broadcast_notifier.py',
            ),
        )

        # Run the script using subprocess
        result = subprocess.run(
            ['python', script_path],
            capture_output=True, text=True,
        )

        # Print stdout and stderr for debugging
        print('STDOUT:', result.stdout)
        print('STDERR:', result.stderr)

        # Assert that the script runs without errors
        self.assertEqual(
            result.returncode, 0,
            'Script exited with a non-zero status.',
        )


if __name__ == '__main__':
    unittest.main()
