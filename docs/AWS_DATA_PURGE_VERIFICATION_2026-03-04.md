# AWS Data Purge Verification (2026-03-04)

- Generated: 2026-03-04 21:32:03 UTC
- Account: 574823419003 (GovCloud)
- Regions checked: us-gov-west-1, us-gov-east-1
- Evidence format: timestamped CLI snapshots (headless terminal environment)

## 1) RDS / Aurora State

### Region: us-gov-west-1
Timestamp: 2026-03-04 21:32:03 UTC

DB instances:
```json
[]
```
DB clusters:
```json
[]
```
Manual DB snapshots:
```json
[]
```
Automated DB snapshots:
```json
[]
```
Manual cluster snapshots:
```json
[]
```
Automated cluster snapshots:
```json
[]
```
DB instance automated backups:
```json
[]
```

### Region: us-gov-east-1
Timestamp: 2026-03-04 21:32:14 UTC

DB instances:
```json
[]
```
DB clusters:
```json
[]
```
Manual DB snapshots:
```json
[]
```
Automated DB snapshots:
```json
[]
```
Manual cluster snapshots:
```json
[]
```
Automated cluster snapshots:
```json
[]
```
DB instance automated backups:
```json
[]
```

## 2) S3 Buckets / Objects
Timestamp: 2026-03-04 21:32:24 UTC
```json
{
    "Buckets": [],
    "Owner": {
        "ID": "72d141c900281c54b16fb86a16314167e15ff5104e99daccbcb05ea2d409c113"
    },
    "Prefix": null
}
```

## 3) CloudWatch Logs

### Region: us-gov-west-1
Timestamp: 2026-03-04 21:32:25 UTC
```json
[
    "/aws/ecs/containerinsights/mira-prod-cluster/performance",
    "/vpc/mira-prod-flow-logs"
]
```

### Region: us-gov-east-1
Timestamp: 2026-03-04 21:32:27 UTC
```json
[]
```

## 4) Secrets Manager (JSON-bearing secrets)

### Region: us-gov-west-1
Timestamp: 2026-03-04 21:32:28 UTC
```json
[]
```

### Region: us-gov-east-1
Timestamp: 2026-03-04 21:32:30 UTC
```json
[]
```

## 5) DynamoDB

### Region: us-gov-west-1
Timestamp: 2026-03-04 21:32:32 UTC
```json
{
    "TableNames": []
}
```

### Region: us-gov-east-1
Timestamp: 2026-03-04 21:32:33 UTC
```json
{
    "TableNames": []
}
```

## 6) Persistent Storage Surfaces (FAISS/docker-volume relevant)

### Region: us-gov-west-1
Timestamp: 2026-03-04 21:32:35 UTC
EFS:
```json
[]
```
FSx:
```json
[]
```
EBS volumes:
```json
[]
```
EBS snapshots (owned):
```json
[]
```

### Region: us-gov-east-1
Timestamp: 2026-03-04 21:32:41 UTC
EFS:
```json
[]
```
FSx:
```json
[]
```
EBS volumes:
```json
[]
```
EBS snapshots (owned):
```json
[]
```

## 7) Search/Cache/Data Warehousing Surfaces

### Region: us-gov-west-1
Timestamp: 2026-03-04 21:32:48 UTC
OpenSearch:
```json
{
    "DomainNames": []
}
```
ElastiCache:
```json
[]
```
Redshift:
```json
[]
```
DocDB:
```json
[]
```
Neptune:
```json
[]
```

### Region: us-gov-east-1
Timestamp: 2026-03-04 21:32:56 UTC
OpenSearch:
```json
{
    "DomainNames": []
}
```
ElastiCache:
```json
[]
```
Redshift:
```json
[]
```
DocDB:
```json
[]
```
Neptune:
```json
[]
```

## 8) ECS Runtime / Volume Check
Timestamp: 2026-03-04 21:33:03 UTC
Services:
```json
[
    {
        "name": "mira-prod-backend",
        "status": "ACTIVE",
        "desired": 0,
        "running": 0,
        "pending": 0
    },
    {
        "name": "mira-prod-frontend",
        "status": "ACTIVE",
        "desired": 0,
        "running": 0,
        "pending": 0
    }
]
```
Backend task definition volumes/mounts:
```json
{
    "taskDefinitionArn": "arn:aws-us-gov:ecs:us-gov-west-1:574823419003:task-definition/mira-prod-backend-task:28",
    "volumes": [],
    "mountPoints": [
        []
    ]
}
```
Frontend task definition volumes/mounts:
```json
{
    "taskDefinitionArn": "arn:aws-us-gov:ecs:us-gov-west-1:574823419003:task-definition/mira-prod-frontend-task:16",
    "volumes": [],
    "mountPoints": [
        []
    ]
}
```

## 9) FAISS Indicator Search (names only)

### Region: us-gov-west-1
Timestamp: 2026-03-04 21:33:11 UTC
Secrets matching faiss/json/nasa/mira:
```json
[]
```
SSM parameters matching faiss/json/nasa/mira:
```json
[]
```

### Region: us-gov-east-1
Timestamp: 2026-03-04 21:33:14 UTC
Secrets matching faiss/json/nasa/mira:
```json
[]
```
SSM parameters matching faiss/json/nasa/mira:
```json
[]
```

## Conclusion Snapshot
- SQL/Postgres resources: empty
- RDS snapshots/backups: empty
- S3 buckets: empty
- CloudWatch log groups: empty
- Secrets: empty
- Persistent volume surfaces (EFS/FSx/EBS): empty
- ECS persistent mounts: none
