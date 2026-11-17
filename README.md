# GoodTurn

GoodTurn is a serverless, event-driven community mutual aid and emergency errand dispatch platform. It connects neighborhood volunteers with residents requiring immediate physical assistance, including prescription pickups, essential groceries, and local medical transit.

---

## Overview

Community aid initiatives often face logistical friction, relying on fragmented spreadsheets or noisy messaging groups where critical requests can be overlooked. GoodTurn provides an automated dispatch infrastructure that coordinates requests, volunteers, and physical delivery verification with end-to-end security and privacy.

Key capabilities include:
- Plain-language aid requests with automated categorization and urgency prioritization.
- Proximity-based volunteer dispatch and notification.
- Resilient asynchronous state machine orchestration for errand lifecycles.
- Envelope encryption protecting recipient contact details until acceptance.
- Physical delivery verification using one-time verification tokens.

---

## System Architecture

GoodTurn is implemented entirely with AWS serverless services, scaling down to zero idle resource consumption.

```
[Client Application]
         │
         ▼
[Amazon API Gateway] (HTTP API)
         │
         ▼
  [AWS Lambda] ──► [Amazon Bedrock] (Natural Language Triage)
         │
         ├──► [Amazon DynamoDB] (Request & Volunteer Records)
         │
         ▼
[AWS Step Functions] (Lifecycle Orchestration & Dispatch)
         │
         ├──► [Amazon SNS] (Volunteer Notifications)
         │
         └──► [Task Token Callback] (Volunteer Acceptance & Matching)
```

### AWS Services

- **Amazon Cognito**: User identity, role-based access control, and authentication.
- **Amazon API Gateway**: Managed HTTP endpoints for client ingress.
- **AWS Lambda**: Compute engine for request intake, matching logic, and completion verification.
- **Amazon Bedrock**: Automated natural language extraction, priority scoring, and PII redaction.
- **AWS Step Functions**: Resilient state machine managing errand dispatch, acceptance timeouts, and escalation.
- **Amazon DynamoDB**: On-demand NoSQL database for requests, helper profiles, and audit trails.
- **Amazon SNS**: Notification distribution to verified volunteer pools.
- **Amazon S3**: Static web asset hosting.

---

## Core Workflow

1. **Intake**: A resident submits an aid description and landmark location.
2. **Triage**: An intake Lambda invokes Amazon Bedrock to categorize the errand (e.g., Pharmacy, Groceries) and evaluate priority (e.g., Urgent, Standard).
3. **Dispatch**: AWS Step Functions initiates an orchestration workflow, recording the request as pending and alerting relevant neighborhood volunteers via SNS.
4. **Acceptance**: A volunteer accepts the task. The Step Functions execution resumes via task token callback, binding the volunteer to the errand and sharing encrypted handoff details.
5. **Verification**: Physical delivery is validated through a one-time safety verification code shared in person between the recipient and volunteer.

---

## Development Setup

### Prerequisites

- AWS CLI configured with valid credentials
- AWS SAM CLI installed
- Python 3.12 or later
- Node.js 18 or later

### Repository Structure

```
.
├── src/
│   ├── intake/         # Intake and triage handler
│   ├── accept/         # Volunteer acceptance handler
│   ├── verify/         # Delivery verification handler
│   └── status/         # Status and query handler
├── frontend/           # Web client application
├── template.yaml       # AWS SAM infrastructure definition
└── README.md
```

### Building and Deployment

Build the SAM application:

```bash
sam build
```

Deploy to AWS:

```bash
sam deploy --guided
```

---

## License

This project is licensed under the Apache License 2.0.
