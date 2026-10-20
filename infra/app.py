#!/usr/bin/env python3
"""Insightly infrastructure (AWS CDK v2, Python).

Stacks, deployed in this order by `cdk deploy --all`:
  InsightlyData      S3 data + Athena results buckets, Glue databases, Athena workgroup
  InsightlyNetwork   VPC (2 AZ, 1 NAT), S3 gateway endpoint
  InsightlyDatabase  Aurora PostgreSQL Serverless v2 (pgvector, LangGraph checkpoints)
  InsightlyService   ECS Fargate (Graviton) + ALB, Cognito, Secrets Manager, least-privilege IAM
  InsightlyOps       CloudWatch dashboard + alarms, SNS alerts, AWS Budgets
"""

import os
import sys

import aws_cdk as cdk

sys.path.insert(0, os.path.dirname(__file__))

from stacks.data_stack import DataStack  # noqa: E402
from stacks.database_stack import DatabaseStack  # noqa: E402
from stacks.network_stack import NetworkStack  # noqa: E402
from stacks.ops_stack import OpsStack  # noqa: E402
from stacks.service_stack import ServiceStack  # noqa: E402

app = cdk.App()
env = cdk.Environment(
    account=os.environ.get("CDK_DEFAULT_ACCOUNT"),
    region=app.node.try_get_context("region") or os.environ.get("CDK_DEFAULT_REGION"),
)
cdk.Tags.of(app).add("project", "insightly")
cdk.Tags.of(app).add("cost-center", "analytics-ai")

data = DataStack(app, "InsightlyData", env=env)
net = NetworkStack(app, "InsightlyNetwork", env=env)
db = DatabaseStack(app, "InsightlyDatabase", vpc=net.vpc, env=env)
svc = ServiceStack(app, "InsightlyService", vpc=net.vpc, data=data, db=db, env=env)
OpsStack(app, "InsightlyOps", service=svc, env=env)

app.synth()
