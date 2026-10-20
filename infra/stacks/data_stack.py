import aws_cdk as cdk
from aws_cdk import aws_athena as athena
from aws_cdk import aws_glue as glue
from aws_cdk import aws_s3 as s3
from constructs import Construct


class DataStack(cdk.Stack):
    def __init__(self, scope: Construct, id: str, **kw) -> None:
        super().__init__(scope, id, **kw)
        retain = bool(self.node.try_get_context("retainData"))
        removal = cdk.RemovalPolicy.RETAIN if retain else cdk.RemovalPolicy.DESTROY

        self.data_bucket = s3.Bucket(
            self,
            "DataBucket",
            bucket_name=f"insightly-data-{self.account}-{self.region}",
            block_public_access=s3.BlockPublicAccess.BLOCK_ALL,
            encryption=s3.BucketEncryption.S3_MANAGED,
            enforce_ssl=True,
            removal_policy=removal,
            auto_delete_objects=not retain,
            lifecycle_rules=[
                # staging copies are only needed while CTAS runs
                s3.LifecycleRule(prefix="staging/", expiration=cdk.Duration.days(30)),
                s3.LifecycleRule(abort_incomplete_multipart_upload_after=cdk.Duration.days(1)),
            ],
        )
        self.results_bucket = s3.Bucket(
            self,
            "AthenaResults",
            bucket_name=f"insightly-athena-results-{self.account}-{self.region}",
            block_public_access=s3.BlockPublicAccess.BLOCK_ALL,
            encryption=s3.BucketEncryption.S3_MANAGED,
            enforce_ssl=True,
            removal_policy=cdk.RemovalPolicy.DESTROY,
            auto_delete_objects=True,
            # query results are throwaway: expiring them keeps S3 cost near zero
            lifecycle_rules=[s3.LifecycleRule(expiration=cdk.Duration.days(7))],
        )
        for name in ("insightly_raw", "insightly_curated"):
            glue.CfnDatabase(
                self,
                f"Db{name}",
                catalog_id=self.account,
                database_input=glue.CfnDatabase.DatabaseInputProperty(name=name),
            )

        self.workgroup = athena.CfnWorkGroup(
            self,
            "Workgroup",
            name="insightly",
            state="ENABLED",
            recursive_delete_option=True,
            work_group_configuration=athena.CfnWorkGroup.WorkGroupConfigurationProperty(
                enforce_work_group_configuration=True,
                publish_cloud_watch_metrics_enabled=True,
                # hard cost cap: any single query scanning more than 1 GB is cancelled
                bytes_scanned_cutoff_per_query=1_000_000_000,
                engine_version=athena.CfnWorkGroup.EngineVersionProperty(
                    selected_engine_version="Athena engine version 3"
                ),
                result_configuration=athena.CfnWorkGroup.ResultConfigurationProperty(
                    output_location=f"s3://{self.results_bucket.bucket_name}/results/",
                    encryption_configuration=athena.CfnWorkGroup.EncryptionConfigurationProperty(
                        encryption_option="SSE_S3"
                    ),
                ),
            ),
        )
        cdk.CfnOutput(self, "DataBucketName", value=self.data_bucket.bucket_name)
        cdk.CfnOutput(self, "AthenaWorkgroup", value="insightly")
