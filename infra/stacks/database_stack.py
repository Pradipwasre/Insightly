import aws_cdk as cdk
from aws_cdk import aws_ec2 as ec2
from aws_cdk import aws_rds as rds
from constructs import Construct


class DatabaseStack(cdk.Stack):
    """Aurora PostgreSQL Serverless v2 with pgvector.

    Holds LangGraph checkpoints (conversation state), long-term memory and the semantic-layer
    vectors. min capacity 0 + auto-pause means it costs storage only when idle.
    """

    def __init__(self, scope: Construct, id: str, *, vpc: ec2.IVpc, **kw) -> None:
        super().__init__(scope, id, **kw)
        self.sg = ec2.SecurityGroup(self, "DbSg", vpc=vpc, description="Insightly Aurora")
        self.cluster = rds.DatabaseCluster(
            self,
            "Aurora",
            engine=rds.DatabaseClusterEngine.aurora_postgres(
                version=rds.AuroraPostgresEngineVersion.VER_17_5
            ),
            writer=rds.ClusterInstance.serverless_v2("writer"),
            serverless_v2_min_capacity=0,
            serverless_v2_max_capacity=2,
            serverless_v2_auto_pause_duration=cdk.Duration.minutes(15),
            default_database_name="insightly",
            credentials=rds.Credentials.from_generated_secret("insightly_admin"),
            vpc=vpc,
            vpc_subnets=ec2.SubnetSelection(subnet_type=ec2.SubnetType.PRIVATE_WITH_EGRESS),
            security_groups=[self.sg],
            storage_encrypted=True,
            backup=rds.BackupProps(retention=cdk.Duration.days(7)),
            removal_policy=cdk.RemovalPolicy.SNAPSHOT,
        )
        self.secret = self.cluster.secret
        cdk.CfnOutput(self, "DbSecretArn", value=self.secret.secret_arn)
