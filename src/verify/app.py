"""
GoodTurn Civic Aid - Physical Delivery Safety Verification Service
Validates verbal Safety PIN (#GT-XXXX) exchanged upon physical handoff,
completes Step Functions execution, and records completion in DynamoDB.
"""

import json
import logging
import os
from datetime import datetime, timezone

import boto3
from botocore.exceptions import ClientError

logger = logging.getLogger()
logger.setLevel(logging.INFO)

dynamodb = boto3.resource("dynamodb")
stepfunctions = boto3.client("stepfunctions")
REQUESTS_TABLE = os.environ.get("REQUESTS_TABLE")


def lambda_handler(event, context):
    logger.info("Received verification event: %s", json.dumps(event))

    headers = {
        "Content-Type": "application/json",
        "Access-Control-Allow-Origin": "*",
        "Access-Control-Allow-Methods": "POST, OPTIONS",
        "Access-Control-Allow-Headers": "*",
    }

    if event.get("requestContext", {}).get("http", {}).get("method") == "OPTIONS":
        return {"statusCode": 200, "headers": headers, "body": ""}

    try:
        path_params = event.get("pathParameters") or {}
        request_id = path_params.get("requestId")

        raw_body = event.get("body", "{}")
        body = json.loads(raw_body) if isinstance(raw_body, str) else raw_body

        submitted_pin = body.get("safetyPin", "").strip().upper()
        notes = body.get("notes", "").strip()

        if not request_id or not submitted_pin:
            return {
                "statusCode": 400,
                "headers": headers,
                "body": json.dumps({"error": "requestId and safetyPin are required"}),
            }

        table = dynamodb.Table(REQUESTS_TABLE)
        response = table.get_item(Key={"requestId": request_id})
        item = response.get("Item")

        if not item:
            return {
                "statusCode": 404,
                "headers": headers,
                "body": json.dumps({"error": f"Request {request_id} not found"}),
            }

        stored_pin = item.get("safetyPin", "").strip().upper()
        # Allow validation with or without GT- prefix
        clean_submitted = submitted_pin.replace("GT-", "").replace("#", "")
        clean_stored = stored_pin.replace("GT-", "").replace("#", "")

        if clean_submitted != clean_stored:
            logger.warning("PIN mismatch for %s: submitted %s", request_id, submitted_pin)
            return {
                "statusCode": 403,
                "headers": headers,
                "body": json.dumps({"error": "Invalid verification PIN. Verification failed."}),
            }

        verification_task_token = item.get("verificationTaskToken")
        now = datetime.now(timezone.utc).isoformat()

        # Resume Step Functions execution to complete state machine
        if verification_task_token:
            try:
                stepfunctions.send_task_success(
                    taskToken=verification_task_token,
                    output=json.dumps({
                        "requestId": request_id,
                        "status": "COMPLETED",
                        "completedAt": now,
                    }),
                )
                logger.info("Step Functions verification completed for %s", request_id)
            except ClientError as sfn_err:
                logger.warning("Step Functions send_task_success warning: %s", str(sfn_err))

        # Update DynamoDB status to COMPLETED
        update_response = table.update_item(
            Key={"requestId": request_id},
            UpdateExpression="SET #s = :status, completedAt = :now, updatedAt = :now, completionNotes = :notes REMOVE verificationTaskToken",
            ExpressionAttributeNames={"#s": "status"},
            ExpressionAttributeValues={
                ":status": "COMPLETED",
                ":now": now,
                ":notes": notes,
            },
            ReturnValues="ALL_NEW",
        )

        return {
            "statusCode": 200,
            "headers": headers,
            "body": json.dumps(update_response.get("Attributes", {})),
        }

    except Exception as exc:
        logger.exception("Failed to verify delivery")
        return {
            "statusCode": 500,
            "headers": headers,
            "body": json.dumps({"error": "Internal server error", "details": str(exc)}),
        }
