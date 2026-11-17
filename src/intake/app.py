"""
GoodTurn Civic Aid - Ingest and AI Triage Service
Handles errand intake, automated triage via Amazon Bedrock,
persists requests to DynamoDB, and initiates Step Functions lifecycle.
"""

import json
import logging
import os
import random
import uuid
from datetime import datetime, timezone

import boto3
from botocore.exceptions import ClientError

logger = logging.getLogger()
logger.setLevel(logging.INFO)

dynamodb = boto3.resource("dynamodb")
stepfunctions = boto3.client("stepfunctions")
bedrock_runtime = boto3.client("bedrock-runtime", region_name="us-east-1")

REQUESTS_TABLE = os.environ.get("REQUESTS_TABLE")
STATE_MACHINE_ARN = os.environ.get("STATE_MACHINE_ARN")


def triage_with_bedrock(description: str) -> dict:
    """
    Analyzes natural language errand description using Amazon Bedrock
    to infer category, urgency level, and summary.
    Falls back to deterministic rule extraction if Bedrock invocation fails.
    """
    prompt = (
        "You are an emergency aid dispatch triage system. Analyze the following request "
        "and return a strictly valid JSON object with keys: category (one of: Medical, Groceries, Supplies, Other), "
        "urgency (one of: Critical, Urgent, Routine), and summary (concise description under 15 words).\n\n"
        f"Request description: {description}\n\nJSON output:"
    )

    try:
        payload = {
            "anthropic_version": "bedrock-2023-05-31",
            "max_tokens": 150,
            "messages": [
                {
                    "role": "user",
                    "content": [{"type": "text", "text": prompt}],
                }
            ],
            "temperature": 0.1,
        }
        response = bedrock_runtime.invoke_model(
            modelId="anthropic.claude-3-5-haiku-20241022-v1:0",
            body=json.dumps(payload),
            contentType="application/json",
            accept="application/json",
        )
        response_body = json.loads(response["body"].read().decode("utf-8"))
        text_content = response_body["content"][0]["text"].strip()
        parsed = json.loads(text_content)
        return {
            "category": parsed.get("category", "Supplies"),
            "urgency": parsed.get("urgency", "Urgent"),
            "summary": parsed.get("summary", description[:60]),
        }
    except Exception as exc:
        logger.warning("Bedrock invocation fell back to heuristic parsing: %s", str(exc))
        desc_lower = description.lower()
        if any(term in desc_lower for term in ["med", "pill", "prescription", "doctor", "hospital", "pharmacy"]):
            category = "Medical"
            urgency = "Critical"
        elif any(term in desc_lower for term in ["water", "food", "bread", "grocery", "rice"]):
            category = "Groceries"
            urgency = "Urgent"
        else:
            category = "Supplies"
            urgency = "Routine"

        return {
            "category": category,
            "urgency": urgency,
            "summary": description[:60],
        }


def generate_safety_pin() -> str:
    """Generates a four-digit verification PIN with GT prefix."""
    pin_digits = random.randint(1000, 9999)
    return f"GT-{pin_digits}"


def lambda_handler(event, context):
    logger.info("Received event: %s", json.dumps(event))

    headers = {
        "Content-Type": "application/json",
        "Access-Control-Allow-Origin": "*",
        "Access-Control-Allow-Methods": "POST, OPTIONS",
        "Access-Control-Allow-Headers": "*",
    }

    if event.get("requestContext", {}).get("http", {}).get("method") == "OPTIONS":
        return {"statusCode": 200, "headers": headers, "body": ""}

    try:
        raw_body = event.get("body", "{}")
        body = json.loads(raw_body) if isinstance(raw_body, str) else raw_body

        description = body.get("description", "").strip()
        district = body.get("district", "East Legon").strip()
        landmark = body.get("landmark", "").strip()
        requester_name = body.get("requesterName", "Anonymous").strip()
        requester_phone = body.get("phone", "").strip()
        requester_id = body.get("requesterId", str(uuid.uuid4()))

        if not description:
            return {
                "statusCode": 400,
                "headers": headers,
                "body": json.dumps({"error": "Description is required"}),
            }

        # Perform Bedrock AI triage
        triage_result = triage_with_bedrock(description)
        category = body.get("category") or triage_result["category"]
        urgency = body.get("urgency") or triage_result["urgency"]

        request_id = f"req-{uuid.uuid4().hex[:8]}"
        created_at = datetime.now(timezone.utc).isoformat()
        safety_pin = generate_safety_pin()

        item = {
            "requestId": request_id,
            "requesterId": requester_id,
            "requesterName": requester_name,
            "phone": requester_phone,
            "district": district,
            "landmark": landmark,
            "description": description,
            "category": category,
            "urgency": urgency,
            "summary": triage_result["summary"],
            "status": "PENDING_MATCH",
            "safetyPin": safety_pin,
            "createdAt": created_at,
            "updatedAt": created_at,
        }

        # Persist to DynamoDB
        table = dynamodb.Table(REQUESTS_TABLE)
        table.put_item(Item=item)
        logger.info("Persisted request %s to DynamoDB", request_id)

        # Trigger Step Functions execution
        if STATE_MACHINE_ARN:
            try:
                sfn_response = stepfunctions.start_execution(
                    stateMachineArn=STATE_MACHINE_ARN,
                    name=f"{request_id}-{int(datetime.now(timezone.utc).timestamp())}",
                    input=json.dumps({
                        "requestId": request_id,
                        "district": district,
                        "category": category,
                        "urgency": urgency,
                    }),
                )
                item["executionArn"] = sfn_response.get("executionArn")
                logger.info("Started Step Functions execution: %s", item["executionArn"])
            except ClientError as sfn_err:
                logger.error("Failed to start Step Functions execution: %s", str(sfn_err))

        return {
            "statusCode": 201,
            "headers": headers,
            "body": json.dumps(item),
        }

    except Exception as exc:
        logger.exception("Failed to process intake request")
        return {
            "statusCode": 500,
            "headers": headers,
            "body": json.dumps({"error": "Internal server error", "details": str(exc)}),
        }
