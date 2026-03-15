# AWS DB Deletion Record (2026-03-04)

Requested action: delete all PostgreSQL/SQL databases from AWS GovCloud for this account.

## Account/Scope
- Date: 2026-03-04
- Regions checked: `us-gov-west-1`, `us-gov-east-1`
- Services checked: Amazon RDS DB Instances, Amazon RDS DB Clusters (Aurora)

## Inventory Found Before Deletion

### `us-gov-west-1`
- DB Instance Identifier: `mira-prod-postgres`
- Engine: `postgres`
- Engine Version: `17.6`
- Status at discovery: `available`
- Initial DB name: `mira_h2`
- Endpoint: `mira-prod-postgres.cg9f4svalwcm.us-gov-west-1.rds.amazonaws.com:5432`
- Deletion protection: `true`
- ARN: `arn:aws-us-gov:rds:us-gov-west-1:574823419003:db:mira-prod-postgres`

### `us-gov-west-1` Clusters
- None

### `us-gov-east-1`
- DB Instances: None
- DB Clusters: None

## Deletion Execution
- `mira-prod-postgres` deletion protection disabled.
- `mira-prod-postgres` deletion initiated with:
  - `skip-final-snapshot=true`
  - `delete-automated-backups=true`
- Post-delete status check:
  - `us-gov-west-1`: `mira-prod-postgres` status = `deleting`
  - `us-gov-east-1`: no DB instances present

## Notes
- This record captures resources that existed immediately prior to deletion.
- If historical recovery is required, only previously retained backups/snapshots (if any) would remain.
