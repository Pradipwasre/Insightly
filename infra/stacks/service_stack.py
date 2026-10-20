import os

import aws_cdk as cdk
from aws_cdk import aws_cognito as cognito
from aws_cdk import aws_ec2 as ec2
from aws_cdk import aws_ecr_assets as ecr_assets
from aws_cdk import aws_ecs as ecs
from aws_cdk import aws_ecs_patterns as ecs_patterns
from aws_cdk import aws_iam as iam
from aws_cdk import aws_logs as logs
from aws_cdk import aws_secretsmanager as sm
from constructs import Construct

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))


class ServiceStack(cdk.Stack):
    def __init__(self, scope: Construct, id: str, *, vpc: ec2.IVpc, data, db, **kw) -> None:
        super().__init__(scope, id, **kw)

        # --- identity -----------------------------------------------------------------------
        self.user_pool = cognito.UserPool(
            self,
            "Users",
            user_pool_name="insightly-users",
            self_sign_up_enabled=False,
            sign_in_aliases=cognito.SignInAliases(email=True),
            password_policy=cognito.PasswordPolicy(min_length=12),
            account_recovery=cognito.AccountRecovery.EMAIL_ONLY,
            removal_policy=cdk.RemovalPolicy.DESTROY,
        )
        self.client = self.user_pool.add_client(
            "WebClient",
            auth_flows=cognito.AuthFlow(user_password=True, user_srp=True),
            generate_secret=False,
            id_token_validity=cdk.Duration.hours(1),
        )
        cognito.CfnUserPoolGroup(
            self, "AdminGroup", user_pool_id=self.user_pool.user_pool_id, group_name="admin"
        )

        # --- secrets: created once by a human with the AWS CLI (guide step 7), so the key
        # never appears in code, CloudFormation templates or CI logs ---------------------
        self.openai_secret = sm.Secret.from_secret_name_v2(self, "OpenAIKey", "insightly/openai-api-key")

        # --- service ------------------------------------------------------------------------
        cluster = ecs.Cluster(self, "Cluster", vpc=vpc, container_insights_v2=ecs.ContainerInsights.ENABLED)
        log_group = logs.LogGroup(
            self,
            "ApiLogs",
            log_group_name="/insightly/api",
            retention=logs.RetentionDays.TWO_WEEKS,
            removal_policy=cdk.RemovalPolicy.DESTROY,
        )
        env = {
            "INSIGHTLY_ENV": "prod",
            "INSIGHTLY_LLM_PROVIDER": "openai",
            "INSIGHTLY_QUERY_ENGINE": "athena",
            "INSIGHTLY_ATHENA_WORKGROUP": "insightly",
            "INSIGHTLY_ATHENA_DATABASE": "insightly_curated",
            "INSIGHTLY_VECTOR_STORE": "pgvector",
            "INSIGHTLY_CHECKPOINTER": "postgres",
            "INSIGHTLY_DATABASE_SECRET_ARN": db.secret.secret_arn,
            "INSIGHTLY_AUTH_MODE": "cognito",
            "INSIGHTLY_COGNITO_USER_POOL_ID": self.user_pool.user_pool_id,
            "INSIGHTLY_COGNITO_CLIENT_ID": self.client.user_pool_client_id,
            "INSIGHTLY_EMIT_CLOUDWATCH_EMF": "true",
            "INSIGHTLY_CORS_ORIGINS": '["*"]',
            "AWS_REGION": self.region,
        }
        self.service = ecs_patterns.ApplicationLoadBalancedFargateService(
            self,
            "Api",
            cluster=cluster,
            cpu=1024,
            memory_limit_mib=2048,
            desired_count=1,
            min_healthy_percent=100,
            public_load_balancer=True,
            circuit_breaker=ecs.DeploymentCircuitBreaker(rollback=True),
            runtime_platform=ecs.RuntimePlatform(
                cpu_architecture=ecs.CpuArchitecture.ARM64,  # Graviton: ~20% cheaper per vCPU
                operating_system_family=ecs.OperatingSystemFamily.LINUX,
            ),
            task_subnets=ec2.SubnetSelection(subnet_type=ec2.SubnetType.PRIVATE_WITH_EGRESS),
            task_image_options=ecs_patterns.ApplicationLoadBalancedTaskImageOptions(
                image=ecs.ContainerImage.from_asset(
                    REPO_ROOT,
                    platform=ecr_assets.Platform.LINUX_ARM64,
                    exclude=[
                        "infra/cdk.out",
                        ".venv",
                        ".git",
                        ".cache",
                        "data",
                        "reports",
                        "**/__pycache__",
                        "**/node_modules",
                    ],
                ),
                container_port=8000,
                environment=env,
                secrets={"OPENAI_API_KEY": ecs.Secret.from_secrets_manager(self.openai_secret)},
                log_driver=ecs.LogDrivers.aws_logs(stream_prefix="api", log_group=log_group),
            ),
        )
        self.service.target_group.configure_health_check(path="/healthz", healthy_http_codes="200")
        self.service.target_group.set_attribute("deregistration_delay.timeout_seconds", "15")
        scaling = self.service.service.auto_scale_task_count(min_capacity=1, max_capacity=3)
        scaling.scale_on_cpu_utilization("Cpu", target_utilization_percent=60)

        # Ingress rule lives in this stack to avoid a cross-stack dependency cycle.
        ec2.CfnSecurityGroupIngress(
            self,
            "ApiToAurora",
            group_id=db.sg.security_group_id,
            ip_protocol="tcp",
            from_port=5432,
            to_port=5432,
            description="API to Aurora",
            source_security_group_id=self.service.service.connections.security_groups[0].security_group_id,
        )
        db.secret.grant_read(self.service.task_definition.task_role)

        # --- least-privilege data access -----------------------------------------------------
        role = self.service.task_definition.task_role
        wg_arn = f"arn:aws:athena:{self.region}:{self.account}:workgroup/insightly"
        role.add_to_principal_policy(
            iam.PolicyStatement(
                actions=[
                    "athena:StartQueryExecution",
                    "athena:GetQueryExecution",
                    "athena:GetQueryResults",
                    "athena:StopQueryExecution",
                    "athena:GetWorkGroup",
                ],
                resources=[wg_arn],
            )
        )
        cat = f"arn:aws:glue:{self.region}:{self.account}"
        role.add_to_principal_policy(
            iam.PolicyStatement(
                actions=[
                    "glue:GetDatabase",
                    "glue:GetDatabases",
                    "glue:GetTable",
                    "glue:GetTables",
                    "glue:GetPartition",
                    "glue:GetPartitions",
                ],
                resources=[
                    f"{cat}:catalog",
                    f"{cat}:database/insightly_curated",
                    f"{cat}:table/insightly_curated/*",
                ],
            )
        )
        data.data_bucket.grant_read(role, "curated/*")
        data.results_bucket.grant_read_write(role)
        # Defence in depth: even a bypassed SQL firewall cannot read the PII table.
        role.add_to_principal_policy(
            iam.PolicyStatement(
                effect=iam.Effect.DENY,
                actions=["glue:GetTable", "glue:GetPartitions", "s3:GetObject"],
                resources=[
                    f"{cat}:table/insightly_curated/users_pii",
                    f"{data.data_bucket.bucket_arn}/curated/users_pii/*",
                ],
            )
        )

        cdk.CfnOutput(self, "ApiUrl", value=f"http://{self.service.load_balancer.load_balancer_dns_name}")
        cdk.CfnOutput(self, "UserPoolId", value=self.user_pool.user_pool_id)
        cdk.CfnOutput(self, "UserPoolClientId", value=self.client.user_pool_client_id)
        cdk.CfnOutput(self, "OpenAISecretName", value=self.openai_secret.secret_name)
