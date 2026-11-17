"""
GoodTurn Civic Aid - Volunteer Acceptance Service
Handles volunteer acceptance of an errand, resumes Step Functions workflow
using task token, and transitions state to MATCHED.
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
    logger.info("Received acceptance event: %s", json.dumps(event))

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

        volunteer_id = body.get("volunteerId", "vol-default").strip()
        volunteer_name = body.get("volunteerName", "Civic Volunteer").strip()
        volunteer_phone = body.get("volunteerPhone", "").strip()

        if not request_id:
            return {
                "statusCode": 400,
                "headers": headers,
                "body": json.dumps({"error": "requestId path parameter is required"}),
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

        current_status = item.get("status")
        if current_status not in ["PENDING_MATCH", "OPEN"]:
            return {
                "statusCode": 409,
                "headers": headers,
                "body": json.dumps({
                    "error": f"Request {request_id} is not in an acceptable state (current: {current_status})"
                }),
            }

        match_task_token = item.get("matchTaskToken")
        now = datetime.now(timezone.utc).isoformat()

        # Resume Step Functions execution if task token exists
        if match_task_token:
            try:
                stepfunctions.send_task_success(
                    taskToken=match_task_token,
                    output=json.dumps({
                        "requestId": request_id,
                        "volunteerId": volunteer_id,
                        "volunteerName": volunteer_name,
                        "acceptedAt": now,
                    }),
                )
                logger.info("Resumed Step Functions task token for request %s", request_id)
            except ClientError as sfn_err:
                logger.warning(
                    "Could not send task success (token might have expired): %s",
                    str(sfn_err),
                )

        # Update DynamoDB record
        update_response = table.update_item(
            Key={"requestId": request_id},
            UpdateExpression="SET #s = :status, volunteerId = :vId, volunteerName = :vName, volunteerPhone = :vPhone, acceptedAt = :now, updatedAt = :now REMOVE matchTaskToken",
            ExpressionAttributeNames={"#s": "status"},
            ExpressionAttributeValues={
                ":status": "MATCHED",
                ":vId": volunteer_id,
                ":vName": volunteer_name,
                ":vPhone": volunteer_phone,
                ":now": now,
            },
            ReturnValues="ALL_NEW",
        )

        updated_item = update_response.get("Attributes", {})

        return {
            "statusCode": 200,
            "headers": headers,
            "body": json.dumps(updated_item),
        }

    except Exception as exc:
        logger.exception("Failed to accept errand request")
        return {
            "statusCode": 500,
            "headers": headers,
            "body": json.dumps({"error": "Internal server error", "details": str(exc)}),
        }
