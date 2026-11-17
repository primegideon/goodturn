"""
Unit test suite for GoodTurn serverless microservices.
Compatible with standard library unittest and pytest.
"""

import json
import os
import sys
import unittest
from unittest.mock import MagicMock, patch

# Ensure src modules are discoverable
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src")))

from intake.app import generate_safety_pin, triage_with_bedrock
import intake.app as intake_app
import accept.app as accept_app
import verify.app as verify_app


class GoodTurnBackendTests(unittest.TestCase):

    def test_safety_pin_format(self):
        """Validates generated safety PIN adheres to GT-XXXX format."""
        pin = generate_safety_pin()
        self.assertTrue(pin.startswith("GT-"))
        digits = pin.split("-")[1]
        self.assertEqual(len(digits), 4)
        self.assertTrue(digits.isdigit())

    def test_triage_fallback_heuristics(self):
        """Validates heuristic classification when Bedrock is not reachable."""
        with patch("intake.app.bedrock_runtime.invoke_model", side_effect=Exception("Service unavailable")):
            medical_res = triage_with_bedrock("Need asthma inhaler prescription from pharmacy")
            self.assertEqual(medical_res["category"], "Medical")
            self.assertEqual(medical_res["urgency"], "Critical")

            grocery_res = triage_with_bedrock("Need drinking water bottles and bread")
            self.assertEqual(grocery_res["category"], "Groceries")
            self.assertEqual(grocery_res["urgency"], "Urgent")

            general_res = triage_with_bedrock("Help deliver document envelope")
            self.assertEqual(general_res["category"], "Supplies")
            self.assertEqual(general_res["urgency"], "Routine")

    def test_intake_missing_description(self):
        """Validates intake handler rejects empty descriptions."""
        event = {
            "body": json.dumps({"description": "", "district": "Osu"}),
            "requestContext": {"http": {"method": "POST"}},
        }
        response = intake_app.lambda_handler(event, None)
        self.assertEqual(response["statusCode"], 400)
        body = json.loads(response["body"])
        self.assertIn("error", body)

    def test_accept_not_found(self):
        """Validates accept handler returns 404 for non-existent request."""
        with patch.object(accept_app.dynamodb, "Table") as mock_table:
            mock_instance = MagicMock()
            mock_instance.get_item.return_value = {}
            mock_table.return_value = mock_instance

            event = {
                "pathParameters": {"requestId": "req-nonexistent"},
                "body": json.dumps({"volunteerId": "vol-123"}),
                "requestContext": {"http": {"method": "POST"}},
            }
            response = accept_app.lambda_handler(event, None)
            self.assertEqual(response["statusCode"], 404)

    def test_verify_pin_mismatch(self):
        """Validates verify handler rejects invalid PIN."""
        with patch.object(verify_app.dynamodb, "Table") as mock_table:
            mock_instance = MagicMock()
            mock_instance.get_item.return_value = {
                "Item": {
                    "requestId": "req-001",
                    "safetyPin": "GT-1234",
                    "status": "MATCHED",
                }
            }
            mock_table.return_value = mock_instance

            event = {
                "pathParameters": {"requestId": "req-001"},
                "body": json.dumps({"safetyPin": "GT-9999"}),
                "requestContext": {"http": {"method": "POST"}},
            }
            response = verify_app.lambda_handler(event, None)
            self.assertEqual(response["statusCode"], 403)

    def test_verify_pin_success(self):
        """Validates verify handler accepts correct PIN and marks completed."""
        with patch.object(verify_app.dynamodb, "Table") as mock_table:
            mock_instance = MagicMock()
            mock_instance.get_item.return_value = {
                "Item": {
                    "requestId": "req-001",
                    "safetyPin": "GT-1234",
                    "status": "MATCHED",
                    "verificationTaskToken": "test-token",
                }
            }
            mock_instance.update_item.return_value = {
                "Attributes": {
                    "requestId": "req-001",
                    "status": "COMPLETED",
                    "safetyPin": "GT-1234",
                }
            }
            mock_table.return_value = mock_instance

            with patch.object(verify_app.stepfunctions, "send_task_success") as mock_sfn:
                event = {
                    "pathParameters": {"requestId": "req-001"},
                    "body": json.dumps({"safetyPin": "GT-1234", "notes": "Handed over safely"}),
                    "requestContext": {"http": {"method": "POST"}},
                }
                response = verify_app.lambda_handler(event, None)
                self.assertEqual(response["statusCode"], 200)
                mock_sfn.assert_called_once()
                body = json.loads(response["body"])
                self.assertEqual(body["status"], "COMPLETED")


if __name__ == "__main__":
    unittest.main()
