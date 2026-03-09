# AWS Compliance Receipt
**Date:** March 4, 2026  
**System:** BoundState MIRA (AWS GovCloud)  
**Account:** `574823419003`  
**Regions Assessed:** `us-gov-west-1`, `us-gov-east-1`

## 1) Purpose
This manifest is the single compliance receipt for the March 4, 2026 data purge operation. It records:
- What data-bearing infrastructure artifacts were found
- Where they were found
- When deletion actions were executed
- Cryptographic hash of the post-deletion empty-state snapshot

## 2) Pre-Deletion Findings (What Was Found)
All identified artifacts were in `us-gov-west-1` unless explicitly noted.

1. PostgreSQL / RDS
- DB instance: `mira-prod-postgres` (engine: postgres, DB name: `mira_h2`)
- Automated RDS snapshots existed prior to final purge completion

2. Secrets / JSON-bearing config
- `mira/prod/config`
- `mira/prod/postgres`

3. Runtime / Logging
- ECS cluster: `mira-prod-cluster`
- ECS services: `mira-prod-backend`, `mira-prod-frontend`
- CloudWatch log groups were present during runtime
- VPC Flow Log existed: `fl-04339bcaf3d140021`

4. Container image stores
- ECR repositories: `mira`, `mira-backend`, `mira-frontend`

5. Not Found at time of assessment
- No S3 buckets
- No DynamoDB tables
- No EFS/FSx file systems
- No owned EBS volumes/snapshots
- No OpenSearch domains
- No RDS/Aurora resources in `us-gov-east-1`

## 3) Deletion Execution Timeline (When It Was Deleted)
Source: CloudTrail management events on March 4, 2026 (`us-gov-west-1`), timeline file linked in Section 5.

Key deletion/control events:
- `2026-03-04T15:18:57-06:00` `ModifyDBInstance` (deletion protection removed) for `mira-prod-postgres`
- `2026-03-04T15:18:58-06:00` `DeleteDBInstance` for `mira-prod-postgres`
- `2026-03-04T15:29:20-06:00` `DeleteSecret` for `mira/prod/config`
- `2026-03-04T15:29:22-06:00` `DeleteSecret` for `mira/prod/postgres`
- `2026-03-04T15:33:55-06:00` `DeleteFlowLogs` for `fl-04339bcaf3d140021`
- `2026-03-04T15:37:15-06:00` `DeleteService` for `mira-prod-backend`
- `2026-03-04T15:37:17-06:00` `DeleteService` for `mira-prod-frontend`
- `2026-03-04T15:37:20-06:00` `DeleteCluster` for `mira-prod-cluster`
- `2026-03-04T15:39:42-06:00` `DeleteRepository` for `mira`
- `2026-03-04T15:39:43-06:00` `DeleteRepository` for `mira-backend`
- `2026-03-04T15:39:45-06:00` `DeleteRepository` for `mira-frontend`
- Multiple `DeleteLogGroup` events executed during purge window

## 4) Post-Deletion Empty-State Hash (Compliance Fingerprint)
An empty-state snapshot was captured after purge completion and canonicalized for hashing.

- Snapshot file: `AWS_EMPTY_STATE_SNAPSHOT_2026-03-04.json`
- Hash algorithm: `SHA-256`
- Hash value:  
`1f865978f4a8722555a0f7b66542398de458bd5f457b3b8338c7a3aea9f26390`

Verification command:
```bash
sha256sum docs/AWS_EMPTY_STATE_SNAPSHOT_2026-03-04.json
```

Expected:
```text
1f865978f4a8722555a0f7b66542398de458bd5f457b3b8338c7a3aea9f26390  AWS_EMPTY_STATE_SNAPSHOT_2026-03-04.json
```

## 5) Evidence Artifacts
- `docs/AWS_DATA_PURGE_VERIFICATION_2026-03-04_FINAL.md`
- `docs/AWS_DB_DELETION_RECORD_2026-03-04.md`
- `docs/AWS_DELETE_EVENT_TIMELINE_2026-03-04.json`
- `docs/AWS_EMPTY_STATE_SNAPSHOT_2026-03-04.json`
- `docs/AWS_EMPTY_STATE_SNAPSHOT_2026-03-04.sha256`

## 6) Final Attestation
As of the empty-state capture timestamp on March 4, 2026, queried AWS data-bearing surfaces in scope were empty for this account in `us-gov-west-1` and `us-gov-east-1`, and deletion actions were recorded in CloudTrail management events.
